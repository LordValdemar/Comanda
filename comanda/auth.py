"""Login, usuários, permissões por papel e proteção CSRF."""

import hmac
import logging
import secrets
import threading
import time
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

bp = Blueprint("auth", __name__)
log = logging.getLogger("comanda.auth")

PAPEIS = {
    "admin": "Administrador",   # tudo, inclusive cardápio, usuários e ajustes
    "caixa": "Caixa",           # comandas, fechamento, cancelamentos e relatórios
    "garcom": "Garçom",         # abre comandas e lança pedidos
    "cozinha": "Cozinha",       # só a tela da cozinha
}
# Página inicial de cada papel depois do login.
INICIO = {"admin": "comandas.lista", "caixa": "comandas.lista", "garcom": "comandas.lista", "cozinha": "cozinha.tela"}
SENHA_MINIMA = 6  # a equipe entra várias vezes por dia, no celular: 6 é o mínimo razoável numa rede local
MAX_TENTATIVAS = 5
JANELA_BLOQUEIO = 15 * 60  # segundos


class ErroUsuario(ValueError):
    """Dados de usuário inválidos (mensagem pode ser mostrada na tela)."""


# ---------------------------------------------------------------------------
# Regras de usuário (usadas pelas telas e pelo gerenciar.py)
# ---------------------------------------------------------------------------

def validar_senha(senha):
    if len(senha) < SENHA_MINIMA:
        raise ErroUsuario(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")


def criar_usuario(conexao, usuario, senha, papel="garcom"):
    usuario = usuario.strip()
    if not usuario or len(usuario) > 40:
        raise ErroUsuario("Informe um nome de usuário (até 40 caracteres).")
    if papel not in PAPEIS:
        raise ErroUsuario("Papel inválido.")
    validar_senha(senha)
    if conexao.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
        raise ErroUsuario(f"O usuário “{usuario}” já existe. Escolha outro nome.")
    with conexao:
        cursor = conexao.execute(
            "INSERT INTO usuarios (usuario, senha_hash, papel, token_sessao) VALUES (?, ?, ?, ?)",
            (usuario, generate_password_hash(senha), papel, secrets.token_hex(16)),
        )
    return cursor.lastrowid


def trocar_senha(conexao, usuario_id, senha_nova):
    validar_senha(senha_nova)
    with conexao:
        # Trocar o token derruba as sessões abertas em outros aparelhos.
        conexao.execute(
            "UPDATE usuarios SET senha_hash = ?, token_sessao = ? WHERE id = ?",
            (generate_password_hash(senha_nova), secrets.token_hex(16), usuario_id),
        )


def existe_usuario(conexao):
    return conexao.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None


def admins_ativos(conexao):
    return conexao.execute("SELECT COUNT(*) FROM usuarios WHERE papel = 'admin' AND ativo = 1").fetchone()[0]


# ---------------------------------------------------------------------------
# Limite de tentativas de senha, por IP
# ---------------------------------------------------------------------------

_tentativas = {}
_trava_tentativas = threading.Lock()


def _bloqueado(ip):
    agora = time.monotonic()
    with _trava_tentativas:
        recentes = [t for t in _tentativas.get(ip, []) if agora - t < JANELA_BLOQUEIO]
        if recentes:
            _tentativas[ip] = recentes
        else:
            _tentativas.pop(ip, None)
        return len(recentes) >= MAX_TENTATIVAS


def _registrar_falha(ip):
    with _trava_tentativas:
        _tentativas.setdefault(ip, []).append(time.monotonic())


def _limpar_falhas(ip):
    with _trava_tentativas:
        _tentativas.pop(ip, None)


# ---------------------------------------------------------------------------
# Sessão, CSRF e decoradores
# ---------------------------------------------------------------------------

def token_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _verificar_csrf():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Formulários mandam o campo csrf_token; a tela da cozinha (fetch) manda o cabeçalho.
    enviado = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    esperado = session.get("csrf", "")
    if not esperado or not hmac.compare_digest(enviado, esperado):
        log.warning("CSRF inválido em %s vindo de %s", request.path, request.remote_addr)
        abort(400)


def _carregar_usuario():
    g.usuario = None
    usuario_id = session.get("usuario_id")
    if usuario_id is None:
        return
    linha = db.obter().execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    # Sessão vale só enquanto o usuário existe, está ativo e não trocou a senha.
    if linha is None or not linha["ativo"] or not hmac.compare_digest(session.get("token", ""), linha["token_sessao"]):
        session.clear()
        return
    g.usuario = linha


def login_obrigatorio(funcao):
    @wraps(funcao)
    def interna(*args, **kwargs):
        if g.usuario is None:
            if request.path.startswith("/api/"):
                return {"erro": "faça login de novo"}, 401
            return redirect(url_for("auth.entrar", proximo=request.full_path if request.query_string else request.path))
        return funcao(*args, **kwargs)
    return interna


def papel_exigido(*papeis):
    """Libera a rota só para os papéis indicados (o admin sempre pode)."""
    def decorador(funcao):
        @wraps(funcao)
        @login_obrigatorio
        def interna(*args, **kwargs):
            if g.usuario["papel"] != "admin" and g.usuario["papel"] not in papeis:
                abort(403)
            return funcao(*args, **kwargs)
        return interna
    return decorador


def pode(*papeis):
    """Para os templates: o usuário logado tem um destes papéis (ou é admin)?"""
    return g.usuario is not None and (g.usuario["papel"] == "admin" or g.usuario["papel"] in papeis)


def _proximo_seguro(destino):
    # Só caminhos internos: evita redirecionar para outro site depois do login.
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return None


def _iniciar_sessao(linha):
    session.clear()
    session.permanent = True
    session["usuario_id"] = linha["id"]
    session["token"] = linha["token_sessao"]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@bp.route("/configurar", methods=["GET", "POST"])
def configurar():
    """Primeiro acesso: cria o administrador. Some depois que existe um usuário."""
    conexao = db.obter()
    if existe_usuario(conexao):
        return redirect(url_for("auth.entrar"))
    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        senha = request.form.get("senha", "")
        if senha != request.form.get("confirmacao", ""):
            flash("As senhas não conferem.", "erro")
        else:
            try:
                usuario_id = criar_usuario(conexao, usuario, senha, "admin")
            except ErroUsuario as erro:
                flash(str(erro), "erro")
            else:
                nome = request.form.get("estabelecimento", "").strip()
                if nome:
                    db.gravar_config("nome_estabelecimento", nome[:80])
                _iniciar_sessao(conexao.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone())
                log.info("Administrador “%s” criado no primeiro acesso", usuario)
                flash("Tudo pronto! Comece cadastrando o cardápio.", "ok")
                return redirect(url_for("cardapio.lista"))
    return render_template("configurar.html")


@bp.route("/login", methods=["GET", "POST"])
def entrar():
    conexao = db.obter()
    if not existe_usuario(conexao):
        return redirect(url_for("auth.configurar"))
    if g.usuario is not None:
        return redirect(url_for(INICIO[g.usuario["papel"]]))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if _bloqueado(ip):
            flash("Muitas tentativas erradas. Espere 15 minutos e tente de novo.", "erro")
            return render_template("login.html"), 429
        nome = request.form.get("usuario", "").strip()
        linha = conexao.execute("SELECT * FROM usuarios WHERE usuario = ?", (nome,)).fetchone()
        if linha is None or not check_password_hash(linha["senha_hash"], request.form.get("senha", "")):
            _registrar_falha(ip)
            log.warning("Senha errada para “%s” vindo de %s", nome, ip)
            flash("Usuário ou senha incorretos.", "erro")
            return render_template("login.html"), 401
        if not linha["ativo"]:
            flash("Este usuário está desativado. Fale com o administrador.", "erro")
            return render_template("login.html"), 403
        _limpar_falhas(ip)
        _iniciar_sessao(linha)
        log.info("Login de “%s” vindo de %s", linha["usuario"], ip)
        return redirect(_proximo_seguro(request.args.get("proximo")) or url_for(INICIO[linha["papel"]]))
    return render_template("login.html")


@bp.route("/sair", methods=["POST"])
def sair():
    session.clear()
    return redirect(url_for("auth.entrar"))


@bp.route("/")
def inicio():
    if g.usuario is None:
        return redirect(url_for("auth.entrar"))
    return redirect(url_for(INICIO[g.usuario["papel"]]))


@bp.route("/minha-senha", methods=["GET", "POST"])
@login_obrigatorio
def minha_senha():
    if request.method == "POST":
        conexao = db.obter()
        if not check_password_hash(g.usuario["senha_hash"], request.form.get("atual", "")):
            flash("A senha atual está errada.", "erro")
        elif request.form.get("nova", "") != request.form.get("confirmacao", ""):
            flash("As senhas novas não conferem.", "erro")
        else:
            try:
                trocar_senha(conexao, g.usuario["id"], request.form.get("nova", ""))
            except ErroUsuario as erro:
                flash(str(erro), "erro")
            else:
                _iniciar_sessao(conexao.execute("SELECT * FROM usuarios WHERE id = ?", (g.usuario["id"],)).fetchone())
                flash("Senha trocada.", "ok")
                return redirect(url_for("auth.inicio"))
    return render_template("minha_senha.html")


@bp.route("/usuarios", methods=["GET", "POST"])
@papel_exigido("admin")
def usuarios():
    conexao = db.obter()
    if request.method == "POST":
        try:
            criar_usuario(conexao, request.form.get("usuario", ""), request.form.get("senha", ""),
                          request.form.get("papel", ""))
        except ErroUsuario as erro:
            flash(str(erro), "erro")
        else:
            flash("Usuário criado.", "ok")
        return redirect(url_for("auth.usuarios"))
    lista = conexao.execute("SELECT * FROM usuarios ORDER BY ativo DESC, usuario").fetchall()
    return render_template("usuarios.html", usuarios=lista, papeis=PAPEIS)


@bp.route("/usuarios/<int:usuario_id>", methods=["POST"])
@papel_exigido("admin")
def alterar_usuario(usuario_id):
    conexao = db.obter()
    alvo = conexao.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if alvo is None:
        abort(404)
    acao = request.form.get("acao")
    eh_ultimo_admin = alvo["papel"] == "admin" and alvo["ativo"] and admins_ativos(conexao) <= 1
    try:
        if acao == "senha":
            trocar_senha(conexao, usuario_id, request.form.get("senha", ""))
            flash(f"Senha de “{alvo['usuario']}” trocada.", "ok")
        elif acao == "papel":
            papel = request.form.get("papel", "")
            if papel not in PAPEIS:
                raise ErroUsuario("Papel inválido.")
            if eh_ultimo_admin and papel != "admin":
                raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")
            with conexao:
                conexao.execute("UPDATE usuarios SET papel = ? WHERE id = ?", (papel, usuario_id))
            flash(f"“{alvo['usuario']}” agora é {PAPEIS[papel]}.", "ok")
        elif acao == "ativo":
            ativar = not alvo["ativo"]
            if not ativar and eh_ultimo_admin:
                raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")
            with conexao:
                # Desativar também derruba as sessões abertas (troca o token).
                conexao.execute("UPDATE usuarios SET ativo = ?, token_sessao = ? WHERE id = ?",
                                (1 if ativar else 0, secrets.token_hex(16), usuario_id))
            flash(f"“{alvo['usuario']}” {'reativado' if ativar else 'desativado'}.", "ok")
        else:
            abort(400)
    except ErroUsuario as erro:
        flash(str(erro), "erro")
    return redirect(url_for("auth.usuarios"))


def registrar(app):
    app.register_blueprint(bp)
    app.before_request(_carregar_usuario)
    app.before_request(_verificar_csrf)
    app.jinja_env.globals["csrf_token"] = token_csrf
    app.jinja_env.globals["pode"] = pode
    app.jinja_env.globals["PAPEIS"] = PAPEIS

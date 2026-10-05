"""Login, usuários, permissões por papel e proteção CSRF.

As regras das contas vêm do núcleo (src/domain/contas/locais.py); aqui ficam a sessão, o CSRF e as rotas.
"""

import hmac
import logging
import secrets
import time
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from src.domain.contas import PAPEIS as _TODOS_OS_PAPEIS
from src.domain.contas import CodigoIncorreto, ErroUsuario, ServicoDeContasLocais
from src.domain.contas.entidades import JANELA_BLOQUEIO, MAX_TENTATIVAS
from src.domain.contas.locais import SENHA_MINIMA_LOCAL as SENHA_MINIMA
from src.domain.contas.locais import BloqueadoAqui, Desativado
from src.domain.erros import NaoEncontrado
from src.domain.tentativas import LimiteDeTentativas
from src.infrastructure.senhas import SenhasWerkzeug
from src.infrastructure.sqlite import ConsultasDeUsuarios, RepositorioDeContasSQLite

from . import db, totp

__all__ = ["PAPEIS", "SENHA_MINIMA", "ErroUsuario", "criar_usuario", "desativar_2fa", "trocar_senha"]

bp = Blueprint("auth", __name__)
log = logging.getLogger("comanda.auth")

# Os papéis da Comanda (o editor é do Painel de Propagandas, que esta versão não tem).
PAPEIS = {papel: _TODOS_OS_PAPEIS[papel] for papel in ("admin", "caixa", "garcom", "cozinha")}
# Página inicial de cada papel depois do login.
INICIO = {"admin": "comandas.lista", "caixa": "comandas.lista", "garcom": "comandas.lista", "cozinha": "cozinha.tela"}
VALIDADE_ETAPA_2FA = 5 * 60  # tempo para digitar o código depois da senha
_tentativas = LimiteDeTentativas(MAX_TENTATIVAS, JANELA_BLOQUEIO)   # senha e código, por IP (neste processo)


def servico(conexao=None):
    """As regras das contas de uma loja só (núcleo: src/domain/contas/locais.py) com o banco daqui."""
    return ServicoDeContasLocais(RepositorioDeContasSQLite(conexao or db.obter()), SenhasWerkzeug(), PAPEIS, _tentativas)


def _usuario(conexao, usuario_id):
    return ConsultasDeUsuarios(conexao).usuario(usuario_id)


# Atalhos com os nomes de antes (gerenciar.py e testes).

def criar_usuario(conexao, usuario, senha, papel="garcom"):
    return servico(conexao).criar(usuario, senha, papel)


def trocar_senha(conexao, usuario_id, senha_nova):
    servico(conexao).trocar_senha(usuario_id, senha_nova)


def desativar_2fa(conexao, usuario_id):
    servico(conexao).desativar_2fa(usuario_id)


def existe_usuario(conexao):
    return servico(conexao).existe_alguem()


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
    linha = _usuario(db.obter(), usuario_id)
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
        interna.papeis = {"admin", *papeis}  # para a varredura de permissões dos testes
        return interna
    return decorador


def pode(*papeis):
    """Para os templates: o usuário logado tem um destes papéis (ou é admin)?"""
    return g.usuario is not None and (g.usuario["papel"] == "admin" or g.usuario["papel"] in papeis)


def pode_fechar_conta():
    """Para os botões: fecha contas (ou pode, pedindo autorização). Quem decide é a tela de Permissões."""
    from . import permissoes  # evita importação circular

    return permissoes.permite("fechar_conta")


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
                _iniciar_sessao(_usuario(conexao, usuario_id))
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
        nome = request.form.get("usuario", "").strip()
        try:
            conta = servico(conexao).entrar(nome, request.form.get("senha", ""), ip)
        except BloqueadoAqui as erro:
            flash(str(erro), "erro")
            return render_template("login.html"), 429
        except Desativado as erro:
            flash(str(erro), "erro")
            return render_template("login.html"), 403
        except ErroUsuario as erro:
            log.warning("Senha errada para “%s” vindo de %s", nome, ip)
            flash(str(erro), "erro")
            return render_template("login.html"), 401
        proximo = _proximo_seguro(request.args.get("proximo"))
        if conta.tem_2fa:
            # Senha certa, mas ainda falta o código do celular: a sessão ainda não vale.
            session.clear()
            session["2fa_usuario"] = conta.id
            session["2fa_desde"] = time.time()
            session["2fa_proximo"] = proximo
            return redirect(url_for("auth.codigo"))
        _iniciar_sessao(_usuario(conexao, conta.id))
        log.info("Login de “%s” vindo de %s", conta.usuario, ip)
        return redirect(proximo or url_for(INICIO[conta.papel]))
    return render_template("login.html")


@bp.route("/login/codigo", methods=["GET", "POST"])
def codigo():
    """Segunda etapa do login: o código de 6 dígitos do aplicativo autenticador."""
    usuario_id = session.get("2fa_usuario")
    if usuario_id is None or time.time() - session.get("2fa_desde", 0) > VALIDADE_ETAPA_2FA:
        session.clear()
        flash("Entre de novo com usuário e senha.", "erro")
        return redirect(url_for("auth.entrar"))
    conexao = db.obter()
    contas = servico(conexao)
    conta = contas.pode_pedir_codigo(usuario_id)
    if conta is None:
        session.clear()
        return redirect(url_for("auth.entrar"))
    if request.method == "POST":
        ip = request.remote_addr or "?"
        try:
            conta = contas.confirmar_codigo(conta, request.form.get("codigo", ""), ip)
        except BloqueadoAqui as erro:
            flash(str(erro), "erro")
            return render_template("login_codigo.html"), 429
        except CodigoIncorreto as erro:
            log.warning("Código de verificação errado para “%s” vindo de %s", conta.usuario, ip)
            flash(str(erro), "erro")
            return render_template("login_codigo.html"), 401
        proximo = session.get("2fa_proximo")
        _iniciar_sessao(_usuario(conexao, conta.id))
        log.info("Login de “%s” (com verificação em duas etapas) vindo de %s", conta.usuario, ip)
        return redirect(proximo or url_for(INICIO[conta.papel]))
    return render_template("login_codigo.html")


@bp.route("/sair", methods=["POST"])
def sair():
    # Com o ponto aberto, sair é registrar a saída (na página do ponto, com ou sem o QR code).
    if g.get("ponto_aberto"):
        flash("Você está com o ponto aberto. Para sair, registre a saída.", "erro")
        return redirect(url_for("ponto.meu"))
    session.clear()
    return redirect(url_for("auth.entrar"))


@bp.route("/")
def inicio():
    if g.usuario is None:
        return redirect(url_for("auth.entrar"))
    return redirect(url_for(INICIO[g.usuario["papel"]]))


@bp.route("/minha-conta")
@login_obrigatorio
def minha_conta():
    contexto = {}
    if not g.usuario["totp_segredo"]:
        # O segredo novo fica na sessão até ser confirmado com um código: QR lido pela metade não tranca ninguém.
        if "2fa_novo" not in session:
            session["2fa_novo"] = totp.novo_segredo()
        emissor = db.ler_config("nome_estabelecimento") or "Comanda"
        contexto = {"segredo": session["2fa_novo"], "qr": totp.qr_code(session["2fa_novo"], g.usuario["usuario"], emissor)}
    return render_template("minha_conta.html", **contexto)


def _conta_logada():
    return servico().conta(g.usuario["id"])


@bp.route("/minha-conta/2fa/ativar", methods=["POST"])
@login_obrigatorio
def ativar_2fa():
    segredo = session.get("2fa_novo")
    if g.usuario["totp_segredo"] or not segredo:
        return redirect(url_for("auth.minha_conta"))
    try:
        servico().ativar_2fa(_conta_logada(), segredo, request.form.get("codigo", ""))
    except ErroUsuario as erro:
        flash(str(erro), "erro")
        return redirect(url_for("auth.minha_conta"))
    session.pop("2fa_novo", None)
    log.info("Verificação em duas etapas ativada para “%s”", g.usuario["usuario"])
    flash("Verificação em duas etapas ativada. Da próxima vez, o código do aplicativo será pedido ao entrar.", "ok")
    return redirect(url_for("auth.minha_conta"))


@bp.route("/minha-conta/2fa/desativar", methods=["POST"])
@login_obrigatorio
def desativar_2fa_proprio():
    try:
        servico().desativar_2fa_propria(_conta_logada(), request.form.get("senha", ""), request.form.get("codigo", ""))
    except ErroUsuario as erro:
        flash(str(erro), "erro")
    else:
        _iniciar_sessao(_usuario(db.obter(), g.usuario["id"]))
        log.info("Verificação em duas etapas desativada por “%s”", g.usuario["usuario"])
        flash("Verificação em duas etapas desativada.", "ok")
    return redirect(url_for("auth.minha_conta"))


@bp.route("/minha-senha", methods=["GET", "POST"])
@login_obrigatorio
def minha_senha():
    if request.method == "GET":
        return redirect(url_for("auth.minha_conta"))
    try:
        servico().mudar_minha_senha(_conta_logada(), request.form.get("atual", ""), request.form.get("nova", ""),
                                    request.form.get("confirmacao", ""))
    except ErroUsuario as erro:
        flash(str(erro), "erro")
        return redirect(url_for("auth.minha_conta"))
    _iniciar_sessao(_usuario(db.obter(), g.usuario["id"]))
    flash("Senha trocada.", "ok")
    return redirect(url_for("auth.inicio"))


@bp.route("/usuarios", methods=["GET", "POST"])
@papel_exigido("admin")
def usuarios():
    if request.method == "POST":
        try:
            criar_usuario(db.obter(), request.form.get("usuario", ""), request.form.get("senha", ""),
                          request.form.get("papel", ""))
        except ErroUsuario as erro:
            flash(str(erro), "erro")
        else:
            flash("Usuário criado.", "ok")
        return redirect(url_for("auth.usuarios"))
    return render_template("usuarios.html", usuarios=ConsultasDeUsuarios(db.obter()).equipe(), papeis=PAPEIS)


@bp.route("/usuarios/<int:usuario_id>", methods=["POST"])
@papel_exigido("admin")
def alterar_usuario(usuario_id):
    contas = servico()
    acao = request.form.get("acao")
    try:
        alvo = contas.conta(usuario_id)   # alguém que não existe: 404
        if acao == "senha":
            contas.trocar_senha(usuario_id, request.form.get("senha", ""))
            flash(f"Senha de “{alvo.usuario}” trocada.", "ok")
        elif acao == "papel":
            papel = request.form.get("papel", "")
            alvo = contas.mudar_papel(usuario_id, papel)
            flash(f"“{alvo.usuario}” agora é {PAPEIS[papel]}.", "ok")
        elif acao == "fecha_conta":
            alvo, novo = contas.alternar_fecha_conta(usuario_id)
            flash(f"“{alvo.usuario}” {'agora pode' if novo else 'não pode mais'} fechar contas.", "ok")
        elif acao == "desativar_2fa":
            contas.desativar_2fa(usuario_id)
            log.info("Verificação em duas etapas de “%s” desativada pelo administrador", alvo.usuario)
            flash(f"Verificação em duas etapas de “{alvo.usuario}” desativada. O usuário pode ativar de novo em Minha conta.",
                  "ok")
        elif acao == "ativo":
            alvo, ativado = contas.alternar_ativo(usuario_id)
            flash(f"“{alvo.usuario}” {'reativado' if ativado else 'desativado'}.", "ok")
        else:
            abort(400)
    except NaoEncontrado:
        abort(404)
    except ErroUsuario as erro:
        flash(str(erro), "erro")
    return redirect(url_for("auth.usuarios"))


def registrar(app):
    app.register_blueprint(bp)
    app.before_request(_carregar_usuario)
    app.before_request(_verificar_csrf)
    app.jinja_env.globals["csrf_token"] = token_csrf
    app.jinja_env.globals["pode"] = pode
    app.jinja_env.globals["pode_fechar_conta"] = pode_fechar_conta
    app.jinja_env.globals["PAPEIS"] = PAPEIS

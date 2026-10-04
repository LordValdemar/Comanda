"""Permissões por tipo de funcionário, escolhidas pelo administrador (porta de entrada web).

As regras (níveis "não", "sim" e "com autorização", quem pode autorizar, como vale a liberação)
ficam no núcleo (src/domain/permissoes, o mesmo da plataforma); aqui ficam as rotas, o decorador ``exigir`` e o que os
templates usam. Quem precisa de autorização lê o QR code (ou digita o código) que alguém que
pode mostra no celular: fica liberado, e o sistema guarda quem autorizou quem.
"""

import logging
from functools import wraps
from urllib.parse import urlsplit

import segno
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from src.domain.erros import NaoEncontrado
from src.domain.permissoes import (
    AUTORIZACAO,
    CODIGO_SEGUNDOS,
    FIXAS,
    FUNCOES,
    MAX_MINUTOS,
    MODOS,
    NAO,
    NIVEIS,
    PAPEIS_CONFIGURAVEIS,
    SIM,
    ErroDeAutorizacao,
    Pessoa,
    SemPermissao,
    ServicoDeAutorizacoes,
    TabelaDePermissoes,
    descrever,
    ler_minutos,
    modulos_da_pessoa,
    normalizar_codigo,
)
from src.infrastructure.sqlite import RepositorioDePermissoesSQLite

from . import db
from .auth import PAPEIS, login_obrigatorio, papel_exigido
from .formatos import agora_utc

__all__ = ["AUTORIZACAO", "FUNCOES", "NAO", "NIVEIS", "SIM", "exigir", "nivel", "pode", "permite", "verificar"]

MODULOS = frozenset({"comanda"})   # esta versão tem só a Comanda

log = logging.getLogger(__name__)
bp = Blueprint("permissoes", __name__)


def _repositorio():
    return RepositorioDePermissoesSQLite(db.obter())


def tabela():
    """A tabela de permissões (lida do banco uma vez por pedido)."""
    if "_permissoes" not in g:
        g._permissoes = TabelaDePermissoes(_repositorio().niveis_configurados())
    return g._permissoes


def servico():
    # O relógio é lido a cada uso (lambda): os testes podem trocá-lo.
    return ServicoDeAutorizacoes(_repositorio(), tabela(), MODULOS, relogio=lambda: agora_utc())


def pessoa(usuario=None):
    """A pessoa logada (ou `usuario`) para as regras de permissão."""
    usuario = usuario if usuario is not None else g.get("usuario")
    if usuario is None:
        return None
    return Pessoa(id=usuario["id"], papel=usuario["papel"], modulos=modulos_da_pessoa(usuario["papel"], False, MODULOS),
                  fecha_conta=bool(usuario["fecha_conta"]), nome=usuario["usuario"])


def nivel_do_papel(funcao, papel):
    """O que um papel pode nesta função (sem contar o administrador)."""
    return tabela().nivel_do_papel(funcao, papel)


def nivel(funcao, usuario=None):
    """O que a pessoa logada (ou `usuario`) pode nesta função."""
    quem = pessoa(usuario)
    return NAO if quem is None else tabela().nivel(funcao, quem)


def autorizado(funcao):
    """Liberação por QR code ainda valendo para esta função? Devolve quem autorizou."""
    liberacao = servico().liberacao_vigente(pessoa(), funcao)
    return None if liberacao is None else (liberacao.quem_autorizou or "—")


def _gasta_a_liberacao(funcao):
    """Quando a liberação de "uma vez" é usada: no primeiro envio que dá certo (no fechamento, ao finalizar)."""
    if request.method != "POST":
        return False
    return funcao != "fechar_conta" or request.form.get("acao") == "finalizar"


def _gastar_liberacoes(resposta):
    """after_request: marca como usada a liberação de "uma vez", se a ação deu certo."""
    ids = g.pop("liberacoes_a_gastar", None)
    if not ids or resposta.status_code >= 400:
        return resposta
    if any(categoria == "erro" for categoria, _ in session.get("_flashes", [])):
        return resposta  # a ação não aconteceu (ex.: ainda falta pagar): a liberação continua
    servico().gastar(ids)
    return resposta


def pode(funcao):
    """Pode fazer agora (tem a permissão ou foi autorizado há pouco)."""
    atual = nivel(funcao)
    return atual == SIM or (atual == AUTORIZACAO and autorizado(funcao) is not None)


def permite(funcao):
    """Para os menus e botões: pode, ou pode pedindo autorização."""
    return nivel(funcao) != NAO


def verificar(funcao):
    """None se pode seguir; senão, a resposta a devolver (403 ou a página que pede autorização)."""
    atual = nivel(funcao)
    if atual == SIM:
        return None
    if atual == AUTORIZACAO:
        liberacao = servico().liberacao_vigente(pessoa(), funcao)
        if liberacao is not None:
            g.autorizado_por = liberacao.quem_autorizou or "—"
            if liberacao.uma_vez and _gasta_a_liberacao(funcao):
                g.setdefault("liberacoes_a_gastar", set()).add(liberacao.id)
            return None
        return pedir_autorizacao(funcao)
    abort(403)


def exigir(funcao):
    """Decorador de rota: só segue quem pode a função (ou foi autorizado agora há pouco)."""
    def decorador(rota):
        @wraps(rota)
        @login_obrigatorio
        def interna(*args, **kwargs):
            resposta = verificar(funcao)
            if resposta is not None:
                return resposta
            return rota(*args, **kwargs)

        interna.funcao_exigida = funcao  # para a varredura de permissões dos testes
        return interna
    return decorador


def pedir_autorizacao(funcao):
    if "/api/" in request.path:
        return {"erro": f"Precisa de autorização: {FUNCOES[funcao].nome}."}, 403
    # Depois de autorizado, volta para onde estava (num POST, para a página que tinha o botão).
    voltar = request.full_path.rstrip("?") if request.method == "GET" else request.referrer
    if voltar and _caminho_seguro(voltar):
        session["autorizacao_voltar"] = voltar
    return render_template("autorizacao_pedir.html", funcao=funcao, definicao=FUNCOES[funcao],
                           quem=tabela().papeis_com(funcao, SIM)), 403


def _caminho_seguro(endereco):
    partes = urlsplit(endereco)
    if partes.netloc and partes.netloc != request.host:
        return False
    caminho = partes.path + (f"?{partes.query}" if partes.query else "")
    return caminho.startswith("/") and not caminho.startswith("//") and "\\" not in caminho


def pode_autorizar(funcao, usuario=None):
    """Pode mostrar o QR que libera os outros nesta função: tem "Sim" nela e a permissão "Autorizar os outros"."""
    return tabela().pode_autorizar(funcao, pessoa(usuario))


def funcoes_que_pode_autorizar():
    """Funções em que a pessoa tem "sim" e algum papel da loja precisa de autorização."""
    return tabela().funcoes_que_pode_autorizar(pessoa()) if g.get("usuario") is not None else []


def mostrar_autorizar():
    """O menu mostra "Autorizar" para quem pode autorizar algo que alguém da loja precisa."""
    return g.get("usuario") is not None and tabela().mostrar_autorizar(pessoa())


# ---------------------------------------------------------------------------
# Administrador: a tabela de permissões
# ---------------------------------------------------------------------------

@bp.route("/permissoes", methods=["GET", "POST"])
@papel_exigido("admin")
def configurar():
    modulos_da_loja = [m for m in PAPEIS_CONFIGURAVEIS if m in MODULOS]
    if request.method == "POST":
        _repositorio().gravar_niveis(TabelaDePermissoes.niveis_do_formulario(request.form, modulos_da_loja))
        g.pop("_permissoes", None)
        log.info("“%s” alterou as permissões da equipe", g.usuario["usuario"])
        flash("Permissões salvas. Já valem para quem está usando o sistema.", "ok")
        return redirect(url_for("permissoes.configurar"))

    atual = tabela()
    grupos = []
    for modulo in modulos_da_loja:
        linhas = [
            {"funcao": funcao, "definicao": definicao, "celulas": [
                {"papel": papel, "nivel": atual.nivel_do_papel(funcao, papel), "fixa": (funcao, papel) in FIXAS}
                for papel in PAPEIS_CONFIGURAVEIS[modulo]
            ]}
            for funcao, definicao in FUNCOES.items() if definicao.modulo == modulo
        ]
        grupos.append({"modulo": modulo, "papeis": PAPEIS_CONFIGURAVEIS[modulo], "linhas": linhas})
    return render_template("permissoes.html", grupos=grupos, NIVEIS=NIVEIS)


# ---------------------------------------------------------------------------
# Quem autoriza: mostra o QR code
# ---------------------------------------------------------------------------

@bp.route("/autorizar")
@login_obrigatorio
def autorizar():
    funcoes = funcoes_que_pode_autorizar()
    if not funcoes:
        abort(403)
    funcao = request.args.get("funcao")
    modo = request.args.get("modo")
    minutos = ler_minutos(request.args.get("minutos"))
    if funcao and funcao not in funcoes:
        abort(403)
    autorizacoes, eu = servico(), pessoa()
    codigo = qr = None
    if funcao and modo in MODOS:
        codigo = autorizacoes.gerar_codigo(eu, funcao, modo, minutos).codigo
        endereco = url_for("permissoes.usar", codigo=codigo, _external=True)
        qr = segno.make(endereco, error="m").svg_data_uri(scale=10, border=2)
    return render_template(
        "autorizar.html", funcoes=funcoes, funcao=funcao, codigo=codigo, qr=qr, FUNCOES=FUNCOES,
        validade=CODIGO_SEGUNDOS, recentes=autorizacoes.recentes(eu), ativas=autorizacoes.ativas(eu), modo=modo,
        minutos=minutos, MODOS=MODOS, max_minutos=MAX_MINUTOS, descrever=descrever,
    )


@bp.route("/autorizar/<int:liberacao_id>/encerrar", methods=["POST"])
@login_obrigatorio
def encerrar(liberacao_id):
    """Acaba com uma liberação antes da hora (a "sem prazo", principalmente)."""
    try:
        liberacao = servico().encerrar(liberacao_id, pessoa())
    except NaoEncontrado:
        abort(404)
    except SemPermissao:
        abort(403)
    log.info("“%s” encerrou a liberação de “%s” (%s)", g.usuario["usuario"], liberacao.quem_usou, liberacao.funcao)
    flash(f"Liberação de {liberacao.quem_usou or '—'} encerrada.", "ok")
    return redirect(url_for("permissoes.autorizar"))


@bp.route("/api/autorizar/<codigo>")
@login_obrigatorio
def situacao(codigo):
    """A página do QR pergunta se o código já foi lido (para trocar por outro)."""
    estado, por = servico().situacao_do_codigo(codigo, g.usuario["id"])
    return {"situacao": estado, "por": por} if estado == "usado" else {"situacao": estado}


# ---------------------------------------------------------------------------
# Quem pede: lê o QR code (ou digita o código)
# ---------------------------------------------------------------------------

@bp.route("/autorizacao/codigo", methods=["POST"])
@login_obrigatorio
def digitar():
    return redirect(url_for("permissoes.usar", codigo=normalizar_codigo(request.form.get("codigo")) or "-"))


@bp.route("/autorizacao/<codigo>")
@login_obrigatorio
def usar(codigo):
    voltar = session.pop("autorizacao_voltar", None) or url_for("auth.inicio")
    try:
        liberacao = servico().usar_codigo(codigo, pessoa())
    except ErroDeAutorizacao as erro:
        flash(str(erro), "erro")
        return redirect(voltar)
    nome = FUNCOES[liberacao.funcao].nome
    log.info("“%s” autorizou “%s” a: %s (%s)", liberacao.quem_autorizou, g.usuario["usuario"], nome, liberacao.descricao)
    flash(f"Autorizado por {liberacao.quem_autorizou}: {nome.lower()} liberado {liberacao.descricao}.", "ok")
    return redirect(voltar)


def registrar(app):
    app.register_blueprint(bp)
    app.after_request(_gastar_liberacoes)
    app.jinja_env.globals["permite"] = permite
    app.jinja_env.globals["pode_funcao"] = pode
    app.jinja_env.globals["mostrar_autorizar"] = mostrar_autorizar
    app.jinja_env.globals.setdefault("PAPEIS", PAPEIS)

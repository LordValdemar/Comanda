"""Permissões por tipo de funcionário, escolhidas pelo administrador da loja.

Cada função (fechar conta, dar desconto, cancelar...) tem, para cada papel, um nível:
"não", "sim" ou "com autorização". No último, a pessoa só faz depois que alguém que pode
(o caixa, por exemplo) mostra um QR code de autorização no celular dele e ela lê com o dela:
fica liberada por alguns minutos, e o sistema guarda quem autorizou quem.

O administrador da loja sempre pode tudo. Sem nada configurado, valem os padrões abaixo,
que são o comportamento de antes desta tela existir.
"""

import logging
import secrets
import time
from datetime import timedelta
from functools import wraps

import segno
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from . import db
from .auth import PAPEIS, login_obrigatorio, papel_exigido
from .formatos import agora_utc, de_texto_utc, para_texto_utc

log = logging.getLogger(__name__)
bp = Blueprint("permissoes", __name__)

NAO, SIM, AUTORIZACAO = 0, 1, 2
NIVEIS = {NAO: "Não", SIM: "Sim", AUTORIZACAO: "Com autorização"}

CODIGO_SEGUNDOS = 120        # o QR code de autorização vale 2 minutos e uma leitura só
LIBERADO_MINUTOS = 5         # depois de lido, a pessoa fica liberada por 5 minutos
LETRAS_DO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I/L: fácil de digitar

# Papéis que aparecem em cada módulo (o administrador não entra: ele sempre pode).
PAPEIS_CONFIGURAVEIS = {"comanda": ("caixa", "garcom", "cozinha")}

FUNCOES = {
    # Comanda
    "fechar_conta": {
        "modulo": "comanda", "nome": "Fechar conta",
        "descricao": "Receber pagamentos, tirar a taxa de serviço e finalizar a conta.",
        "padrao": {"caixa": SIM}, "autorizavel": True,
    },
    "desconto": {
        "modulo": "comanda", "nome": "Dar desconto",
        "descricao": "Desconto em reais no fechamento da conta.",
        "padrao": {"caixa": SIM}, "autorizavel": True,
    },
    "cancelar": {
        "modulo": "comanda", "nome": "Cancelar",
        "descricao": "Cancelar a comanda inteira e itens que a cozinha já começou "
                     "(antes disso, quem lançou sempre pode desfazer o engano).",
        "padrao": {"caixa": SIM}, "autorizavel": True,
    },
    "reabrir": {
        "modulo": "comanda", "nome": "Reabrir comanda fechada",
        "descricao": "Voltar uma conta já fechada para aberta (para corrigir).",
        "padrao": {}, "autorizavel": True,
    },
    "cozinha": {
        "modulo": "comanda", "nome": "Tela da cozinha",
        "descricao": "Ver os pedidos e marcar preparando e pronto.",
        "padrao": {"caixa": SIM, "cozinha": SIM}, "autorizavel": False,
    },
    "vendas": {
        "modulo": "comanda", "nome": "Vendas e comandas fechadas",
        "descricao": "Relatório de vendas, exportação e a lista de contas fechadas.",
        "padrao": {"caixa": SIM}, "autorizavel": False,
    },
    "cardapio": {
        "modulo": "comanda", "nome": "Cardápio",
        "descricao": "Cadastrar produtos, preços e categorias.",
        "padrao": {}, "autorizavel": True,
    },
}
# Combinações fixas (sem elas o papel não teria o que fazer).
FIXAS = {("cozinha", "cozinha"): SIM}


def _chave(funcao, papel):
    return f"permissao.{funcao}.{papel}"


def _configuradas():
    """Níveis gravados pela loja: {(funcao, papel): nivel}. Lidos uma vez por pedido."""
    if "_permissoes" not in g:
        linhas = db.obter().execute("SELECT chave, valor FROM configuracoes WHERE chave LIKE 'permissao.%'").fetchall()
        niveis = {}
        for linha in linhas:
            _, funcao, papel = linha["chave"].split(".", 2)
            if linha["valor"].isdigit():
                niveis[(funcao, papel)] = int(linha["valor"])
        g._permissoes = niveis
    return g._permissoes


def nivel_do_papel(funcao, papel):
    """O que um papel pode nesta função, nesta loja (sem contar o administrador)."""
    if (funcao, papel) in FIXAS:
        return FIXAS[(funcao, papel)]
    definicao = FUNCOES[funcao]
    if papel not in PAPEIS_CONFIGURAVEIS[definicao["modulo"]]:
        return NAO
    nivel = _configuradas().get((funcao, papel), definicao["padrao"].get(papel, NAO))
    if nivel == AUTORIZACAO and not definicao["autorizavel"]:
        return NAO
    return nivel if nivel in NIVEIS else NAO


def nivel(funcao, usuario=None):
    """O que a pessoa logada (ou `usuario`, da mesma loja) pode nesta função."""
    usuario = usuario if usuario is not None else g.get("usuario")
    if usuario is None:
        return NAO
    if usuario["papel"] == "admin":
        return SIM
    if funcao == "fechar_conta" and usuario["papel"] == "garcom" and usuario["fecha_conta"]:
        return SIM  # permissão dada à pessoa, na lista de usuários
    return nivel_do_papel(funcao, usuario["papel"])


def autorizado(funcao):
    """Liberação por QR code ainda valendo para esta função? Devolve quem autorizou."""
    liberacao = session.get("autorizacoes", {}).get(funcao)
    if not liberacao or g.get("usuario") is None or liberacao.get("usuario_id") != g.usuario["id"]:
        return None
    if liberacao.get("ate", 0) < time.time():
        return None
    return liberacao.get("por")


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
        por = autorizado(funcao)
        if por is not None:
            g.autorizado_por = por
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
        return {"erro": f"Precisa de autorização: {FUNCOES[funcao]['nome']}."}, 403
    # Depois de autorizado, volta para onde estava (num POST, para a página que tinha o botão).
    voltar = request.full_path.rstrip("?") if request.method == "GET" else request.referrer
    if voltar and _caminho_seguro(voltar):
        session["autorizacao_voltar"] = voltar
    quem = [papel for papel in PAPEIS_CONFIGURAVEIS[FUNCOES[funcao]["modulo"]]
            if nivel_do_papel(funcao, papel) == SIM]
    return render_template("autorizacao_pedir.html", funcao=funcao, definicao=FUNCOES[funcao], quem=quem), 403


def _caminho_seguro(endereco):
    from urllib.parse import urlsplit

    partes = urlsplit(endereco)
    if partes.netloc and partes.netloc != request.host:
        return False
    caminho = partes.path + (f"?{partes.query}" if partes.query else "")
    return caminho.startswith("/") and not caminho.startswith("//") and "\\" not in caminho


def funcoes_que_pode_autorizar():
    """Funções em que a pessoa tem "sim" e algum papel da loja precisa de autorização."""
    if g.get("usuario") is None:
        return []
    resultado = []
    for funcao, definicao in FUNCOES.items():
        if not definicao["autorizavel"] or nivel(funcao) != SIM:
            continue
        papeis = PAPEIS_CONFIGURAVEIS[definicao["modulo"]]
        if any(nivel_do_papel(funcao, papel) == AUTORIZACAO for papel in papeis) or g.usuario["papel"] == "admin":
            resultado.append(funcao)
    return resultado


def mostrar_autorizar():
    """O menu mostra "Autorizar" para quem pode autorizar algo que alguém da loja precisa."""
    if g.get("usuario") is None:
        return False
    for funcao in funcoes_que_pode_autorizar():
        papeis = PAPEIS_CONFIGURAVEIS[FUNCOES[funcao]["modulo"]]
        if any(nivel_do_papel(funcao, papel) == AUTORIZACAO for papel in papeis):
            return True
    return False


# ---------------------------------------------------------------------------
# Administrador: a tabela de permissões
# ---------------------------------------------------------------------------

@bp.route("/permissoes", methods=["GET", "POST"])
@papel_exigido("admin")
def configurar():
    modulos_da_loja = list(PAPEIS_CONFIGURAVEIS)
    if request.method == "POST":
        conexao = db.obter()
        with conexao:
            for funcao, definicao in FUNCOES.items():
                if definicao["modulo"] not in modulos_da_loja:
                    continue
                for papel in PAPEIS_CONFIGURAVEIS[definicao["modulo"]]:
                    if (funcao, papel) in FIXAS:
                        continue
                    valor = request.form.get(f"{funcao}.{papel}", "")
                    if not valor.isdigit() or int(valor) not in NIVEIS:
                        continue
                    if int(valor) == AUTORIZACAO and not definicao["autorizavel"]:
                        continue
                    conexao.execute(
                        "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
                        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                        (_chave(funcao, papel), valor),
                    )
        g.pop("_permissoes", None)
        log.info("“%s” alterou as permissões da equipe", g.usuario["usuario"])
        flash("Permissões salvas. Já valem para quem está usando o sistema.", "ok")
        return redirect(url_for("permissoes.configurar"))

    grupos = []
    for modulo in modulos_da_loja:
        linhas = []
        for funcao, definicao in FUNCOES.items():
            if definicao["modulo"] != modulo:
                continue
            celulas = []
            for papel in PAPEIS_CONFIGURAVEIS[modulo]:
                celulas.append({
                    "papel": papel, "nivel": nivel_do_papel(funcao, papel),
                    "fixa": (funcao, papel) in FIXAS,
                })
            linhas.append({"funcao": funcao, "definicao": definicao, "celulas": celulas})
        grupos.append({"modulo": modulo, "papeis": PAPEIS_CONFIGURAVEIS[modulo], "linhas": linhas})
    return render_template("permissoes.html", grupos=grupos, NIVEIS=NIVEIS)


# ---------------------------------------------------------------------------
# Quem autoriza: mostra o QR code
# ---------------------------------------------------------------------------

def _limpar_vencidos(conexao):
    limite = para_texto_utc(agora_utc() - timedelta(days=90))
    conexao.execute("DELETE FROM autorizacoes WHERE criado_em < ?", (limite,))


@bp.route("/autorizar")
@login_obrigatorio
def autorizar():
    funcoes = funcoes_que_pode_autorizar()
    if not funcoes:
        abort(403)
    funcao = request.args.get("funcao")
    conexao = db.obter()
    codigo = qr = None
    if funcao:
        if funcao not in funcoes:
            abort(403)
        codigo = "".join(secrets.choice(LETRAS_DO_CODIGO) for _ in range(8))
        with conexao:
            _limpar_vencidos(conexao)
            # Um código aberto por pessoa: o anterior, se não foi usado, deixa de valer.
            conexao.execute(
                "DELETE FROM autorizacoes WHERE autorizado_por = ? AND usado_em IS NULL", (g.usuario["id"],)
            )
            conexao.execute(
                "INSERT INTO autorizacoes (codigo, funcao, autorizado_por, criado_em) VALUES (?, ?, ?, ?)",
                (codigo, funcao, g.usuario["id"], para_texto_utc(agora_utc())),
            )
        endereco = url_for("permissoes.usar", codigo=codigo, _external=True)
        qr = segno.make(endereco, error="m").svg_data_uri(scale=10, border=2)
    recentes = conexao.execute(
        "SELECT a.*, u.usuario AS quem_usou, p.usuario AS quem_autorizou FROM autorizacoes a "
        "LEFT JOIN usuarios u ON u.id = a.usado_por LEFT JOIN usuarios p ON p.id = a.autorizado_por "
        "WHERE a.usado_em IS NOT NULL ORDER BY a.usado_em DESC LIMIT 15",
    ).fetchall()
    return render_template(
        "autorizar.html", funcoes=funcoes, funcao=funcao, codigo=codigo, qr=qr, FUNCOES=FUNCOES,
        validade=CODIGO_SEGUNDOS, recentes=recentes, minutos=LIBERADO_MINUTOS,
    )


@bp.route("/api/autorizar/<codigo>")
@login_obrigatorio
def situacao(codigo):
    """A página do QR pergunta se o código já foi lido (para trocar por outro)."""
    linha = db.obter().execute(
        "SELECT a.usado_em, u.usuario FROM autorizacoes a LEFT JOIN usuarios u ON u.id = a.usado_por "
        "WHERE a.codigo = ? AND a.autorizado_por = ?",
        (codigo, g.usuario["id"]),
    ).fetchone()
    if linha is None:
        return {"situacao": "trocado"}
    if linha["usado_em"]:
        return {"situacao": "usado", "por": linha["usuario"]}
    return {"situacao": "aguardando"}


# ---------------------------------------------------------------------------
# Quem pede: lê o QR code (ou digita o código)
# ---------------------------------------------------------------------------

@bp.route("/autorizacao/codigo", methods=["POST"])
@login_obrigatorio
def digitar():
    codigo = "".join(c for c in request.form.get("codigo", "").upper() if c in LETRAS_DO_CODIGO)[:8]
    return redirect(url_for("permissoes.usar", codigo=codigo or "-"))


@bp.route("/autorizacao/<codigo>")
@login_obrigatorio
def usar(codigo):
    conexao = db.obter()
    codigo = codigo.upper()
    linha = conexao.execute(
        "SELECT a.*, u.usuario AS autorizador FROM autorizacoes a JOIN usuarios u ON u.id = a.autorizado_por WHERE a.codigo = ?",
        (codigo,),
    ).fetchone()
    voltar = session.pop("autorizacao_voltar", None) or url_for("auth.inicio")
    if linha is None or linha["usado_em"] is not None:
        flash("Este código de autorização não vale (já foi usado ou foi trocado). Peça um novo.", "erro")
        return redirect(voltar)
    criado = de_texto_utc(linha["criado_em"])
    if (agora_utc() - criado).total_seconds() > CODIGO_SEGUNDOS:
        flash("Este código de autorização venceu. Peça um novo.", "erro")
        return redirect(voltar)
    funcao = linha["funcao"]
    if funcao not in FUNCOES:
        abort(404)
    if linha["autorizado_por"] == g.usuario["id"]:
        flash("Quem autoriza não pode usar o próprio código.", "erro")
        return redirect(voltar)
    if nivel(funcao) != AUTORIZACAO:
        flash("Você não precisa de autorização para isso." if nivel(funcao) == SIM
              else "Seu papel não pode fazer isso, nem com autorização.", "erro")
        return redirect(voltar)
    # Quem autorizou ainda pode a função? (pode ter mudado de papel depois de abrir o QR)
    autorizador = conexao.execute("SELECT * FROM usuarios WHERE id = ?", (linha["autorizado_por"],)).fetchone()
    if autorizador is None or not autorizador["ativo"] or nivel(funcao, autorizador) != SIM:
        flash("Quem mostrou o código não pode mais autorizar isso.", "erro")
        return redirect(voltar)
    agora = para_texto_utc(agora_utc())
    with conexao:
        usado = conexao.execute(
            "UPDATE autorizacoes SET usado_por = ?, usado_em = ? WHERE id = ? AND usado_em IS NULL",
            (g.usuario["id"], agora, linha["id"]),
        ).rowcount
    if not usado:  # alguém leu o mesmo QR um instante antes
        flash("Este código de autorização já foi usado. Peça um novo.", "erro")
        return redirect(voltar)
    liberacoes = dict(session.get("autorizacoes", {}))
    liberacoes[funcao] = {"usuario_id": g.usuario["id"], "ate": time.time() + LIBERADO_MINUTOS * 60,
                          "por": linha["autorizador"]}
    session["autorizacoes"] = liberacoes
    log.info("“%s” autorizou “%s” a: %s", linha["autorizador"], g.usuario["usuario"], FUNCOES[funcao]["nome"])
    flash(f"Autorizado por {linha['autorizador']}: {FUNCOES[funcao]['nome'].lower()} liberado por "
          f"{LIBERADO_MINUTOS} minutos.", "ok")
    return redirect(voltar)


def registrar(app):
    app.register_blueprint(bp)
    app.jinja_env.globals["permite"] = permite
    app.jinja_env.globals["pode_funcao"] = pode
    app.jinja_env.globals["mostrar_autorizar"] = mostrar_autorizar
    app.jinja_env.globals.setdefault("PAPEIS", PAPEIS)

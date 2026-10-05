"""Comandas: abrir, lançar pedidos, fechar a conta (pagamentos) e imprimir o cupom.

As regras vêm do núcleo (src/domain/comanda); o que as telas mostram vem de ConsultasDaComanda.
"""

import logging
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from src.domain.comanda import (
    FORMAS_DE_PAGAMENTO,
    SITUACOES_DO_ITEM,
    Ator,
    ErroComanda,
    Pedido,
    ServicoDeComandas,
    taxa_percentual_valida,
)
from src.domain.dinheiro import ValorInvalido, entrada_reais, ler_reais, reais
from src.domain.erros import ErroDeDominio, NaoEncontrado
from src.infrastructure.sqlite import ConsultasDaComanda, RepositorioDeComandasSQLite

from . import db, permissoes
from .auth import papel_exigido
from .cardapio import agrupar, produtos_ativos
from .formatos import hoje_local, intervalo_utc

bp = Blueprint("comandas", __name__, url_prefix="/comandas")
log = logging.getLogger("comanda.comandas")

# Nomes usados pelas telas e pelos outros módulos (as regras ficam no núcleo, em src/domain/comanda).
FORMAS = FORMAS_DE_PAGAMENTO
STATUS_ITEM = SITUACOES_DO_ITEM
__all__ = ["ErroComanda", "FORMAS", "STATUS_ITEM", "ValorInvalido", "bp", "taxa_padrao", "totais"]


def servico_de_comandas():
    """Os casos de uso da Comanda (regras do núcleo em src/domain), gravando no banco local."""
    return ServicoDeComandas(RepositorioDeComandasSQLite(db.obter()))


def ator_atual():
    """Quem faz a operação (para o histórico). Chame depois de conferir a permissão: aí já se sabe se foi autorizado."""
    return Ator(usuario_id=g.usuario["id"] if g.get("usuario") is not None else None, autorizado_por=g.get("autorizado_por"))


def taxa_padrao():
    """Taxa de serviço (Ajustes); fora da faixa permitida, vale 10%."""
    try:
        return taxa_percentual_valida(db.ler_config("taxa_servico", "10"))
    except ErroComanda:
        return 10.0


def totais(comanda_id):
    """Subtotal, taxa, desconto, total, pago, troco e o que falta (centavos), calculados pelo núcleo."""
    return servico_de_comandas().comanda(comanda_id).totais


def consultas():
    return ConsultasDaComanda(db.obter())


def buscar(comanda_id):
    """A comanda (como a tela mostra); 404 se não existe."""
    comanda = consultas().comanda(comanda_id)
    if comanda is None:
        abort(404)
    return comanda


def _voltar(comanda_id):
    return redirect(url_for("comandas.detalhe", comanda_id=comanda_id))


# ---------------------------------------------------------------------------
# Rotas: garçom e caixa
# ---------------------------------------------------------------------------

@bp.route("/")
@papel_exigido("caixa", "garcom")
def lista():
    leitura = consultas()
    numero = request.args.get("numero", "").strip()
    if numero:
        # Busca pelo número do cartão: abre a comanda, ou oferece abrir uma nova.
        achada = leitura.aberta_com_numero(numero) if numero.isdigit() else None
        if achada:
            return _voltar(achada)
    return render_template("comandas.html", abertas=leitura.abertas(), prontos=leitura.prontos_para_entregar(),
                           numero_buscado=numero, garcons=leitura.garcons())


def _garcom_escolhido(padrao=None):
    """Garçom que atende: quem é garçom atende as comandas que abre; os outros escolhem na lista."""
    if g.usuario["papel"] == "garcom" and "garcom_id" not in request.form:
        return g.usuario["id"]
    escolhido = request.form.get("garcom_id", "")
    if not escolhido:
        return None if "garcom_id" in request.form else padrao
    if not escolhido.isdigit() or not any(str(p["id"]) == escolhido for p in consultas().garcons()):
        raise ErroComanda("Escolha um garçom da lista.")
    return int(escolhido)


@bp.route("/", methods=["POST"])
@papel_exigido("caixa", "garcom")
def nova():
    numero = request.form.get("numero", "")
    try:
        comanda_id = servico_de_comandas().abrir(numero, request.form.get("mesa", ""), request.form.get("cliente", ""),
                                                 taxa_padrao(), ator_atual(), _garcom_escolhido())
    except ErroComanda as erro:
        aberta = consultas().aberta_com_numero(numero.strip())
        flash(str(erro), "erro")
        return _voltar(aberta) if aberta else redirect(url_for("comandas.lista"))
    return _voltar(comanda_id)


@bp.route("/<int:comanda_id>")
@papel_exigido("caixa", "garcom")
def detalhe(comanda_id):
    leitura = consultas()
    comanda = buscar(comanda_id)
    return render_template(
        "comanda.html",
        comanda=comanda,
        itens=leitura.itens(comanda_id),
        grupos=agrupar(produtos_ativos(db.obter())),
        contas=totais(comanda_id),
        status_item=STATUS_ITEM,
        garcons=leitura.garcons(),
    )


@bp.route("/<int:comanda_id>/dados", methods=["POST"])
@papel_exigido("caixa", "garcom")
def alterar_dados(comanda_id):
    comanda = buscar(comanda_id)
    try:
        garcons = consultas().garcons()
        servico_de_comandas().alterar_dados(
            comanda_id, request.form.get("mesa", ""), request.form.get("cliente", ""),
            _garcom_escolhido(comanda["garcom_id"]), {p["id"]: p["usuario"] for p in garcons}, ator_atual(),
        )
    except ErroComanda as erro:
        flash(str(erro), "erro")
    else:
        flash("Dados da comanda atualizados.", "ok")
    return _voltar(comanda_id)


def _pedidos_do_formulario(form):
    """Lê o formulário de lançamento: qtd_<id>/obs_<id> do cardápio e o lançamento rápido por código."""
    pedidos = []
    for chave, valor in form.items():
        encontrado = re.fullmatch(r"qtd_(\d+)", chave)
        if encontrado and valor.strip() not in ("", "0"):
            try:
                quantidade = int(valor)
            except ValueError:
                raise ErroComanda(f"Quantidade inválida: “{valor}”.") from None
            produto_id = int(encontrado.group(1))
            pedidos.append(Pedido(produto_id, quantidade, form.get(f"obs_{produto_id}", "")))
    codigo = form.get("codigo", "").strip()
    if codigo:
        produto_id = consultas().produto_pelo_codigo(codigo)
        if produto_id is None:
            raise ErroComanda(f"Nenhum produto com o código “{codigo}”.")
        try:
            quantidade = int(form.get("codigo_qtd") or 1)
        except ValueError:
            raise ErroComanda("Quantidade inválida.") from None
        pedidos.append(Pedido(produto_id, quantidade, form.get("codigo_obs", "")))
    return pedidos


@bp.route("/<int:comanda_id>/itens", methods=["POST"])
@papel_exigido("caixa", "garcom")
def lancar_itens(comanda_id):
    comanda = buscar(comanda_id)
    try:
        pedidos = _pedidos_do_formulario(request.form)
        # Comanda aberta pelo caixa sem garçom: o garçom que lança o primeiro pedido passa a atender.
        atendente = g.usuario["id"] if g.usuario["papel"] == "garcom" else None
        lancados = servico_de_comandas().lancar(comanda_id, pedidos, ator_atual(), atendente)
    except ErroComanda as erro:
        flash(str(erro), "erro")
    else:
        flash(f"{lancados} item(ns) lançado(s) na comanda {comanda['numero']}.", "ok")
    return _voltar(comanda_id)


@bp.route("/<int:comanda_id>/itens/<int:item_id>", methods=["POST"])
@papel_exigido("caixa", "garcom")
def alterar_item(comanda_id, item_id):
    servico = servico_de_comandas()
    try:
        comanda = servico.comanda(comanda_id)
        item = servico.item(comanda_id, item_id)
    except NaoEncontrado:
        abort(404)
    acao = request.form.get("acao")
    try:
        if acao == "entregue":
            servico.entregar(comanda_id, item_id)
            if request.form.get("voltar") == "lista":
                flash(f"{item.quantidade}× {item.nome} entregue na comanda {comanda.numero}. "
                      "Foi engano? Abra a comanda e toque em “↩ Não entregue”.", "ok")
        elif acao == "pronto":
            servico.desfazer_entrega(comanda_id, item_id)
        elif acao == "cancelar":
            # Antes de a cozinha começar, quem lançou desfaz o engano; depois, é a permissão "Cancelar".
            if item.cozinha_comecou:
                if not permissoes.permite("cancelar"):
                    raise ErroComanda("A cozinha já começou este item. Peça a quem pode cancelar.")
                resposta = permissoes.verificar("cancelar")
                if resposta is not None:
                    return resposta
            servico.cancelar_item(comanda_id, item_id, request.form.get("motivo", ""), ator_atual())
            flash(f"Item “{item.nome}” cancelado.", "ok")
        else:
            abort(400)
    except ErroComanda as erro:
        flash(str(erro), "erro")
    if request.form.get("voltar") == "lista":
        return redirect(url_for("comandas.lista"))
    return _voltar(comanda_id)


# ---------------------------------------------------------------------------
# Rotas: caixa (fechamento, cancelamento, histórico)
# ---------------------------------------------------------------------------

@bp.route("/<int:comanda_id>/fechar", methods=["GET", "POST"])
@permissoes.exigir("fechar_conta")
def fechamento(comanda_id):
    comanda = buscar(comanda_id)
    servico = servico_de_comandas()
    if request.method == "POST":
        acao = request.form.get("acao")
        try:
            if acao == "ajustar":
                resposta = _ajustar_conta(comanda)
                if resposta is not None:
                    return resposta
            elif acao == "pagar":
                pagamento = servico.registrar_pagamento(comanda_id, request.form.get("forma", ""),
                                                        ler_reais(request.form.get("valor")), ator_atual())
                if pagamento.troco:
                    flash(f"Troco: {reais(pagamento.troco)}", "ok")
            elif acao == "remover_pagamento":
                pagamento_id = request.form.get("pagamento_id", "")
                if pagamento_id.isdigit():
                    servico.remover_pagamento(comanda_id, int(pagamento_id), ator_atual())
                else:
                    servico.comanda(comanda_id).garantir_aberta()
            elif acao == "finalizar":
                totais_fechados = servico.fechar(comanda_id, ator_atual())
                log.info("Comanda %s fechada: %s", comanda["numero"], reais(totais_fechados.total))
                flash(f"Comanda {comanda['numero']} fechada. O cartão já pode ser usado de novo.", "ok")
                return redirect(url_for("comandas.cupom", comanda_id=comanda_id, imprimir=1))
            else:
                abort(400)
        except ErroDeDominio as erro:
            flash(str(erro), "erro")
        return redirect(url_for("comandas.fechamento", comanda_id=comanda_id))

    leitura = consultas()
    return render_template(
        "fechar.html", comanda=comanda, contas=totais(comanda_id), pagamentos=leitura.pagamentos(comanda_id),
        formas=FORMAS, itens=leitura.itens(comanda_id), na_cozinha=leitura.itens_na_cozinha(comanda_id),
        entrada_reais=entrada_reais,
    )


def _ajustar_conta(comanda):
    """Taxa de serviço e desconto. Quem fecha a conta tira ou devolve a taxa; desconto é outra permissão."""
    desconto = None  # mantém o atual
    if "desconto" in request.form:
        novo = ler_reais(request.form.get("desconto"))
        if novo != comanda["desconto_centavos"]:
            if not permissoes.permite("desconto"):
                abort(403)
            resposta = permissoes.verificar("desconto")
            if resposta is not None:
                return resposta
            desconto = novo
    servico_de_comandas().ajustar(comanda["id"], bool(request.form.get("cobrar_taxa")), desconto, ator_atual())
    return None


@bp.route("/<int:comanda_id>/cancelar", methods=["POST"])
@permissoes.exigir("cancelar")
def cancelar(comanda_id):
    comanda = buscar(comanda_id)
    try:
        servico_de_comandas().cancelar(comanda_id, request.form.get("motivo", ""), ator_atual())
    except ErroComanda as erro:
        flash(str(erro), "erro")
        return _voltar(comanda_id)
    flash(f"Comanda {comanda['numero']} cancelada.", "ok")
    return redirect(url_for("comandas.lista"))


@bp.route("/<int:comanda_id>/reabrir", methods=["POST"])
@permissoes.exigir("reabrir")
def reabrir(comanda_id):
    comanda = buscar(comanda_id)
    try:
        servico_de_comandas().reabrir(comanda_id, ator_atual())
    except ErroComanda as erro:
        flash(str(erro), "erro")
        return redirect(url_for("comandas.cupom", comanda_id=comanda_id))
    flash(f"Comanda {comanda['numero']} reaberta.", "ok")
    return redirect(url_for("comandas.fechamento", comanda_id=comanda_id))


@bp.route("/<int:comanda_id>/cupom")
@papel_exigido("caixa", "garcom")
def cupom(comanda_id):
    """Conferência (comanda aberta) ou recibo (fechada), no tamanho da impressora térmica de 80 mm."""
    leitura = consultas()
    comanda = buscar(comanda_id)
    itens = leitura.itens_do_cupom(comanda_id)
    pagamentos = leitura.pagamentos(comanda_id)
    auditoria = leitura.auditoria(comanda_id) if permissoes.pode("cancelar") or permissoes.pode("vendas") else []
    from .ajustes import dados_da_loja  # evita importação circular

    formas_usadas = list(dict.fromkeys(FORMAS.get(p["forma"], p["forma"]) for p in pagamentos))
    return render_template(
        "cupom.html", comanda=comanda, itens=itens, pagamentos=pagamentos, formas=FORMAS,
        contas=totais(comanda_id), auditoria=auditoria, loja=dados_da_loja(), formas_usadas=formas_usadas,
    )


@bp.route("/historico")
@permissoes.exigir("vendas")
def historico():
    from .relatorios import ler_periodo  # evita importação circular

    inicio, fim = ler_periodo(request.args, padrao=hoje_local())
    de, ate = intervalo_utc(inicio, fim)
    comandas = consultas().encerradas(de, ate)
    return render_template("historico.html", comandas=comandas, inicio=inicio, fim=fim)

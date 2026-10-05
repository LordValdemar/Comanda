"""Tela da cozinha: pedidos por ordem de chegada, atualizada sozinha a cada poucos segundos.

As regras da tela vêm do núcleo (src/domain/comanda/cozinha.py); as consultas de ConsultasDaComanda.
"""

from datetime import timedelta

from flask import Blueprint, abort, render_template, request

from src.domain.comanda.cozinha import (
    RECENTES_MAXIMO,
    RECENTES_MINUTOS,
    SITUACOES_DA_COZINHA,
    agrupar_por_comanda,
    entregues,
)
from src.domain.erros import NaoEncontrado
from src.infrastructure.sqlite import ConsultasDaComanda

from . import db, permissoes
from .comandas import ErroComanda, servico_de_comandas
from .formatos import agora_utc, hora, minutos_desde, para_texto_utc

bp = Blueprint("cozinha", __name__)

SITUACOES = SITUACOES_DA_COZINHA


def pedidos_da_cozinha():
    """Itens que passam pela cozinha e ainda não foram entregues, agrupados por comanda."""
    return agrupar_por_comanda(ConsultasDaComanda(db.obter()).na_cozinha(), hora, minutos_desde)


def entregues_recentes():
    """Itens da cozinha entregues há pouco: se foi engano, a cozinha traz de volta."""
    desde = para_texto_utc(agora_utc() - timedelta(minutes=RECENTES_MINUTOS))
    return entregues(ConsultasDaComanda(db.obter()).entregues_desde(desde, RECENTES_MAXIMO), hora)


@bp.route("/cozinha")
@permissoes.exigir("cozinha")
def tela():
    return render_template("cozinha.html")


@bp.route("/api/cozinha")
@permissoes.exigir("cozinha")
def api_pedidos():
    return {"comandas": pedidos_da_cozinha(), "recentes": entregues_recentes()}


@bp.route("/api/cozinha/itens/<int:item_id>", methods=["POST"])
@permissoes.exigir("cozinha")
def api_mudar(item_id):
    novo = request.form.get("status", "")
    if novo not in SITUACOES:
        return {"erro": "situação inválida"}, 400
    try:
        servico_de_comandas().mudar_situacao(item_id, novo)
    except NaoEncontrado:
        abort(404)
    except ErroComanda as erro:
        return {"erro": str(erro)}, 409
    return {"status": novo}


@bp.route("/api/cozinha/comandas/<int:comanda_id>/pronto", methods=["POST"])
@permissoes.exigir("cozinha")
def api_tudo_pronto(comanda_id):
    """Marca como prontos todos os itens da comanda que ainda estão na cozinha."""
    return {"alterados": servico_de_comandas().marcar_tudo_pronto(comanda_id)}

"""Tela da cozinha: pedidos por ordem de chegada, atualizada sozinha a cada poucos segundos."""

from datetime import timedelta

from flask import Blueprint, abort, render_template, request

from . import db
from .auth import papel_exigido
from .comandas import ErroComanda, mudar_status_item
from .formatos import agora_utc, hora, minutos_desde, para_texto_utc

bp = Blueprint("cozinha", __name__)

# A cozinha escolhe a situação direto (inclusive voltar uma etapa, se tocou errado).
SITUACOES = ("pendente", "preparando", "pronto", "entregue")
RECENTES_MINUTOS = 30  # itens entregues que ainda aparecem embaixo, para desfazer
RECENTES_MAXIMO = 15


def pedidos_da_cozinha(conexao):
    """Itens que passam pela cozinha e ainda não foram entregues, agrupados por comanda."""
    linhas = conexao.execute(
        "SELECT i.id, i.nome, i.quantidade, i.observacao, i.status, i.lancado_em, i.atualizado_em, "
        "c.id AS comanda_id, c.numero, c.mesa, u.usuario AS garcom "
        "FROM itens i JOIN comandas c ON c.id = i.comanda_id LEFT JOIN usuarios u ON u.id = i.lancado_por "
        "WHERE i.vai_cozinha = 1 AND i.status IN ('pendente', 'preparando', 'pronto') AND c.status != 'cancelada' "
        "ORDER BY i.lancado_em, i.id"
    ).fetchall()
    grupos = {}
    for linha in linhas:
        grupo = grupos.setdefault(linha["comanda_id"], {
            "comanda_id": linha["comanda_id"], "numero": linha["numero"], "mesa": linha["mesa"] or "",
            "desde": linha["lancado_em"], "itens": [],
        })
        grupo["itens"].append({
            "id": linha["id"],
            "nome": linha["nome"],
            "quantidade": linha["quantidade"],
            "observacao": linha["observacao"] or "",
            "status": linha["status"],
            "hora": hora(linha["lancado_em"]),
            "minutos": minutos_desde(linha["lancado_em"]),
            "garcom": linha["garcom"] or "",
        })
    resultado = list(grupos.values())
    for grupo in resultado:
        grupo["minutos"] = minutos_desde(grupo["desde"])
        grupo["tudo_pronto"] = all(item["status"] == "pronto" for item in grupo["itens"])
        del grupo["desde"]
    # Comandas com tudo pronto vão para o fim: o que falta fazer fica no alto da tela.
    resultado.sort(key=lambda grupo: grupo["tudo_pronto"])
    return resultado


def entregues_recentes(conexao):
    """Itens da cozinha entregues há pouco: se foi engano, a cozinha traz de volta."""
    limite = para_texto_utc(agora_utc() - timedelta(minutes=RECENTES_MINUTOS))
    linhas = conexao.execute(
        "SELECT i.id, i.nome, i.quantidade, i.atualizado_em, c.numero, c.mesa FROM itens i "
        "JOIN comandas c ON c.id = i.comanda_id "
        "WHERE i.vai_cozinha = 1 AND i.status = 'entregue' AND i.atualizado_em >= ? AND c.status != 'cancelada' "
        "ORDER BY i.atualizado_em DESC, i.id DESC LIMIT ?",
        (limite, RECENTES_MAXIMO),
    ).fetchall()
    return [
        {"id": linha["id"], "nome": linha["nome"], "quantidade": linha["quantidade"], "numero": linha["numero"],
         "mesa": linha["mesa"] or "", "hora": hora(linha["atualizado_em"])}
        for linha in linhas
    ]


@bp.route("/cozinha")
@papel_exigido("cozinha", "caixa")
def tela():
    return render_template("cozinha.html")


@bp.route("/api/cozinha")
@papel_exigido("cozinha", "caixa")
def api_pedidos():
    conexao = db.obter()
    return {"comandas": pedidos_da_cozinha(conexao), "recentes": entregues_recentes(conexao)}


@bp.route("/api/cozinha/itens/<int:item_id>", methods=["POST"])
@papel_exigido("cozinha", "caixa")
def api_mudar(item_id):
    conexao = db.obter()
    item = conexao.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    novo = request.form.get("status", "")
    if novo not in SITUACOES:
        return {"erro": "situação inválida"}, 400
    try:
        mudar_status_item(conexao, item, novo)
    except ErroComanda as erro:
        return {"erro": str(erro)}, 409
    return {"status": novo}


@bp.route("/api/cozinha/comandas/<int:comanda_id>/pronto", methods=["POST"])
@papel_exigido("cozinha", "caixa")
def api_tudo_pronto(comanda_id):
    """Marca como prontos todos os itens da comanda que ainda estão na cozinha."""
    conexao = db.obter()
    with conexao:
        alterados = conexao.execute(
            "UPDATE itens SET status = 'pronto', atualizado_em = ? "
            "WHERE comanda_id = ? AND vai_cozinha = 1 AND status IN ('pendente', 'preparando')",
            (para_texto_utc(agora_utc()), comanda_id),
        ).rowcount
    return {"alterados": alterados}

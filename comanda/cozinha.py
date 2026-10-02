"""Tela da cozinha: pedidos por ordem de chegada, atualizada sozinha a cada poucos segundos."""

from flask import Blueprint, abort, render_template, request

from . import db
from .auth import papel_exigido
from .comandas import ErroComanda, mudar_status_item
from .formatos import hora, minutos_desde

bp = Blueprint("cozinha", __name__)

# Botão principal de cada etapa (a cozinha só avança; "voltar" desfaz um toque errado).
PROXIMO = {"pendente": "preparando", "preparando": "pronto", "pronto": "entregue"}
ANTERIOR = {"preparando": "pendente", "pronto": "preparando"}


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


@bp.route("/cozinha")
@papel_exigido("cozinha", "caixa")
def tela():
    return render_template("cozinha.html")


@bp.route("/api/cozinha")
@papel_exigido("cozinha", "caixa")
def api_pedidos():
    return {"comandas": pedidos_da_cozinha(db.obter())}


@bp.route("/api/cozinha/itens/<int:item_id>", methods=["POST"])
@papel_exigido("cozinha", "caixa")
def api_avancar(item_id):
    conexao = db.obter()
    item = conexao.execute("SELECT * FROM itens WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    direcao = request.form.get("direcao", "avancar")
    novo = (PROXIMO if direcao == "avancar" else ANTERIOR).get(item["status"])
    if novo is None:
        return {"erro": "este item não pode mudar mais"}, 409
    try:
        mudar_status_item(conexao, item, novo)
    except ErroComanda as erro:
        return {"erro": str(erro)}, 409
    return {"status": novo}

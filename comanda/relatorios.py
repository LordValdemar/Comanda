"""Relatório de vendas por período (e exportação em CSV)."""

import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, render_template, request

from . import db
from .auth import papel_exigido
from .comandas import FORMAS
from .formatos import data_hora, entrada_reais, hoje_local, intervalo_utc

bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")
MAX_DIAS = 366


def ler_periodo(argumentos, padrao):
    """Lê ?de=AAAA-MM-DD&ate=AAAA-MM-DD; datas inválidas voltam ao padrão."""
    def ler(nome):
        try:
            return date.fromisoformat(argumentos.get(nome, ""))
        except ValueError:
            return padrao
    inicio, fim = ler("de"), ler("ate")
    if fim < inicio:
        inicio, fim = fim, inicio
    if (fim - inicio).days >= MAX_DIAS:
        inicio = fim - timedelta(days=MAX_DIAS - 1)
    return inicio, fim


def resumo(conexao, inicio, fim):
    de, ate = intervalo_utc(inicio, fim)
    filtro = "c.status = 'fechada' AND c.fechada_em >= ? AND c.fechada_em < ?"
    geral = conexao.execute(
        f"SELECT COUNT(*) AS comandas, COALESCE(SUM(c.total_centavos), 0) AS faturamento, "
        f"COALESCE(SUM(c.desconto_centavos), 0) AS descontos FROM comandas c WHERE {filtro}",
        (de, ate),
    ).fetchone()
    # Taxa de serviço recalculada a partir dos itens (é o que vai para a equipe).
    taxa = conexao.execute(
        f"SELECT COALESCE(SUM(ROUND(sub * c.taxa_percentual / 100)), 0) FROM comandas c "
        f"JOIN (SELECT comanda_id, SUM(preco_centavos * quantidade) AS sub FROM itens WHERE status != 'cancelado' "
        f"GROUP BY comanda_id) s ON s.comanda_id = c.id WHERE {filtro} AND c.cobrar_taxa = 1",
        (de, ate),
    ).fetchone()[0]
    formas = conexao.execute(
        f"SELECT p.forma, COUNT(*) AS quantidade, SUM(p.valor_centavos) AS valor FROM pagamentos p "
        f"JOIN comandas c ON c.id = p.comanda_id WHERE {filtro} GROUP BY p.forma ORDER BY valor DESC",
        (de, ate),
    ).fetchall()
    produtos = conexao.execute(
        f"SELECT i.nome, SUM(i.quantidade) AS quantidade, SUM(i.quantidade * i.preco_centavos) AS valor FROM itens i "
        f"JOIN comandas c ON c.id = i.comanda_id WHERE {filtro} AND i.status != 'cancelado' "
        f"GROUP BY i.nome ORDER BY quantidade DESC, valor DESC",
        (de, ate),
    ).fetchall()
    cancelados = conexao.execute(
        "SELECT i.*, c.numero, u.usuario AS cancelado_por_nome FROM itens i JOIN comandas c ON c.id = i.comanda_id "
        "LEFT JOIN usuarios u ON u.id = i.cancelado_por "
        "WHERE i.status = 'cancelado' AND i.atualizado_em >= ? AND i.atualizado_em < ? ORDER BY i.atualizado_em",
        (de, ate),
    ).fetchall()
    garcons = conexao.execute(
        f"SELECT COALESCE(u.usuario, '—') AS garcom, SUM(i.quantidade * i.preco_centavos) AS valor FROM itens i "
        f"JOIN comandas c ON c.id = i.comanda_id LEFT JOIN usuarios u ON u.id = i.lancado_por "
        f"WHERE {filtro} AND i.status != 'cancelado' GROUP BY u.usuario ORDER BY valor DESC",
        (de, ate),
    ).fetchall()
    abertas = conexao.execute("SELECT COUNT(*) FROM comandas WHERE status = 'aberta'").fetchone()[0]
    return {
        "comandas": geral["comandas"],
        "faturamento": geral["faturamento"],
        "descontos": geral["descontos"],
        "taxa": int(taxa),
        "ticket_medio": geral["faturamento"] // geral["comandas"] if geral["comandas"] else 0,
        "formas": formas,
        "produtos": produtos,
        "cancelados": cancelados,
        "garcons": garcons,
        "abertas": abertas,
    }


@bp.route("/")
@papel_exigido("caixa")
def vendas():
    inicio, fim = ler_periodo(request.args, padrao=hoje_local())
    return render_template("relatorios.html", inicio=inicio, fim=fim, dados=resumo(db.obter(), inicio, fim), formas=FORMAS)


@bp.route("/comandas.csv")
@papel_exigido("caixa")
def exportar():
    inicio, fim = ler_periodo(request.args, padrao=hoje_local())
    de, ate = intervalo_utc(inicio, fim)
    conexao = db.obter()
    comandas = conexao.execute(
        "SELECT c.*, GROUP_CONCAT(p.forma || ':' || p.valor_centavos, ' ') AS pagamentos FROM comandas c "
        "LEFT JOIN pagamentos p ON p.comanda_id = c.id "
        "WHERE c.status != 'aberta' AND c.fechada_em >= ? AND c.fechada_em < ? GROUP BY c.id ORDER BY c.fechada_em",
        (de, ate),
    ).fetchall()
    saida = io.StringIO()
    # Ponto e vírgula e vírgula decimal: abre direto no Excel em português.
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(["comanda", "mesa", "cliente", "situação", "aberta em", "fechada em", "desconto", "total", "pagamentos"])
    for c in comandas:
        pagamentos = " ".join(
            f"{FORMAS.get(forma, forma)} {entrada_reais(int(valor))}"
            for forma, _, valor in (p.partition(":") for p in (c["pagamentos"] or "").split())
        )
        escritor.writerow([
            c["numero"], c["mesa"] or "", c["cliente"] or "", c["status"], data_hora(c["aberta_em"]),
            data_hora(c["fechada_em"]), entrada_reais(c["desconto_centavos"]), entrada_reais(c["total_centavos"] or 0),
            pagamentos if c["status"] == "fechada" else (c["motivo_cancelamento"] or ""),
        ])
    nome = f"comandas-{inicio:%Y%m%d}-{fim:%Y%m%d}.csv"
    return Response(
        "﻿" + saida.getvalue(),  # BOM: o Excel reconhece os acentos
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )

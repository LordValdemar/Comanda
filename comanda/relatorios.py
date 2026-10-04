"""Relatório de vendas por período (e exportação em CSV). As regras ficam no núcleo (src/domain/relatorios)."""

import csv
import io

from flask import Blueprint, Response, render_template, request

from src.domain.periodo import Periodo
from src.domain.relatorios import RelatorioDeVendas
from src.domain.relatorios.vendas import MAX_DIAS
from src.infrastructure.sqlite import RepositorioDeVendasSQLite

from . import db, permissoes
from .comandas import FORMAS
from .formatos import data_hora, hoje_local, intervalo_utc

bp = Blueprint("relatorios", __name__, url_prefix="/relatorios")


def ler_periodo(argumentos, padrao):
    """?de=AAAA-MM-DD&ate=AAAA-MM-DD (datas inválidas voltam ao padrão; no máximo um ano)."""
    periodo = Periodo.ler(argumentos.get("de"), argumentos.get("ate"), padrao, padrao, MAX_DIAS)
    return periodo.inicio, periodo.fim


def relatorio():
    return RelatorioDeVendas(RepositorioDeVendasSQLite(db.obter()))


def csv_para_baixar(linhas, nome):
    """Ponto e vírgula e BOM: abre direto no Excel em português, com os acentos."""
    saida = io.StringIO()
    csv.writer(saida, delimiter=";").writerows(linhas)
    return Response("﻿" + saida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@bp.route("/")
@permissoes.exigir("vendas")
def vendas():
    inicio, fim = ler_periodo(request.args, padrao=hoje_local())
    return render_template("relatorios.html", inicio=inicio, fim=fim,
                           dados=relatorio().resumo(*intervalo_utc(inicio, fim)), formas=FORMAS)


@bp.route("/comandas.csv")
@permissoes.exigir("vendas")
def exportar():
    inicio, fim = ler_periodo(request.args, padrao=hoje_local())
    linhas = relatorio().planilha(*intervalo_utc(inicio, fim), data_hora=data_hora)
    return csv_para_baixar(linhas, f"comandas-{inicio:%Y%m%d}-{fim:%Y%m%d}.csv")

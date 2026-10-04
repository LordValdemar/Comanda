"""Relatório de vendas no SQLite da Comanda local (regras do núcleo): comanda antiga sem taxa gravada e planilha."""

import pytest

from comanda import db
from src.domain.comanda import Ator, Pedido, ServicoDeComandas
from src.domain.relatorios import RelatorioDeVendas
from src.infrastructure.sqlite import RepositorioDeComandasSQLite, RepositorioDeVendasSQLite

DIA = ("2000-01-01 00:00:00", "2100-01-01 00:00:00")
CAIXA = Ator(None)


@pytest.fixture
def conexao(app):
    conexao = db.conectar(app.config["BANCO"])
    with conexao:
        conexao.execute("INSERT INTO produtos (id, nome, preco_centavos, vai_cozinha) VALUES (1, 'Lanche', 1005, 1)")
    yield conexao
    conexao.close()


def test_vendas_batem_com_os_cupons(conexao):
    loja = ServicoDeComandas(RepositorioDeComandasSQLite(conexao))
    for numero, forma in ((1, "pix"), (2, "dinheiro")):
        comanda = loja.abrir(numero, "", "", 10, CAIXA)
        loja.lancar(comanda, [Pedido(1, 1)], CAIXA)                 # 10,05 + 10% = 11,06 (taxa 1,01)
        loja.registrar_pagamento(comanda, forma, 1106, CAIXA)
        loja.fechar(comanda, CAIXA)
    with conexao:   # uma comanda de antes de a taxa ser gravada no fechamento
        conexao.execute("UPDATE comandas SET taxa_centavos = NULL WHERE numero = 2")
    loja.abrir(3, "", "", 10, CAIXA)                                 # aberta: não entra no faturamento
    relatorio = RelatorioDeVendas(RepositorioDeVendasSQLite(conexao))
    resumo = relatorio.resumo(*DIA)
    assert (resumo.comandas, resumo.faturamento, resumo.taxa, resumo.ticket_medio, resumo.abertas) == (2, 2212, 202, 1106, 1)
    assert sorted((f.forma, f.valor) for f in resumo.formas) == [("dinheiro", 1106), ("pix", 1106)]
    assert [(p.nome, p.quantidade) for p in resumo.produtos] == [("Lanche", 2)]
    planilha = relatorio.planilha(*DIA, data_hora=str)
    assert [linha[0] for linha in planilha[1:]] == [1, 2] and planilha[1][-1] == "PIX 11,06"

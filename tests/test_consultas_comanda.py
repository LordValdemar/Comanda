"""Consultas das telas no SQLite da Comanda local: o que a lista, o cupom, o histórico, a cozinha e o ponto mostram."""

import pytest

from comanda import db
from src.domain.comanda import Ator, Pedido, ServicoDeComandas
from src.infrastructure.sqlite import ConsultasDaComanda, ConsultasDoPonto, RepositorioDeComandasSQLite

CAIXA = Ator(None)


@pytest.fixture
def conexao(app):
    conexao = db.conectar(app.config["BANCO"])
    with conexao:
        conexao.executemany("INSERT INTO usuarios (id, usuario, senha_hash, papel, ativo, token_sessao) VALUES (?, ?, 'x', 'garcom', ?, 't')",
                            [(7, "ana", 1), (8, "beto", 0)])
        conexao.execute("INSERT INTO produtos (id, nome, preco_centavos, vai_cozinha, codigo) VALUES (1, 'Pastel', 800, 1, '12')")
        conexao.execute("INSERT INTO produtos (id, nome, preco_centavos, vai_cozinha) VALUES (2, 'Lata', 600, 0)")
    yield conexao
    conexao.close()


def test_telas_da_comanda(conexao):
    loja = ServicoDeComandas(RepositorioDeComandasSQLite(conexao))
    aberta = loja.abrir(5, "2", "Ana", 10, CAIXA, 7)
    loja.lancar(aberta, [Pedido(1, 2), Pedido(2, 1), Pedido(1, 1)], Ator(7))
    fechada = loja.abrir(6, "", "", 10, CAIXA)
    loja.lancar(fechada, [Pedido(2, 1)], CAIXA)
    loja.registrar_pagamento(fechada, "pix", 660, CAIXA)
    loja.fechar(fechada, CAIXA)
    RepositorioDeComandasSQLite(conexao).registrar_historico(fechada, "fechar conta", "autorizado por maria", 7)
    leitura = ConsultasDaComanda(conexao)

    assert leitura.comanda(aberta)["garcom_nome"] == "ana" and leitura.comanda(999) is None
    assert leitura.aberta_com_numero("5") == aberta and leitura.aberta_com_numero("6") is None
    [linha] = leitura.abertas()
    assert (linha["numero"], linha["consumo"], linha["aguardando"], linha["garcom_nome"]) == (5, 3000, 2, "ana")
    assert [(i["nome"], i["quantidade"]) for i in leitura.itens_do_cupom(aberta)] == [("Pastel", 3), ("Lata", 1)]
    assert leitura.itens_na_cozinha(aberta) == 2
    assert [p["forma"] for p in leitura.pagamentos(fechada)] == ["pix"]
    assert [(a["acao"], a["usuario"]) for a in leitura.auditoria(fechada)] == [("fechar conta", "ana")]
    [encerrada] = leitura.encerradas("2000-01-01", "2100-01-01")
    assert (encerrada["numero"], encerrada["autorizacao"]) == (6, "autorizado por maria")
    assert leitura.produto_pelo_codigo("12") == 1 and leitura.produto_pelo_codigo("99") is None
    assert [g["usuario"] for g in leitura.garcons()] == ["ana"]       # garçom desativado não aparece
    assert [i["comanda_id"] for i in leitura.na_cozinha()] == [aberta, aberta]


def test_equipe_do_ponto(conexao):
    with conexao:
        conexao.execute("INSERT INTO ponto_registros (usuario_id, usuario_nome, entrada) VALUES (7, 'ana', '2026-10-04 12:00:00')")
    equipe = {p["usuario"]: p["trabalhando_desde"] for p in ConsultasDoPonto(conexao).equipe()}
    assert equipe == {"ana": "2026-10-04 12:00:00"}                  # o garçom desativado não aparece

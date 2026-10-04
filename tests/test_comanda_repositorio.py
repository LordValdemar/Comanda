"""Repositório da Comanda local no SQLite de verdade: concorrência, transação desfeita e valores do cupom.

As regras são as do núcleo (src/domain, testadas na plataforma); aqui se confere que o banco
local cumpre o contrato.
"""

import sqlite3
import threading

import pytest

from comanda import db
from src.domain.comanda import Ator, ErroComanda, Pedido, ServicoDeComandas
from src.infrastructure.sqlite import RepositorioDeComandasSQLite

CAIXA = Ator(usuario_id=None)


@pytest.fixture
def banco(app):
    caminho = app.config["BANCO"]
    conexao = db.conectar(caminho)
    with conexao:
        conexao.execute("INSERT INTO produtos (id, nome, preco_centavos, vai_cozinha) VALUES (1, 'Lanche', 2000, 1)")
        conexao.execute("INSERT INTO produtos (id, nome, preco_centavos, vai_cozinha) VALUES (2, 'Lata', 600, 0)")
    conexao.close()
    return caminho


def servico(caminho):
    conexao = db.conectar(caminho)
    return ServicoDeComandas(RepositorioDeComandasSQLite(conexao)), conexao


def comanda_de_22_reais(caminho):
    loja, conexao = servico(caminho)
    comanda_id = loja.abrir(10, "", "", 10, CAIXA)
    loja.lancar(comanda_id, [Pedido(1, 1)], CAIXA)   # 20,00 + 10% = 22,00
    conexao.close()
    return comanda_id


def test_dois_caixas_pagando_ao_mesmo_tempo_nao_pagam_a_mais(banco):
    comanda_id = comanda_de_22_reais(banco)
    largada, resultados = threading.Barrier(8), []

    def pagar():
        loja, conexao = servico(banco)
        largada.wait()
        try:
            loja.registrar_pagamento(comanda_id, "pix", 2200, CAIXA)
            resultados.append("pagou")
        except ErroComanda as erro:
            resultados.append(str(erro))
        finally:
            conexao.close()

    caixas = [threading.Thread(target=pagar) for _ in range(8)]
    for caixa in caixas:
        caixa.start()
    for caixa in caixas:
        caixa.join()
    assert resultados.count("pagou") == 1
    assert all(r == "Esta conta já está paga." for r in resultados if r != "pagou")


def test_erro_no_meio_nao_deixa_nada_gravado(banco, monkeypatch):
    comanda_id = comanda_de_22_reais(banco)
    loja, conexao = servico(banco)

    def banco_caiu(*_):
        raise RuntimeError("falha no meio da gravação")

    monkeypatch.setattr(RepositorioDeComandasSQLite, "registrar_historico", banco_caiu)
    with pytest.raises(RuntimeError):
        loja.registrar_pagamento(comanda_id, "pix", 1000, Ator(None, autorizado_por="caixa"))
    assert conexao.execute("SELECT COUNT(*) FROM pagamentos").fetchone()[0] == 0
    with pytest.raises(RuntimeError):
        loja.cancelar(comanda_id, "desistiu", CAIXA)
    assert conexao.execute("SELECT status FROM comandas WHERE id = ?", (comanda_id,)).fetchone()[0] == "aberta"
    conexao.close()


def test_fluxo_completo_grava_o_que_o_cupom_mostra(banco):
    loja, conexao = servico(banco)
    comanda_id = loja.abrir("7", " 03 ", "", 10, CAIXA)
    loja.lancar(comanda_id, [Pedido(1, 2, " sem cebola "), Pedido(2, 1)], CAIXA)
    itens = conexao.execute("SELECT status, observacao FROM itens ORDER BY id").fetchall()
    assert [tuple(i) for i in itens] == [("pendente", "sem cebola"), ("entregue", None)]   # a lata já sai entregue
    assert loja.marcar_tudo_pronto(comanda_id) == 1
    loja.ajustar(comanda_id, True, 160, Ator(None, autorizado_por="joao"))
    loja.registrar_pagamento(comanda_id, "dinheiro", 5000, CAIXA)   # 46,00 + 4,60 - 1,60 = 49,00
    loja.fechar(comanda_id, CAIXA)
    linha = conexao.execute("SELECT * FROM comandas WHERE id = ?", (comanda_id,)).fetchone()
    assert (linha["status"], linha["mesa"], linha["total_centavos"], linha["taxa_centavos"]) == ("fechada", "03", 4900, 460)
    assert tuple(conexao.execute("SELECT valor_centavos, recebido_centavos FROM pagamentos").fetchone()) == (4900, 5000)
    historico = [tuple(r) for r in conexao.execute("SELECT acao, detalhe FROM auditoria ORDER BY id")]
    assert historico == [("desconto", "R$ 0,00 → R$ 1,60 (autorizado por joao)")]
    with pytest.raises(ErroComanda, match="já foi fechada"):
        loja.lancar(comanda_id, [Pedido(1, 1)], CAIXA)
    conexao.close()


def test_numero_repetido_e_reabertura(banco):
    loja, conexao = servico(banco)
    primeira = loja.abrir(5, "", "", 10, CAIXA)
    with pytest.raises(ErroComanda, match="A comanda 5 já está aberta"):
        loja.abrir(5, "", "", 10, CAIXA)
    loja.cancelar(primeira, "teste", CAIXA)
    segunda = loja.abrir(5, "", "", 10, CAIXA)       # o cartão volta a ser usado
    loja.fechar(segunda, CAIXA)                        # conta zerada: fecha
    terceira = loja.abrir(5, "", "", 10, CAIXA)
    with pytest.raises(ErroComanda, match="Já existe outra comanda 5 aberta"):
        loja.reabrir(segunda, CAIXA)
    loja.cancelar(terceira, "x", CAIXA)
    loja.reabrir(segunda, CAIXA)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        loja.abrir(6, "", "", 10, Ator(usuario_id=999))   # outros erros do banco aparecem como são
    conexao.close()

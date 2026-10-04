"""Cardápio no SQLite da Comanda local: repetidos, ordem e categoria excluída (regras do núcleo)."""

import pytest

from comanda import db
from src.domain.cardapio import CategoriaRepetida, CodigoRepetido, DadosDoProduto, ServicoDeCardapio
from src.domain.erros import NaoEncontrado
from src.infrastructure.sqlite import RepositorioDeCardapioSQLite


@pytest.fixture
def cardapio(app):
    conexao = db.conectar(app.config["BANCO"])
    yield ServicoDeCardapio(RepositorioDeCardapioSQLite(conexao))
    conexao.close()


def test_repetidos_ordem_e_categoria_excluida(cardapio):
    for nome in ("Lanches", "Bebidas", "Doces"):
        cardapio.criar_categoria(nome)
    with pytest.raises(CategoriaRepetida, match="“BEBIDAS” já existe"):
        cardapio.criar_categoria("BEBIDAS")
    lanches, bebidas, doces = (c.id for c in cardapio.categorias())
    cardapio.mover_categoria(doces, para_cima=True)
    assert [c.nome for c in cardapio.categorias()] == ["Lanches", "Doces", "Bebidas"]
    cardapio.criar_produto(DadosDoProduto("X-Burger", 2500, "1", lanches, True))
    with pytest.raises(CodigoRepetido):
        cardapio.criar_produto(DadosDoProduto("X-Salada", 2600, "1", lanches, True))
    suco = cardapio.criar_produto(DadosDoProduto("Suco", 800, None, bebidas, False))
    cardapio.criar_produto(DadosDoProduto("Bala", 50, None, None, False))
    assert [(g, [p.nome for p in itens]) for g, itens in cardapio.grupos_a_venda()] == \
        [("Lanches", ["X-Burger"]), ("Bebidas", ["Suco"]), ("Outros", ["Bala"])]
    cardapio.alternar_ativo(suco)
    assert [p.nome for p in cardapio.a_venda()] == ["X-Burger", "Bala"]
    cardapio.excluir_categoria(lanches)
    assert next(p for p in cardapio.produtos() if p.nome == "X-Burger").categoria is None
    with pytest.raises(NaoEncontrado):
        cardapio.excluir_produto(999)

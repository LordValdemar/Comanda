from comanda import db
from conftest import criar_produto, postar


def test_criar_editar_e_tirar_do_cardapio(logado, app):
    postar(logado, "/cardapio/categorias", {"nome": "Lanches"})
    produto_id = criar_produto(logado, "X-Burger", "25,90", codigo="10", categoria_id="1")
    html = logado.get("/cardapio/").get_data(as_text=True)
    assert "X-Burger" in html and "R$ 25,90" in html

    postar(logado, f"/cardapio/produtos/{produto_id}",
           {"acao": "salvar", "nome": "X-Burger", "preco": "27", "codigo": "10", "categoria_id": "1", "vai_cozinha": "on"})
    with app.app_context():
        assert db.obter().execute("SELECT preco_centavos FROM produtos").fetchone()[0] == 2700

    postar(logado, f"/cardapio/produtos/{produto_id}", {"acao": "ativo"})
    with app.app_context():
        assert db.obter().execute("SELECT ativo FROM produtos").fetchone()[0] == 0


def test_preco_invalido_e_codigo_repetido(logado, app):
    postar(logado, "/cardapio/produtos", {"nome": "Coxinha", "preco": "abc"})
    criar_produto(logado, "Pastel", "8", codigo="5")
    resposta = postar(logado, "/cardapio/produtos", {"nome": "Quibe", "preco": "7", "codigo": "5"}, follow_redirects=True)
    assert "Já existe um produto com esse código" in resposta.get_data(as_text=True)
    with app.app_context():
        assert db.obter().execute("SELECT COUNT(*) FROM produtos").fetchone()[0] == 1


def test_ordem_das_categorias(logado, app):
    for nome in ("Bebidas", "Lanches", "Sobremesas"):
        postar(logado, "/cardapio/categorias", {"nome": nome})
    postar(logado, "/cardapio/categorias/3", {"acao": "subir"})
    with app.app_context():
        nomes = [c["nome"] for c in db.obter().execute("SELECT nome FROM categorias ORDER BY posicao")]
    assert nomes == ["Bebidas", "Sobremesas", "Lanches"]


def test_excluir_produto_mantem_historico(logado, app):
    from conftest import abrir_comanda
    produto_id = criar_produto(logado, "Suco", "6")
    comanda_id = abrir_comanda(logado, 1)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{produto_id}": "2"})
    postar(logado, f"/cardapio/produtos/{produto_id}", {"acao": "excluir"})
    assert "Suco" in logado.get(f"/comandas/{comanda_id}").get_data(as_text=True)

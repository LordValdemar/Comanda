import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from comanda import auth, create_app, db  # noqa: E402


@pytest.fixture(autouse=True)
def limpar_bloqueios():
    auth._tentativas.clear()
    yield
    auth._tentativas.clear()


@pytest.fixture
def app(tmp_path):
    return create_app({"PASTA_DADOS": str(tmp_path / "dados"), "TESTING": True, "SECRET_KEY": "teste"})


@pytest.fixture
def cliente(app):
    return app.test_client()


def csrf(cliente, pagina=None):
    """Token CSRF da sessão. Com `pagina`, confere também que o formulário dela traz o token."""
    if pagina:
        html = cliente.get(pagina).get_data(as_text=True)
        encontrado = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if encontrado:
            return encontrado.group(1)
    with cliente.session_transaction() as sessao:
        sessao.setdefault("csrf", "token-de-teste")
        return sessao["csrf"]


def postar(cliente, url, dados=None, pagina="/minha-senha", **kwargs):
    dados = dict(dados or {})
    dados["csrf_token"] = csrf(cliente, pagina)
    return cliente.post(url, data=dados, **kwargs)


def configurar_admin(cliente, usuario="admin", senha="senha123"):
    return postar(
        cliente, "/configurar",
        {"usuario": usuario, "senha": senha, "confirmacao": senha, "estabelecimento": "Bar do Zé"},
        pagina="/configurar",
    )


def entrar(cliente, usuario, senha="senha123"):
    cliente.post("/sair", data={"csrf_token": csrf(cliente, "/login")})
    return postar(cliente, "/login", {"usuario": usuario, "senha": senha}, pagina="/login")


def criar_pessoa(app, usuario, papel, senha="senha123"):
    with app.app_context():
        auth.criar_usuario(db.obter(), usuario, senha, papel)


def criar_produto(cliente, nome, preco, cozinha=True, codigo="", categoria_id=""):
    dados = {"nome": nome, "preco": preco, "codigo": codigo, "categoria_id": categoria_id}
    if cozinha:
        dados["vai_cozinha"] = "on"
    postar(cliente, "/cardapio/produtos", dados)
    with cliente.application.app_context():
        return db.obter().execute("SELECT id FROM produtos WHERE nome = ?", (nome,)).fetchone()["id"]


def abrir_comanda(cliente, numero, mesa=""):
    resposta = postar(cliente, "/comandas/", {"numero": str(numero), "mesa": mesa})
    return int(resposta.headers["Location"].rstrip("/").split("/")[-1])


@pytest.fixture
def logado(cliente):
    configurar_admin(cliente)
    return cliente

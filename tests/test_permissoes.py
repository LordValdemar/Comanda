"""Varredura de permissões: cada papel tenta TODAS as rotas que não são dele.

As rotas declaram quem pode usá-las (``papel_exigido`` ou a função da tela de Permissões); aqui o garçom, o caixa e a cozinha
chamam cada rota proibida para eles, com todas as ações conhecidas, e nada pode mudar no banco.
Rotas novas entram na varredura sozinhas.
"""

import pytest

from comanda import db, permissoes
from conftest import abrir_comanda, criar_pessoa, criar_produto, csrf, entrar

ACOES = ["", "excluir", "finalizar", "pagar", "ajustar", "cancelar", "pronto", "entregue", "remover_pagamento",
         "renomear", "salvar", "subir", "descer", "ativo", "exigir", "dispensar", "novo_endereco", "fecha_conta"]


def foto(app):
    with app.app_context():
        conexao = db.obter()
        tabelas = [t for (t,) in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: sorted(tuple(linha) for linha in conexao.execute(f"SELECT * FROM {t}")) for t in tabelas}


@pytest.fixture
def loja(logado, app):
    produto = criar_produto(logado, "X-Salada", "20,00")
    comanda_id = abrir_comanda(logado, 5)
    logado.post(f"/comandas/{comanda_id}/itens", data={f"qtd_{produto}": "1", "csrf_token": csrf(logado)})
    with app.app_context():
        conexao = db.obter()
        ids = {
            "comanda_id": comanda_id, "produto_id": produto,
            "item_id": conexao.execute("SELECT id FROM itens").fetchone()[0],
            "usuario_id": conexao.execute("SELECT id FROM usuarios WHERE usuario = 'admin'").fetchone()[0],
            "categoria_id": 1, "pagamento_id": 1,
        }
    formulario = {
        "nome": "invadido", "preco": "1,00", "numero": "99", "mesa": "invadida", "quantidade": "5",
        "valor": "1000", "forma": "dinheiro", "desconto": "100", "usuario": "intruso", "senha": "senha-intrusa",
        "confirmacao": "senha-intrusa", "papel": "admin", "status": "entregue", f"qtd_{produto}": "3",
        "taxa": "50", "dias": list("0123456"), "ativo": "1",
    }
    return ids, formulario


@pytest.mark.parametrize("papel", ["garcom", "caixa", "cozinha"])
def test_papel_nao_usa_rotas_que_nao_sao_dele(loja, app, cliente, papel):
    ids, formulario = loja
    criar_pessoa(app, "pessoa", papel)
    entrar(cliente, "pessoa")
    antes = foto(app)
    testadas = 0
    for regra in app.url_map.iter_rules():
        rota = app.view_functions[regra.endpoint]
        papeis = getattr(rota, "papeis", None)
        if getattr(rota, "funcao_exigida", None):  # rota da tela de Permissões: vale o padrão do papel
            with app.test_request_context():
                papeis = {papel} if permissoes.nivel_do_papel(rota.funcao_exigida, papel) else set()
        if papeis is None or papel in papeis:
            continue
        testadas += 1
        valores = {nome: ids.get(nome, 1) for nome in regra.arguments}
        url = regra.build(valores, append_unknown=False)[1]
        if "GET" in regra.methods:
            assert cliente.get(url).status_code == 403, url
        if "POST" in regra.methods:
            for acao in ACOES:
                resposta = cliente.post(url, data={**formulario, "acao": acao, "csrf_token": csrf(cliente)})
                assert resposta.status_code == 403, (url, acao)
        assert foto(app) == antes, url
    assert testadas >= 5

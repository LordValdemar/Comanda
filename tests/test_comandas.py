from comanda import db
from conftest import abrir_comanda, criar_pessoa, criar_produto, entrar, postar


def preparar(logado):
    lanche = criar_produto(logado, "X-Salada", "20,00", codigo="1")
    lata = criar_produto(logado, "Refri lata", "6,00", cozinha=False)
    return lanche, lata


def itens(app):
    with app.app_context():
        return db.obter().execute("SELECT * FROM itens ORDER BY id").fetchall()


def test_abrir_e_numero_repetido(logado, app):
    comanda_id = abrir_comanda(logado, 7, mesa="3")
    assert "Comanda 7" in logado.get(f"/comandas/{comanda_id}").get_data(as_text=True)
    # Abrir de novo o mesmo número leva para a comanda já aberta.
    resposta = postar(logado, "/comandas/", {"numero": "7"})
    assert resposta.headers["Location"].endswith(f"/comandas/{comanda_id}")
    # Buscar pelo número também.
    assert logado.get("/comandas/?numero=7").headers["Location"].endswith(f"/comandas/{comanda_id}")
    assert "não está aberta" in logado.get("/comandas/?numero=8").get_data(as_text=True)


def test_lancar_pelo_cardapio_e_pelo_codigo(logado, app):
    lanche, lata = preparar(logado)
    comanda_id = abrir_comanda(logado, 1)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "2", f"obs_{lanche}": "sem cebola", f"qtd_{lata}": "1"})
    postar(logado, f"/comandas/{comanda_id}/itens", {"codigo": "1", "codigo_qtd": "1"})
    lista = itens(app)
    assert [(i["nome"], i["quantidade"], i["status"]) for i in lista] == [
        ("X-Salada", 2, "pendente"), ("Refri lata", 1, "entregue"), ("X-Salada", 1, "pendente"),
    ]
    assert lista[0]["observacao"] == "sem cebola"
    assert "R$ 66,00" in logado.get(f"/comandas/{comanda_id}").get_data(as_text=True)


def test_preco_fica_o_da_hora_do_pedido(logado, app):
    lanche, _ = preparar(logado)
    comanda_id = abrir_comanda(logado, 1)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    postar(logado, f"/cardapio/produtos/{lanche}", {"acao": "salvar", "nome": "X-Salada", "preco": "99", "vai_cozinha": "on"})
    assert itens(app)[0]["preco_centavos"] == 2000


def test_fluxo_da_cozinha(logado, app):
    lanche, lata = preparar(logado)
    comanda_id = abrir_comanda(logado, 5, mesa="2")
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1", f"qtd_{lata}": "1"})
    dados = logado.get("/api/cozinha").get_json()
    assert len(dados["comandas"]) == 1
    assert [i["nome"] for i in dados["comandas"][0]["itens"]] == ["X-Salada"]  # a lata não vai para a cozinha
    item_id = dados["comandas"][0]["itens"][0]["id"]

    token = {"X-CSRF-Token": logado.get("/cozinha") and _csrf_cozinha(logado)}
    assert logado.post(f"/api/cozinha/itens/{item_id}", data={"direcao": "avancar"}).status_code == 400  # sem CSRF
    assert logado.post(f"/api/cozinha/itens/{item_id}", data={"direcao": "avancar"}, headers=token).get_json() == {"status": "preparando"}
    assert logado.post(f"/api/cozinha/itens/{item_id}", data={"direcao": "voltar"}, headers=token).get_json() == {"status": "pendente"}
    logado.post(f"/api/cozinha/itens/{item_id}", data={"direcao": "avancar"}, headers=token)
    logado.post(f"/api/cozinha/itens/{item_id}", data={"direcao": "avancar"}, headers=token)
    # Pronto: aparece para o garçom servir.
    assert "Prontos para servir" in logado.get("/comandas/").get_data(as_text=True)
    postar(logado, f"/comandas/{comanda_id}/itens/{item_id}", {"acao": "entregue"})
    assert logado.get("/api/cozinha").get_json() == {"comandas": []}


def _csrf_cozinha(cliente):
    import re
    html = cliente.get("/cozinha").get_data(as_text=True)
    return re.search(r'data-csrf="([^"]+)"', html).group(1)


def test_garcom_so_cancela_antes_da_cozinha(cliente, app):
    from conftest import configurar_admin
    configurar_admin(cliente)
    lanche, _ = preparar(cliente)
    criar_pessoa(app, "joao", "garcom")
    entrar(cliente, "joao")
    comanda_id = abrir_comanda(cliente, 1)
    postar(cliente, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    postar(cliente, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    primeiro, segundo = (i["id"] for i in itens(app))
    # Sem motivo, não cancela.
    postar(cliente, f"/comandas/{comanda_id}/itens/{primeiro}", {"acao": "cancelar", "motivo": ""})
    assert itens(app)[0]["status"] == "pendente"
    postar(cliente, f"/comandas/{comanda_id}/itens/{primeiro}", {"acao": "cancelar", "motivo": "lançado errado"})
    assert itens(app)[0]["status"] == "cancelado"
    with app.app_context():
        conexao = db.obter()
        with conexao:
            conexao.execute("UPDATE itens SET status = 'preparando' WHERE id = ?", (segundo,))
    resposta = postar(cliente, f"/comandas/{comanda_id}/itens/{segundo}", {"acao": "cancelar", "motivo": "x"}, follow_redirects=True)
    assert "Peça ao caixa" in resposta.get_data(as_text=True)
    # O garçom não fecha conta.
    assert cliente.get(f"/comandas/{comanda_id}/fechar").status_code == 403


def test_fechamento_com_taxa_desconto_e_troco(logado, app):
    lanche, lata = preparar(logado)
    comanda_id = abrir_comanda(logado, 9)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "2", f"qtd_{lata}": "1"})  # 46,00
    pagina = logado.get(f"/comandas/{comanda_id}/fechar").get_data(as_text=True)
    assert "R$ 4,60" in pagina and "R$ 50,60" in pagina  # taxa de 10%

    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "cobrar_taxa": "on", "desconto": "0,60"})  # 50,00
    # Cartão não pode passar do total.
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": "credito", "valor": "60"})
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": "pix", "valor": "30"})
    # Ainda faltam 20: não fecha.
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    with app.app_context():
        assert db.obter().execute("SELECT status FROM comandas").fetchone()[0] == "aberta"
    resposta = postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": "dinheiro", "valor": "50"},
                      follow_redirects=True)
    assert "Troco: R$ 30,00" in resposta.get_data(as_text=True)
    resposta = postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    assert "/cupom" in resposta.headers["Location"]
    with app.app_context():
        comanda = db.obter().execute("SELECT * FROM comandas").fetchone()
        assert (comanda["status"], comanda["total_centavos"]) == ("fechada", 5000)
    cupom = logado.get(f"/comandas/{comanda_id}/cupom").get_data(as_text=True)
    assert "RECIBO" in cupom and "R$ 50,00" in cupom and "Troco" in cupom and "Não é documento fiscal" in cupom
    # Com a comanda fechada, o mesmo número pode ser aberto de novo.
    assert abrir_comanda(logado, 9) != comanda_id


def test_sem_taxa_e_conta_zerada(logado, app):
    lanche, _ = preparar(logado)
    comanda_id = abrir_comanda(logado, 2)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "desconto": "20"})  # cortesia, sem taxa
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    with app.app_context():
        assert db.obter().execute("SELECT status, total_centavos FROM comandas").fetchone()[:] == ("fechada", 0)


def test_desconto_maior_que_a_conta(logado, app):
    lanche, _ = preparar(logado)
    comanda_id = abrir_comanda(logado, 2)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    resposta = postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "desconto": "500"}, follow_redirects=True)
    assert "não pode passar" in resposta.get_data(as_text=True)


def test_cancelar_comanda_e_reabrir(logado, app):
    lanche, _ = preparar(logado)
    comanda_id = abrir_comanda(logado, 3)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    postar(logado, f"/comandas/{comanda_id}/cancelar", {"motivo": "cliente desistiu"})
    with app.app_context():
        assert db.obter().execute("SELECT status FROM comandas").fetchone()[0] == "cancelada"
    assert itens(app)[0]["status"] == "cancelado"
    # Não dá para lançar em comanda cancelada.
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    assert len(itens(app)) == 1

    outra = abrir_comanda(logado, 4)
    postar(logado, f"/comandas/{outra}/itens", {f"qtd_{lanche}": "1"})
    postar(logado, f"/comandas/{outra}/fechar", {"acao": "pagar", "forma": "pix", "valor": "22"})
    postar(logado, f"/comandas/{outra}/fechar", {"acao": "finalizar"})
    postar(logado, f"/comandas/{outra}/reabrir")
    with app.app_context():
        conexao = db.obter()
        assert conexao.execute("SELECT status FROM comandas WHERE id = ?", (outra,)).fetchone()[0] == "aberta"
        acoes = [a["acao"] for a in conexao.execute("SELECT acao FROM auditoria ORDER BY id")]
    assert acoes == ["cancelar comanda", "reabrir comanda"]


def test_comanda_inexistente(logado):
    assert logado.get("/comandas/999").status_code == 404

from comanda import backup, db
from conftest import abrir_comanda, criar_produto, postar


def vender(logado, numero, produto, quantidade, forma, valor):
    comanda_id = abrir_comanda(logado, numero)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{produto}": str(quantidade)})
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": forma, "valor": valor})
    postar(logado, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    return comanda_id


def test_relatorio_do_dia(logado):
    cerveja = criar_produto(logado, "Cerveja", "10", cozinha=False)
    vender(logado, 1, cerveja, 2, "pix", "22")        # 20 + 2 de taxa
    vender(logado, 2, cerveja, 1, "dinheiro", "20")   # 10 + 1 de taxa, troco 9
    abrir_comanda(logado, 3)
    html = logado.get("/relatorios/").get_data(as_text=True)
    assert "R$ 33,00" in html          # faturamento
    assert "R$ 16,50" in html          # ticket médio
    assert "R$ 3,00" in html           # taxa de serviço
    assert "PIX" in html and "Dinheiro" in html
    assert "1 comanda(s) ainda aberta(s)" in html
    assert "Fechadas e canceladas (2)" in logado.get("/comandas/historico").get_data(as_text=True)


def test_csv(logado):
    cerveja = criar_produto(logado, "Cerveja", "10", cozinha=False)
    vender(logado, 1, cerveja, 1, "debito", "11")
    resposta = logado.get("/relatorios/comandas.csv")
    texto = resposta.get_data(as_text=True)
    assert resposta.mimetype == "text/csv"
    assert "comanda;mesa" in texto and "11,00" in texto and "Cartão de débito 11,00" in texto


def test_periodo_invalido_usa_hoje(logado):
    assert logado.get("/relatorios/?de=lixo&ate=2020-13-40").status_code == 200


def test_backup_e_restauracao(logado, app):
    criar_produto(logado, "Água", "4", cozinha=False)
    caminho = backup.criar_backup(app.config)
    criar_produto(logado, "Suco", "7", cozinha=False)
    with app.app_context():
        db.fechar()
    backup.restaurar_backup(app.config, caminho)
    with app.app_context():
        assert [p["nome"] for p in db.obter().execute("SELECT nome FROM produtos")] == ["Água"]


def test_backup_pelo_navegador(logado):
    resposta = postar(logado, "/ajustes/backup")
    assert resposta.status_code == 200 and resposta.data[:2] == b"PK"


def test_ajustes_taxa(logado):
    postar(logado, "/ajustes/", {"nome_estabelecimento": "Lanchonete X", "taxa_servico": "12,5"})
    cerveja = criar_produto(logado, "Cerveja", "10", cozinha=False)
    comanda_id = abrir_comanda(logado, 1)
    postar(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{cerveja}": "2"})
    assert "R$ 22,50" in logado.get(f"/comandas/{comanda_id}/fechar").get_data(as_text=True)
    resposta = postar(logado, "/ajustes/", {"taxa_servico": "50"}, follow_redirects=True)
    assert "vai de 0 a 30" in resposta.get_data(as_text=True)


def test_saude(cliente):
    assert cliente.get("/saude").get_json() == {"ok": True}

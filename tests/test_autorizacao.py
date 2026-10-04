"""Tela de Permissões e autorização por QR code (ex.: o caixa libera o garçom a fechar a conta)."""

import re

from comanda import db, permissoes
from conftest import abrir_comanda, criar_pessoa, criar_produto, csrf


def post(cliente, url, dados=None, **kwargs):
    return cliente.post(url, data={**(dados or {}), "csrf_token": csrf(cliente)}, **kwargs)


def pessoa(app, usuario):
    cliente = app.test_client()
    post(cliente, "/login", {"usuario": usuario, "senha": "senha123"})
    return cliente


def permitir(admin, **niveis):
    return post(admin, "/permissoes", {chave: str(valor) for chave, valor in niveis.items()})


def consultar(app, sql, *parametros):
    with app.app_context():
        return db.obter().execute(sql, parametros).fetchall()


def codigo_do_qr(cliente, funcao, modo="minutos", minutos=5):
    pagina = cliente.get(f"/autorizar?funcao={funcao}&modo={modo}&minutos={minutos}").get_data(as_text=True)
    return re.search(r'class="selo codigo-autorizacao">([A-Z0-9]{8})<', pagina).group(1)


def comanda_com_lanche(admin):
    lanche = criar_produto(admin, "X-Salada", "20,00")
    comanda_id = abrir_comanda(admin, 5)
    post(admin, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})
    return comanda_id


def test_padroes_e_so_o_administrador_mexe(logado, app):
    criar_pessoa(app, "caixa", "caixa")
    caixa = pessoa(app, "caixa")
    assert "Fechar conta" in logado.get("/permissoes").get_data(as_text=True)
    assert caixa.get("/permissoes").status_code == 403
    assert permitir(caixa, **{"cardapio.caixa": permissoes.SIM}).status_code == 403
    assert caixa.get("/cardapio/").status_code == 403

    permitir(logado, **{"cardapio.caixa": permissoes.SIM})
    assert caixa.get("/cardapio/").status_code == 200
    assert "Cardápio</a>" in caixa.get("/comandas/").get_data(as_text=True)


def test_garcom_fecha_conta_com_o_qr_do_caixa(logado, app):
    comanda_id = comanda_com_lanche(logado)
    criar_pessoa(app, "maria", "garcom")
    criar_pessoa(app, "joana", "garcom")
    criar_pessoa(app, "caixa", "caixa")
    permitir(logado, **{"fechar_conta.garcom": permissoes.AUTORIZACAO})
    maria, joana, caixa = pessoa(app, "maria"), pessoa(app, "joana"), pessoa(app, "caixa")

    resposta = maria.get(f"/comandas/{comanda_id}/fechar")
    assert resposta.status_code == 403 and "Precisa de autorização" in resposta.get_data(as_text=True)
    assert "Autorizar</a>" in caixa.get("/comandas/").get_data(as_text=True)

    codigo = codigo_do_qr(caixa, "fechar_conta")
    assert maria.get(f"/autorizacao/{codigo}").headers["Location"].endswith(f"/comandas/{comanda_id}/fechar")
    assert caixa.get(f"/api/autorizar/{codigo}").get_json() == {"situacao": "usado", "por": "maria"}
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar"})
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": "pix", "valor": "20"})
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    assert consultar(app, "SELECT status FROM comandas WHERE id = ?", comanda_id)[0][0] == "fechada"
    assert "autorizado por caixa" in consultar(app, "SELECT detalhe FROM auditoria WHERE acao = 'taxa de serviço'")[0][0]

    joana.get(f"/autorizacao/{codigo}")                     # uma leitura só
    assert joana.get(f"/comandas/{comanda_id}/fechar").status_code == 403
    with app.app_context():
        conexao = db.obter()
        with conexao:
            conexao.execute("UPDATE autorizacoes SET ate = '2020-01-01 00:00:00' WHERE usado_por IS NOT NULL")
    assert maria.get(f"/comandas/{comanda_id}/fechar").status_code == 403

    vencido = codigo_do_qr(caixa, "fechar_conta")
    with app.app_context():
        conexao = db.obter()
        with conexao:
            conexao.execute("UPDATE autorizacoes SET criado_em = '2020-01-01 00:00:00' WHERE codigo = ?", (vencido,))
    assert "venceu" in maria.get(f"/autorizacao/{vencido}", follow_redirects=True).get_data(as_text=True)
    proprio = codigo_do_qr(caixa, "fechar_conta")
    assert "próprio código" in caixa.get(f"/autorizacao/{proprio}", follow_redirects=True).get_data(as_text=True)
    resposta = post(maria, "/autorizacao/codigo", {"codigo": proprio.lower()}, follow_redirects=True)
    assert "Autorizado por caixa" in resposta.get_data(as_text=True)


def test_desconto_e_cancelamento_com_autorizacao(logado, app):
    comanda_id = comanda_com_lanche(logado)
    criar_pessoa(app, "caixa", "caixa")
    permitir(logado, **{"desconto.caixa": permissoes.AUTORIZACAO, "cancelar.caixa": permissoes.AUTORIZACAO})
    caixa = pessoa(app, "caixa")
    resposta = post(caixa, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "cobrar_taxa": "1", "desconto": "5"})
    assert resposta.status_code == 403
    assert post(caixa, f"/comandas/{comanda_id}/cancelar", {"motivo": "teste"}).status_code == 403

    caixa.get(f"/autorizacao/{codigo_do_qr(logado, 'desconto')}")
    post(caixa, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "cobrar_taxa": "1", "desconto": "5"})
    assert consultar(app, "SELECT desconto_centavos FROM comandas")[0][0] == 500
    assert post(caixa, f"/comandas/{comanda_id}/cancelar", {"motivo": "teste"}).status_code == 403  # outra função


def test_quem_esta_em_nao_nem_com_autorizacao(logado, app):
    criar_pessoa(app, "maria", "garcom")
    criar_pessoa(app, "caixa", "caixa")
    permitir(logado, **{"fechar_conta.cozinha": permissoes.AUTORIZACAO})
    maria, caixa = pessoa(app, "maria"), pessoa(app, "caixa")
    assert maria.get("/autorizar").status_code == 403
    codigo = codigo_do_qr(caixa, "fechar_conta")
    assert "nem com autorização" in maria.get(f"/autorizacao/{codigo}", follow_redirects=True).get_data(as_text=True)


def test_uma_vez_sem_prazo_e_historico(logado, app):
    primeira = comanda_com_lanche(logado)
    segunda = abrir_comanda(logado, 6)
    criar_pessoa(app, "maria", "garcom")
    criar_pessoa(app, "caixa", "caixa")
    permitir(logado, **{"fechar_conta.garcom": permissoes.AUTORIZACAO})
    maria, caixa = pessoa(app, "maria"), pessoa(app, "caixa")

    maria.get(f"/autorizacao/{codigo_do_qr(caixa, 'fechar_conta', 'uma')}")
    assert "Ainda falta receber" in post(maria, f"/comandas/{primeira}/fechar", {"acao": "finalizar"},
                                         follow_redirects=True).get_data(as_text=True)
    post(maria, f"/comandas/{primeira}/fechar", {"acao": "pagar", "forma": "pix", "valor": "22"})
    post(maria, f"/comandas/{primeira}/fechar", {"acao": "finalizar"})
    assert consultar(app, "SELECT status FROM comandas WHERE id = ?", primeira)[0][0] == "fechada"
    assert maria.get(f"/comandas/{segunda}/fechar").status_code == 403
    assert "autorizado por caixa" in logado.get("/comandas/historico").get_data(as_text=True)

    maria.get(f"/autorizacao/{codigo_do_qr(caixa, 'fechar_conta', 'sempre')}")
    maria = pessoa(app, "maria")
    assert maria.get(f"/comandas/{segunda}/fechar").status_code == 200
    liberacao = consultar(app, "SELECT id FROM autorizacoes WHERE modo = 'sempre'")[0][0]
    post(caixa, f"/autorizar/{liberacao}/encerrar")
    assert maria.get(f"/comandas/{segunda}/fechar").status_code == 403

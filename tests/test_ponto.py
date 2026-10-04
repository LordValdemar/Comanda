"""Controle de ponto (com QR code), garçom que fecha conta e cabeçalhos de segurança."""

import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from comanda import db, ponto
from conftest import abrir_comanda, criar_pessoa, criar_produto, csrf


def post(cliente, url, dados=None, **kwargs):
    return cliente.post(url, data={**(dados or {}), "csrf_token": csrf(cliente)}, **kwargs)


def consultar(app, sql, *parametros):
    with app.app_context():
        return db.obter().execute(sql, parametros).fetchall()


def id_de(app, usuario):
    return consultar(app, "SELECT id FROM usuarios WHERE usuario = ?", usuario)[0]["id"]


def aparelho(app, usuario, senha="senha123"):
    """Um celular novo (cliente próprio) já logado."""
    cliente = app.test_client()
    post(cliente, "/login", {"usuario": usuario, "senha": senha})
    return cliente


def ler_qr(cliente, app, token=None):
    """Simula a pessoa lendo, com o celular, o QR code que está na tela do ponto."""
    with app.app_context():
        token = token or ponto.token_qr()
    return cliente.get(f"/ponto/qr/{token}", follow_redirects=True)


def ligar_ponto(admin):
    post(admin, "/ponto/ajustes", {"ativo": "1"})


def hoje():
    return str(datetime.now(ZoneInfo("America/Sao_Paulo")).weekday())


# ---------------------------------------------------------------------------
# Ponto
# ---------------------------------------------------------------------------

def test_sem_controle_ligado_a_equipe_entra_normalmente(logado, app):
    criar_pessoa(app, "joao", "garcom")
    assert aparelho(app, "joao").get("/comandas/").status_code == 200


def test_entrada_e_saida_com_qr(logado, app):
    criar_pessoa(app, "joao", "garcom")
    ligar_ponto(logado)
    joao = aparelho(app, "joao")

    # Sem ponto aberto: tudo leva para a página do ponto, e a API da cozinha responde 401.
    assert joao.get("/comandas/").headers["Location"].endswith("/ponto")
    assert joao.get("/api/cozinha").status_code == 401
    assert "leia o <b>QR code do ponto</b>" in joao.get("/ponto").get_data(as_text=True)

    # Sem ler o QR, não registra.
    post(joao, "/ponto/entrada")
    assert consultar(app, "SELECT COUNT(*) FROM ponto_registros")[0][0] == 0

    assert "QR code lido" in ler_qr(joao, app).get_data(as_text=True)
    post(joao, "/ponto/entrada")
    assert joao.get("/comandas/").status_code == 200
    assert "Ponto aberto" in joao.get("/comandas/").get_data(as_text=True)

    ler_qr(joao, app)
    resposta = post(joao, "/ponto/saida")
    assert resposta.headers["Location"].endswith("/login")
    registro = consultar(app, "SELECT * FROM ponto_registros")[0]
    assert registro["saida"] and registro["motivo_saida"] == "saída" and registro["usuario_nome"] == "joao"


def test_qr_vale_para_uma_pessoa_so_e_vence(logado, app):
    criar_pessoa(app, "joao", "garcom")
    criar_pessoa(app, "maria", "caixa")
    ligar_ponto(logado)
    joao, maria = aparelho(app, "joao"), aparelho(app, "maria")
    with app.app_context():
        token = ponto.token_qr()
        antigo = ponto.token_qr(agora=time.time() - 10 * 60)
    assert "QR code lido" in ler_qr(joao, app, token).get_data(as_text=True)
    assert "já foi usado" in ler_qr(maria, app, token).get_data(as_text=True)
    assert "venceu" in ler_qr(maria, app, antigo).get_data(as_text=True)
    assert "venceu" in ler_qr(maria, app, "lixo").get_data(as_text=True)
    assert "QR code lido" in ler_qr(maria, app).get_data(as_text=True)


def test_qr_troca_a_cada_2_minutos_com_tolerancia(logado, app):
    inicio = 15_000_000 * ponto.QR_TROCA_SEGUNDOS
    with app.app_context():
        token = ponto.token_qr(agora=inicio + 100)
        assert ponto.token_valido(token, agora=inicio + 119)
        assert ponto.token_valido(token, agora=inicio + 140)       # 30 s de tolerância
        assert not ponto.token_valido(token, agora=inicio + 160)


def test_saida_sem_qr_fica_anotada(logado, app):
    criar_pessoa(app, "joao", "garcom")
    ligar_ponto(logado)
    joao = aparelho(app, "joao")
    ler_qr(joao, app)
    post(joao, "/ponto/entrada")
    post(joao, "/ponto/saida")
    assert consultar(app, "SELECT motivo_saida FROM ponto_registros")[0][0] == "saída sem QR code"


def test_fora_do_horario(logado, app):
    criar_pessoa(app, "joao", "garcom")
    ligar_ponto(logado)
    joao = aparelho(app, "joao")
    ler_qr(joao, app)
    post(joao, "/ponto/entrada")
    outros_dias = [d for d in "0123456" if d != hoje()]
    post(logado, f"/ponto/pessoa/{id_de(app, 'joao')}", {"dias": outros_dias})
    assert joao.get("/comandas/").headers["Location"].endswith("/ponto")
    assert consultar(app, "SELECT motivo_saida FROM ponto_registros")[0][0] == "fim do horário"
    ler_qr(joao, app)
    assert "Fora do seu horário" in post(joao, "/ponto/entrada", follow_redirects=True).get_data(as_text=True)


def test_tarefa_fecha_ponto_de_quem_passou_do_horario(logado, app):
    criar_pessoa(app, "joao", "garcom")
    ligar_ponto(logado)
    joao = aparelho(app, "joao")
    ler_qr(joao, app)
    post(joao, "/ponto/entrada")
    with app.app_context():
        conexao = db.obter()
        with conexao:
            conexao.execute("UPDATE usuarios SET horario_dias = ? WHERE usuario = 'joao'",
                            ("".join(d for d in "0123456" if d != hoje()),))
        ponto.fechar_fora_do_horario()
    assert consultar(app, "SELECT motivo_saida FROM ponto_registros")[0][0] == "fim do horário"


def test_desconectar(logado, app):
    criar_pessoa(app, "joao", "garcom")
    joao, celular = aparelho(app, "joao"), aparelho(app, "joao")
    post(logado, f"/ponto/pessoa/{id_de(app, 'joao')}/desconectar", {"voltar": "usuarios"})
    for cliente in (joao, celular):
        assert cliente.get("/comandas/").headers["Location"].startswith("/login")
    # Não desconecta a si mesmo.
    post(logado, f"/ponto/pessoa/{id_de(app, 'admin')}/desconectar")
    assert logado.get("/comandas/").status_code == 200


def test_isento_e_so_admin_mexe(logado, app):
    criar_pessoa(app, "tablet", "cozinha")
    criar_pessoa(app, "maria", "caixa")
    ligar_ponto(logado)
    post(logado, f"/ponto/pessoa/{id_de(app, 'tablet')}", {"dias": list("0123456"), "isento": "on"})
    assert aparelho(app, "tablet").get("/cozinha").status_code == 200
    maria = aparelho(app, "maria")
    assert maria.get("/ponto/equipe").status_code in (302, 403)
    assert post(maria, "/ponto/ajustes", {"ativo": "0"}).status_code in (302, 403)
    with app.app_context():
        assert ponto.ativo()


def test_tela_do_qr_e_relatorio(logado, app):
    pagina = logado.get("/ponto/equipe").get_data(as_text=True)
    endereco = re.search(r'<p class="endereco">http://localhost(/ponto/quiosque/[^<]+)</p>', pagina).group(1)
    anonimo = app.test_client()
    assert "Bar do Zé" in anonimo.get(endereco).get_data(as_text=True)
    api = endereco.replace("/ponto/quiosque/", "/api/ponto/quiosque/")
    assert anonimo.get(api).get_json() == {"ativo": False}
    ligar_ponto(logado)
    dados = anonimo.get(api).get_json()
    assert dados["qr"].startswith("data:image/svg+xml")
    assert "qr" not in anonimo.get(api + "?versao=" + dados["versao"]).get_json()

    criar_pessoa(app, "joao", "garcom")
    joao = aparelho(app, "joao")
    ler_qr(joao, app)
    post(joao, "/ponto/entrada")
    assert anonimo.get(api + "?versao=" + dados["versao"]).get_json()["versao"] != dados["versao"]
    assert "joao" in logado.get("/ponto/relatorio.csv").get_data(as_text=True)

    post(logado, "/ponto/qr-ajustes", {"acao": "novo_endereco"})
    assert anonimo.get(endereco).status_code == 404


def test_horario_que_vira_a_noite():
    sexta_das_18_as_2 = {"horario_dias": "4", "horario_inicio": "18:00", "horario_fim": "02:00"}
    fuso = ZoneInfo("America/Sao_Paulo")

    def em(dia, hora):  # 2026-10-02 é uma sexta-feira
        return datetime.fromisoformat(f"2026-10-{dia:02d}T{hora}").replace(tzinfo=fuso)

    assert ponto.no_horario(sexta_das_18_as_2, em(2, "19:00"))
    assert ponto.no_horario(sexta_das_18_as_2, em(3, "01:30"))
    assert not ponto.no_horario(sexta_das_18_as_2, em(3, "19:00"))
    assert not ponto.no_horario(sexta_das_18_as_2, em(2, "01:30"))


# ---------------------------------------------------------------------------
# Garçom que fecha conta
# ---------------------------------------------------------------------------

def test_garcom_autorizado_fecha_conta_e_tira_taxa(logado, app):
    lanche = criar_produto(logado, "X-Salada", "20,00")
    criar_pessoa(app, "maria", "garcom")
    comanda_id = abrir_comanda(logado, 5)
    post(logado, f"/comandas/{comanda_id}/itens", {f"qtd_{lanche}": "1"})

    maria = aparelho(app, "maria")
    assert maria.get(f"/comandas/{comanda_id}/fechar").status_code == 403
    post(logado, f"/usuarios/{id_de(app, 'maria')}", {"acao": "fecha_conta"})
    assert "fecha contas" in logado.get("/usuarios").get_data(as_text=True)

    pagina = maria.get(f"/comandas/{comanda_id}/fechar").get_data(as_text=True)
    assert "Taxa de serviço" in pagina and 'name="desconto"' not in pagina
    assert post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar", "desconto": "5"}).status_code == 403
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "ajustar"})  # tira a taxa
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "pagar", "forma": "pix", "valor": "20"})
    post(maria, f"/comandas/{comanda_id}/fechar", {"acao": "finalizar"})
    comanda = consultar(app, "SELECT status, cobrar_taxa, fechada_por FROM comandas WHERE id = ?", comanda_id)[0]
    assert comanda["status"] == "fechada" and comanda["cobrar_taxa"] == 0 and comanda["fechada_por"] == id_de(app, "maria")

    post(logado, f"/usuarios/{id_de(app, 'maria')}", {"acao": "fecha_conta"})
    assert maria.get(f"/comandas/{comanda_id}/fechar").status_code == 403


# ---------------------------------------------------------------------------
# Cabeçalhos de segurança
# ---------------------------------------------------------------------------

def test_csp_sem_estilo_embutido_e_permissoes(logado):
    resposta = logado.get("/comandas/")
    assert "unsafe-inline" not in resposta.headers["Content-Security-Policy"]
    assert "camera=(self)" in resposta.headers["Permissions-Policy"]
    pasta = os.path.join(os.path.dirname(__file__), "..", "comanda", "templates")
    for raiz, _, arquivos in os.walk(pasta):
        for nome in arquivos:
            with open(os.path.join(raiz, nome), encoding="utf-8") as arquivo:
                html = arquivo.read()
            assert 'style="' not in html and "<style" not in html, nome


def test_garcom_que_muda_de_papel_perde_o_fechar_conta(logado, app):
    criar_pessoa(app, "maria", "garcom")
    maria = id_de(app, "maria")
    post(logado, f"/usuarios/{maria}", {"acao": "fecha_conta"})
    post(logado, f"/usuarios/{maria}", {"acao": "papel", "papel": "cozinha"})
    post(logado, f"/usuarios/{maria}", {"acao": "papel", "papel": "garcom"})
    linha = consultar(app, "SELECT papel, fecha_conta FROM usuarios WHERE id = ?", maria)[0]
    assert (linha["papel"], linha["fecha_conta"]) == ("garcom", 0)

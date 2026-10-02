import os
import re
import sqlite3
import time

from comanda import create_app, db, totp
from conftest import configurar_admin, criar_pessoa, csrf, entrar, postar


def segredo_da_pagina(cliente):
    html = cliente.get("/minha-conta").get_data(as_text=True)
    assert "data:image/svg+xml" in html  # QR code
    return re.search(r'class="chave">([A-Z2-7]+)<', html).group(1)


def ativar_2fa(cliente, agora):
    segredo = segredo_da_pagina(cliente)
    postar(cliente, "/minha-conta/2fa/ativar", {"codigo": totp.codigo_atual(segredo, agora - 30)})
    return segredo


def test_totp():
    segredo = totp.novo_segredo()
    agora = 1_790_000_000
    codigo = totp.codigo_atual(segredo, agora)
    contador = totp.verificar(segredo, codigo, agora=agora)
    assert contador is not None
    assert totp.verificar(segredo, codigo, ultimo_usado=contador, agora=agora) is None  # não reusa
    assert totp.verificar(segredo, totp.codigo_atual(segredo, agora - 30), agora=agora) is not None  # relógio atrasado
    assert totp.verificar(segredo, totp.codigo_atual(segredo, agora - 120), agora=agora) is None
    assert totp.verificar(segredo, "abc", agora=agora) is None


def test_codigo_errado_nao_ativa(logado, app):
    segredo_da_pagina(logado)
    postar(logado, "/minha-conta/2fa/ativar", {"codigo": "000000"})
    with app.app_context():
        assert db.obter().execute("SELECT totp_segredo FROM usuarios").fetchone()[0] is None


def test_login_com_duas_etapas(cliente, app):
    agora = time.time()
    configurar_admin(cliente)
    segredo = ativar_2fa(cliente, agora)
    with app.app_context():
        assert db.obter().execute("SELECT totp_segredo FROM usuarios").fetchone()[0] == segredo

    resposta = entrar(cliente, "admin")
    assert resposta.headers["Location"].endswith("/login/codigo")
    # Só a senha não basta: as páginas continuam fechadas.
    assert cliente.get("/comandas/").status_code == 302
    assert postar(cliente, "/login/codigo", {"codigo": "123456"}).status_code == 401
    resposta = postar(cliente, "/login/codigo", {"codigo": totp.codigo_atual(segredo)})
    assert resposta.headers["Location"].endswith("/comandas/")
    assert cliente.get("/comandas/").status_code == 200

    # O mesmo código não serve de novo.
    entrar(cliente, "admin")
    assert postar(cliente, "/login/codigo", {"codigo": totp.codigo_atual(segredo)}).status_code == 401


def test_etapa_do_codigo_expira(cliente, app):
    configurar_admin(cliente)
    ativar_2fa(cliente, time.time())
    entrar(cliente, "admin")
    with cliente.session_transaction() as sessao:
        sessao["2fa_desde"] = time.time() - 600
    assert cliente.get("/login/codigo").headers["Location"].endswith("/login")


def test_codigo_sem_passar_pela_senha(cliente):
    configurar_admin(cliente)
    cliente.post("/sair", data={"csrf_token": csrf(cliente)})
    assert cliente.get("/login/codigo").headers["Location"].endswith("/login")


def test_admin_tira_duas_etapas_de_quem_perdeu_o_celular(cliente, app):
    configurar_admin(cliente)
    criar_pessoa(app, "maria", "caixa")
    entrar(cliente, "maria")
    ativar_2fa(cliente, time.time())
    entrar(cliente, "admin")
    assert "2 etapas" in cliente.get("/usuarios").get_data(as_text=True)
    postar(cliente, "/usuarios/2", {"acao": "desativar_2fa"})
    with app.app_context():
        assert db.obter().execute("SELECT totp_segredo FROM usuarios WHERE id = 2").fetchone()[0] is None
    resposta = entrar(cliente, "maria")
    assert resposta.headers["Location"].endswith("/comandas/")


def test_desativar_a_propria_exige_senha_e_codigo(cliente, app):
    configurar_admin(cliente)
    segredo = ativar_2fa(cliente, time.time())
    postar(cliente, "/minha-conta/2fa/desativar", {"senha": "errada", "codigo": totp.codigo_atual(segredo)})
    with app.app_context():
        assert db.obter().execute("SELECT totp_segredo FROM usuarios").fetchone()[0] is not None
    postar(cliente, "/minha-conta/2fa/desativar", {"senha": "senha123", "codigo": totp.codigo_atual(segredo)})
    with app.app_context():
        assert db.obter().execute("SELECT totp_segredo FROM usuarios").fetchone()[0] is None
    assert cliente.get("/comandas/").status_code == 200  # continua logado


def test_certificado(cliente, app):
    assert "não está ligado" in cliente.get("/certificado").get_data(as_text=True)
    assert cliente.get("/certificado.crt").status_code == 404
    pasta = os.path.join(app.config["PASTA_DADOS"], "https", "pki", "authorities", "local")
    os.makedirs(pasta)
    with open(os.path.join(pasta, "root.crt"), "w") as arquivo:
        arquivo.write("-----BEGIN CERTIFICATE-----\n")
    assert "Baixar o certificado" in cliente.get("/certificado").get_data(as_text=True)
    resposta = cliente.get("/certificado.crt")
    assert resposta.status_code == 200 and resposta.mimetype == "application/x-x509-ca-cert"


def test_migracao_de_banco_antigo(tmp_path):
    """Um banco da versão 1 (antes das duas etapas) ganha as colunas novas sem perder os usuários."""
    banco = tmp_path / "dados" / "comanda.sqlite3"
    banco.parent.mkdir()
    conexao = sqlite3.connect(banco)
    conexao.executescript(db.MIGRACOES[0] + "\nPRAGMA user_version = 1;")
    conexao.execute("INSERT INTO usuarios (usuario, senha_hash, papel, token_sessao) VALUES ('velho', 'x', 'admin', 't')")
    conexao.commit()
    conexao.close()
    app = create_app({"PASTA_DADOS": str(tmp_path / "dados"), "TESTING": True, "SECRET_KEY": "teste"})
    with app.app_context():
        linha = db.obter().execute("SELECT usuario, totp_segredo, totp_ultimo FROM usuarios").fetchone()
    assert tuple(linha) == ("velho", None, 0)

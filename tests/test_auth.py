from conftest import configurar_admin, criar_pessoa, csrf, entrar, postar


def test_primeiro_acesso_cria_admin(cliente):
    assert cliente.get("/").headers["Location"].endswith("/login")
    assert cliente.get("/login").headers["Location"].endswith("/configurar")
    resposta = configurar_admin(cliente)
    assert resposta.headers["Location"].endswith("/cardapio/")
    assert "Bar do Zé" in cliente.get("/cardapio/").get_data(as_text=True)
    # Depois de configurado, /configurar não cria outro admin.
    cliente.post("/sair", data={"csrf_token": csrf(cliente, "/minha-senha")})
    assert cliente.get("/configurar").headers["Location"].endswith("/login")


def test_senha_errada_e_bloqueio(cliente, app):
    configurar_admin(cliente)
    cliente.post("/sair", data={"csrf_token": csrf(cliente, "/minha-senha")})
    for _ in range(5):
        assert postar(cliente, "/login", {"usuario": "admin", "senha": "errada"}, pagina="/login").status_code == 401
    assert postar(cliente, "/login", {"usuario": "admin", "senha": "senha123"}, pagina="/login").status_code == 429


def test_post_sem_csrf_e_recusado(logado):
    assert logado.post("/comandas/", data={"numero": "1"}).status_code == 400


def test_papeis(cliente, app):
    configurar_admin(cliente)
    criar_pessoa(app, "joao", "garcom")
    criar_pessoa(app, "chef", "cozinha")
    criar_pessoa(app, "maria", "caixa")

    entrar(cliente, "joao")
    assert cliente.get("/comandas/").status_code == 200
    assert cliente.get("/cardapio/").status_code == 403
    assert cliente.get("/relatorios/").status_code == 403
    assert cliente.get("/cozinha").status_code == 403

    entrar(cliente, "chef")
    assert cliente.get("/").headers["Location"].endswith("/cozinha")
    assert cliente.get("/cozinha").status_code == 200
    assert cliente.get("/comandas/").status_code == 403

    entrar(cliente, "maria")
    assert cliente.get("/relatorios/").status_code == 200
    assert cliente.get("/cozinha").status_code == 200
    assert cliente.get("/usuarios").status_code == 403


def test_desativar_derruba_sessao(cliente, app):
    configurar_admin(cliente)
    criar_pessoa(app, "joao", "garcom")
    garcom = app.test_client()
    entrar(garcom, "joao")
    assert garcom.get("/comandas/").status_code == 200
    postar(cliente, "/usuarios/2", {"acao": "ativo"})
    assert garcom.get("/comandas/").status_code == 302
    assert postar(garcom, "/login", {"usuario": "joao", "senha": "senha123"}, pagina="/login").status_code == 403


def test_nao_remove_ultimo_admin(logado):
    postar(logado, "/usuarios/1", {"acao": "papel", "papel": "garcom"})
    assert logado.get("/usuarios").status_code == 200  # continua admin
    postar(logado, "/usuarios/1", {"acao": "ativo"})
    assert logado.get("/usuarios").status_code == 200


def test_trocar_propria_senha(logado):
    resposta = postar(logado, "/minha-senha", {"atual": "senha123", "nova": "outra-senha", "confirmacao": "outra-senha"})
    assert resposta.status_code == 302
    logado.post("/sair", data={"csrf_token": csrf(logado, "/minha-senha")})
    assert postar(logado, "/login", {"usuario": "admin", "senha": "outra-senha"}, pagina="/login").status_code == 302


def test_proximo_nao_redireciona_para_fora(cliente):
    configurar_admin(cliente)
    cliente.post("/sair", data={"csrf_token": csrf(cliente, "/minha-senha")})
    token = csrf(cliente, "/login")
    resposta = cliente.post("/login?proximo=//malicioso.com", data={"usuario": "admin", "senha": "senha123", "csrf_token": token})
    assert "malicioso" not in resposta.headers["Location"]

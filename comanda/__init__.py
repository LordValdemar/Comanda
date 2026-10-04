"""
Comanda - comanda eletrônica para bares, restaurantes e lanchonetes, na rede local.

Este pacote cria a aplicação Flask (create_app) com estas partes:
- auth:        login, usuários e papéis (admin, caixa, garçom, cozinha), proteção CSRF
- cardapio:    categorias e produtos
- comandas:    abrir, lançar pedidos, fechar a conta e imprimir o cupom
- cozinha:     tela da cozinha, atualizada sozinha
- relatorios:  vendas por período
- ajustes:     dados do estabelecimento e backup
"""

import logging
import os
import secrets
from logging.handlers import TimedRotatingFileHandler

from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import ajustes, auth, cardapio, certificado, comandas, cozinha, db, formatos, permissoes, ponto, relatorios

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_ligado(nome):
    return os.environ.get(nome, "").strip().lower() in {"1", "true", "sim", "yes"}


def montar_config(sobrescrever=None):
    """Lê a configuração das variáveis de ambiente (veja o README)."""
    sobrescrever = sobrescrever or {}
    pasta_dados = os.path.abspath(
        sobrescrever.get("PASTA_DADOS") or os.environ.get("PASTA_DADOS") or os.path.join(PASTA_PROJETO, "dados")
    )
    config = {
        "PASTA_DADOS": pasta_dados,
        "BANCO": os.path.join(pasta_dados, "comanda.sqlite3"),
        "PASTA_BACKUPS": os.path.join(pasta_dados, "backups"),
        "PASTA_LOGS": os.path.join(pasta_dados, "logs"),
        "BACKUP_MANTER": int(os.environ.get("BACKUP_MANTER", 14)),
        "LOGS_DIAS": int(os.environ.get("LOGS_DIAS", 90)),
        "FUSO_HORARIO": os.environ.get("FUSO_HORARIO", "America/Sao_Paulo"),
        "MAX_CONTENT_LENGTH": 1024 * 1024,  # só formulários: nada de envio de arquivos
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _env_ligado("COOKIE_SEGURO"),
        # Nome diferente do Painel de Propagandas: no mesmo servidor (mesmo IP), os cookies não se misturam.
        "SESSION_COOKIE_NAME": "comanda_sessao",
        "PERMANENT_SESSION_LIFETIME": 30 * 24 * 3600,  # 30 dias: a equipe não precisa entrar todo dia
        "ATRAS_DE_PROXY": _env_ligado("ATRAS_DE_PROXY"),
    }
    config.update(sobrescrever)
    return config


def _chave_secreta(pasta_dados):
    """Usa CHAVE_SECRETA do ambiente ou cria uma chave aleatória no disco."""
    if os.environ.get("CHAVE_SECRETA"):
        return os.environ["CHAVE_SECRETA"]
    caminho = os.path.join(pasta_dados, "chave_secreta")
    if not os.path.exists(caminho):
        descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descritor, "w") as f:
            f.write(secrets.token_hex(32))
    with open(caminho) as f:
        return f.read().strip()


def _configurar_logs(app):
    formato = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    arquivo = TimedRotatingFileHandler(
        os.path.join(app.config["PASTA_LOGS"], "comanda.log"),
        when="midnight", backupCount=app.config["LOGS_DIAS"], encoding="utf-8",
    )
    arquivo.setFormatter(formato)
    registro = logging.getLogger("comanda")
    registro.setLevel(logging.INFO)
    registro.propagate = False  # o Waitress configura o log raiz; evita linhas duplicadas
    # Evita handlers duplicados quando create_app é chamado várias vezes (testes).
    for antigo in list(registro.handlers):
        registro.removeHandler(antigo)
        antigo.close()
    registro.addHandler(arquivo)
    if not app.testing:
        console = logging.StreamHandler()
        console.setFormatter(formato)
        registro.addHandler(console)


def create_app(sobrescrever=None):
    app = Flask(__name__)
    app.config.update(montar_config(sobrescrever))

    for chave in ("PASTA_DADOS", "PASTA_BACKUPS", "PASTA_LOGS"):
        os.makedirs(app.config[chave], exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _chave_secreta(app.config["PASTA_DADOS"])

    if app.config["ATRAS_DE_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configurar_logs(app)
    db.migrar(app.config["BANCO"])
    app.teardown_appcontext(db.fechar)

    auth.registrar(app)
    ponto.registrar(app)
    permissoes.registrar(app)
    for modulo in (cardapio, comandas, cozinha, relatorios, ajustes, certificado):
        app.register_blueprint(modulo.bp)

    app.jinja_env.filters["reais"] = formatos.reais
    app.jinja_env.filters["data_hora"] = formatos.data_hora
    app.jinja_env.filters["hora"] = formatos.hora
    app.jinja_env.filters["data_extenso"] = formatos.data_extenso
    app.jinja_env.filters["minutos"] = formatos.minutos_desde

    @app.context_processor
    def estabelecimento():
        return {"nome_estabelecimento": db.ler_config("nome_estabelecimento") or "Comanda"}

    @app.route("/saude")
    def saude():
        db.obter().execute("SELECT 1").fetchone()
        return {"ok": True}

    @app.after_request
    def cabecalhos_de_seguranca(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        # Libera só o que o sistema usa: tela acesa na cozinha e câmera para o QR do ponto.
        resposta.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), screen-wake-lock=(self), fullscreen=(self), microphone=(), geolocation=(), "
            "payment=(), usb=(), serial=(), bluetooth=(), browsing-topics=()",
        )
        resposta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-src 'none'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        return resposta

    @app.errorhandler(400)
    def requisicao_invalida(_erro):
        if request.path.startswith("/api/"):
            return {"erro": "requisição inválida"}, 400
        return (
            "<h1>Requisição inválida</h1><p>A página pode ter expirado. "
            "<a href='/'>Voltar</a> e tente de novo.</p>",
            400,
        )

    @app.errorhandler(403)
    def proibido(_erro):
        if request.path.startswith("/api/"):
            return {"erro": "sem permissão"}, 403
        return "<h1>Sem permissão</h1><p>Seu usuário não pode abrir esta página. <a href='/'>Voltar</a></p>", 403

    return app

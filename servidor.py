"""
Inicia a Comanda em modo de produção (servidor Waitress), com o backup diário.

    python servidor.py

Para desenvolvimento, com recarga automática:

    flask --app comanda run --debug --port 5001
"""

import logging
import os
import socket

from waitress import serve

from comanda import arquivo_config, create_app
from comanda.tarefas import iniciar_tarefas


def ip_na_rede_local():
    """IP deste computador na rede do estabelecimento (para abrir no celular dos garçons)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
            conexao.connect(("8.8.8.8", 80))  # UDP: nada é enviado, só escolhe a interface de rede
            return conexao.getsockname()[0]
    except OSError:
        return None


def main():
    arquivo = arquivo_config.carregar()  # configuracao.env, se existir
    app = create_app()
    iniciar_tarefas(app)

    host = os.environ.get("HOST", "0.0.0.0")
    porta = int(os.environ.get("PORTA", 5001))  # a 5000 é do Painel de Propagandas
    log = logging.getLogger("comanda")
    log.info("Comanda iniciada")
    log.info("Neste computador: http://localhost:%s/", porta)
    ip = ip_na_rede_local()
    if ip and host == "0.0.0.0":
        log.info("Na rede (celulares dos garçons, cozinha, caixa): http://%s:%s/", ip, porta)
    log.info("Dados em: %s", app.config["PASTA_DADOS"])
    if arquivo:
        log.info("Configuração lida de: %s", arquivo)

    opcoes = {"threads": int(os.environ.get("THREADS", 8)), "ident": "Comanda"}
    if app.config["ATRAS_DE_PROXY"]:
        opcoes.update(
            trusted_proxy=os.environ.get("PROXY_CONFIAVEL", "127.0.0.1"),
            trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
            clear_untrusted_proxy_headers=True,
        )
    serve(app, host=host, port=porta, **opcoes)


if __name__ == "__main__":
    main()

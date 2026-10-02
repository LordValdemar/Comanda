"""Certificado do HTTPS na rede local (deploy/ativar-https.sh), para instalar nos aparelhos."""

import os

from flask import Blueprint, abort, current_app, render_template, send_file

bp = Blueprint("certificado", __name__)


def caminho_certificado():
    """Certificado raiz da autoridade local criada pelo Caddy (só existe com o HTTPS ligado)."""
    caminho = os.path.join(current_app.config["PASTA_DADOS"], "https", "pki", "authorities", "local", "root.crt")
    return caminho if os.path.isfile(caminho) else None


@bp.route("/certificado")
def instrucoes():
    # Página pública: é aberta antes de o aparelho confiar no cadeado (e às vezes antes do login).
    return render_template("certificado.html", disponivel=caminho_certificado() is not None)


@bp.route("/certificado.crt")
def baixar():
    caminho = caminho_certificado()
    if caminho is None:
        abort(404)
    # Este tipo faz o Android e o iPhone oferecerem a instalação do certificado.
    return send_file(caminho, mimetype="application/x-x509-ca-cert", as_attachment=True,
                     download_name="comanda-certificado.crt")

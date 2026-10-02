"""Ajustes do estabelecimento (nome no cupom, taxa de serviço) e backup pelo navegador."""

import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from . import backup, db
from .auth import papel_exigido
from .certificado import caminho_certificado
from .comandas import taxa_padrao

bp = Blueprint("ajustes", __name__, url_prefix="/ajustes")


@bp.route("/", methods=["GET", "POST"])
@papel_exigido("admin")
def pagina():
    if request.method == "POST":
        try:
            taxa = float(request.form.get("taxa_servico", "10").replace(",", ".") or 0)
        except ValueError:
            taxa = -1
        if not 0 <= taxa <= 30:
            flash("A taxa de serviço vai de 0 a 30%.", "erro")
            return redirect(url_for("ajustes.pagina"))
        db.gravar_config("nome_estabelecimento", request.form.get("nome_estabelecimento", "").strip()[:80])
        db.gravar_config("endereco", request.form.get("endereco", "").strip()[:160])
        db.gravar_config("rodape_cupom", request.form.get("rodape_cupom", "").strip()[:160])
        db.gravar_config("taxa_servico", f"{taxa:g}")
        flash("Ajustes salvos. A nova taxa vale para as comandas abertas daqui em diante.", "ok")
        return redirect(url_for("ajustes.pagina"))
    pasta = current_app.config["PASTA_BACKUPS"]
    backups = sorted((n for n in os.listdir(pasta) if n.startswith("backup-") and n.endswith(".zip")), reverse=True)
    return render_template(
        "ajustes.html",
        nome_estabelecimento=db.ler_config("nome_estabelecimento"),
        endereco=db.ler_config("endereco"),
        rodape_cupom=db.ler_config("rodape_cupom", "Obrigado pela preferência!"),
        taxa_servico=f"{taxa_padrao():g}".replace(".", ","),
        backups=backups,
        https_ligado=caminho_certificado() is not None,
    )


@bp.route("/backup", methods=["POST"])
@papel_exigido("admin")
def fazer_backup():
    caminho = backup.criar_backup(current_app.config)
    return send_file(caminho, as_attachment=True, download_name=os.path.basename(caminho))

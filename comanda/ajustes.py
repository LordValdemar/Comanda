"""Ajustes do estabelecimento (dados e logo do cupom, taxa de serviço) e backup pelo navegador."""

import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from src.domain.empresas import LOGO_MAX_BYTES, CadastroInvalido, ler_logo

from . import backup, db
from .auth import papel_exigido
from .certificado import caminho_certificado
from .comandas import taxa_padrao

bp = Blueprint("ajustes", __name__, url_prefix="/ajustes")

# Campos de texto do cupom: (chave, tamanho máximo).
CAMPOS = (("nome_estabelecimento", 80), ("cnpj", 20), ("email", 80), ("endereco", 160), ("telefone", 40),
          ("local", 60), ("rodape_cupom", 160))


def dados_da_loja():
    """O que vai no cabeçalho e no fim do cupom."""
    dados = {chave: db.ler_config(chave) for chave, _ in CAMPOS}
    dados["nome_estabelecimento"] = dados["nome_estabelecimento"] or "Comanda"
    dados["rodape_cupom"] = db.ler_config("rodape_cupom", "Obrigado pela preferência!")
    dados["logo"] = db.ler_config("logo")
    return dados


@bp.route("/", methods=["GET", "POST"])
@papel_exigido("admin")
def pagina():
    if request.method == "POST":
        if request.form.get("acao") == "remover_logo":
            db.gravar_config("logo", "")
            flash("Logo removido do cupom.", "ok")
            return redirect(url_for("ajustes.pagina"))
        try:
            taxa = float(request.form.get("taxa_servico", "10").replace(",", ".") or 0)
        except ValueError:
            taxa = -1
        if not 0 <= taxa <= 30:
            flash("A taxa de serviço vai de 0 a 30%.", "erro")
            return redirect(url_for("ajustes.pagina"))
        arquivo = request.files.get("logo")
        if arquivo and arquivo.filename:
            try:   # PNG ou JPG até 300 KB (regra do núcleo): o logo vai junto em cada cupom
                logo = ler_logo(arquivo.read(LOGO_MAX_BYTES + 1))
            except CadastroInvalido as erro:
                flash(str(erro), "erro")
                return redirect(url_for("ajustes.pagina"))
            db.gravar_config("logo", logo)
        for chave, tamanho in CAMPOS:
            if chave in request.form:
                db.gravar_config(chave, request.form.get(chave, "").strip()[:tamanho])
        db.gravar_config("taxa_servico", f"{taxa:g}")
        flash("Ajustes salvos. A nova taxa vale para as comandas abertas daqui em diante.", "ok")
        return redirect(url_for("ajustes.pagina"))
    pasta = current_app.config["PASTA_BACKUPS"]
    backups = sorted((n for n in os.listdir(pasta) if n.startswith("backup-") and n.endswith(".zip")), reverse=True)
    return render_template(
        "ajustes.html",
        dados=dados_da_loja(),
        taxa_servico=f"{taxa_padrao():g}".replace(".", ","),
        backups=backups,
        https_ligado=caminho_certificado() is not None,
    )


@bp.route("/backup", methods=["POST"])
@papel_exigido("admin")
def fazer_backup():
    caminho = backup.criar_backup(current_app.config)
    return send_file(caminho, as_attachment=True, download_name=os.path.basename(caminho))

"""Backup e restauração do banco em um único .zip."""

import glob
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime

log = logging.getLogger("comanda.backup")

NOME_BANCO_NO_ZIP = "comanda.sqlite3"


def criar_backup(config):
    """Gera dados/backups/backup-AAAAMMDD-HHMMSS.zip e apaga os mais antigos."""
    pasta_backups = config["PASTA_BACKUPS"]
    os.makedirs(pasta_backups, exist_ok=True)
    destino = os.path.join(pasta_backups, f"backup-{datetime.now():%Y%m%d-%H%M%S}.zip")
    parcial = destino + ".parcial"

    with tempfile.TemporaryDirectory() as temporaria:
        # A API de backup do SQLite copia o banco com segurança mesmo em uso.
        copia = os.path.join(temporaria, NOME_BANCO_NO_ZIP)
        origem = sqlite3.connect(config["BANCO"])
        alvo = sqlite3.connect(copia)
        try:
            origem.backup(alvo)
        finally:
            alvo.close()
            origem.close()
        with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
            arquivo_zip.write(copia, NOME_BANCO_NO_ZIP)
    os.replace(parcial, destino)

    antigos = sorted(glob.glob(os.path.join(pasta_backups, "backup-*.zip")))
    for velho in antigos[: max(0, len(antigos) - max(1, config["BACKUP_MANTER"]))]:
        os.remove(velho)

    log.info("Backup criado: %s", destino)
    return destino


def restaurar_backup(config, caminho_zip):
    """Substitui o banco pelo do backup. O banco atual vai para dados/antes-da-restauracao-<data>/.

    Pare o serviço antes de restaurar.
    """
    with zipfile.ZipFile(caminho_zip) as arquivo_zip:
        if arquivo_zip.namelist() != [NOME_BANCO_NO_ZIP]:
            raise ValueError("Este arquivo não é um backup da Comanda.")
        guardados = os.path.join(config["PASTA_DADOS"], f"antes-da-restauracao-{datetime.now():%Y%m%d-%H%M%S}")
        os.makedirs(guardados)
        for sufixo in ("", "-wal", "-shm"):
            if os.path.exists(config["BANCO"] + sufixo):
                shutil.move(config["BANCO"] + sufixo, guardados)
        with arquivo_zip.open(NOME_BANCO_NO_ZIP) as origem, open(config["BANCO"], "wb") as saida:
            shutil.copyfileobj(origem, saida)
    log.info("Backup restaurado de %s (dados anteriores em %s)", caminho_zip, guardados)
    return guardados


def fez_backup_hoje(config):
    hoje = f"backup-{datetime.now():%Y%m%d}-"
    return any(
        os.path.basename(c).startswith(hoje) for c in glob.glob(os.path.join(config["PASTA_BACKUPS"], "backup-*.zip"))
    )

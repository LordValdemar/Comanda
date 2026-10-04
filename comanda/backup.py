"""Backup e restauração do banco em um único .zip.

As regras e o trabalho com os arquivos vêm do núcleo (src/domain/backup.py e src/infrastructure/backup.py).
"""

from datetime import datetime

from src.domain.backup import FormatoDoBackup
from src.infrastructure.backup import Backups

__all__ = ["NOME_BANCO_NO_ZIP", "criar_backup", "fez_backup_hoje", "restaurar_backup"]

NOME_BANCO_NO_ZIP = "comanda.sqlite3"
FORMATO = FormatoDoBackup(NOME_BANCO_NO_ZIP, com_midia=False, sistema="da Comanda")


def _backups(config):
    return Backups(FORMATO, config["BANCO"], config["PASTA_BACKUPS"], config["PASTA_DADOS"])


def criar_backup(config):
    """Gera dados/backups/backup-AAAAMMDD-HHMMSS.zip e apaga os mais antigos."""
    return _backups(config).criar(datetime.now(), config["BACKUP_MANTER"])


def restaurar_backup(config, caminho_zip):
    """Substitui o banco pelo do backup. O banco atual vai para dados/antes-da-restauracao-<data>/.

    Pare o serviço antes de restaurar.
    """
    return _backups(config).restaurar(caminho_zip, datetime.now())


def fez_backup_hoje(config):
    return _backups(config).feito_no_dia(datetime.now().date())

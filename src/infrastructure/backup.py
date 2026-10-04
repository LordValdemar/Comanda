"""Backup e restauração (banco e, no Painel, os arquivos de mídia) em um único .zip."""

import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime

from src.domain.backup import FormatoDoBackup, a_apagar, feito_no_dia, nome_do_backup

log = logging.getLogger("backup")


class Backups:
    def __init__(self, formato: FormatoDoBackup, banco: str, pasta_backups: str, pasta_dados: str,
                 pasta_midia: str | None = None) -> None:
        self._formato = formato
        self._banco = banco
        self._pasta_backups = pasta_backups
        self._pasta_dados = pasta_dados
        self._pasta_midia = pasta_midia

    def _existentes(self) -> list[str]:
        return os.listdir(self._pasta_backups) if os.path.isdir(self._pasta_backups) else []

    def criar(self, agora: datetime, manter: int) -> str:
        """Gera backups/backup-AAAAMMDD-HHMMSS.zip e apaga os mais antigos."""
        os.makedirs(self._pasta_backups, exist_ok=True)
        destino = os.path.join(self._pasta_backups, nome_do_backup(agora))
        parcial = destino + ".parcial"
        with tempfile.TemporaryDirectory() as temporaria:
            # A API de backup do SQLite copia o banco com segurança mesmo em uso.
            copia = os.path.join(temporaria, self._formato.banco_no_zip)
            origem, alvo = sqlite3.connect(self._banco), sqlite3.connect(copia)
            try:
                origem.backup(alvo)
            finally:
                alvo.close()
                origem.close()
            with zipfile.ZipFile(parcial, "w", zipfile.ZIP_DEFLATED) as arquivo_zip:
                arquivo_zip.write(copia, self._formato.banco_no_zip)
                if self._formato.com_midia and self._pasta_midia and os.path.isdir(self._pasta_midia):
                    for nome in sorted(os.listdir(self._pasta_midia)):
                        caminho = os.path.join(self._pasta_midia, nome)
                        if os.path.isfile(caminho):
                            # Imagens e vídeos já são comprimidos: guardar sem recomprimir.
                            arquivo_zip.write(caminho, "midia/" + nome, compress_type=zipfile.ZIP_STORED)
        os.replace(parcial, destino)
        for velho in a_apagar(self._existentes(), manter):
            os.remove(os.path.join(self._pasta_backups, velho))
        log.info("Backup criado: %s", destino)
        return destino

    def restaurar(self, caminho_zip: str, agora: datetime) -> str:
        """Substitui o banco (e a mídia) pelo conteúdo do backup.

        Os dados atuais são movidos para dados/antes-da-restauracao-<data>/, para nada ser perdido.
        Pare o servidor antes de restaurar.
        """
        with zipfile.ZipFile(caminho_zip) as arquivo_zip:
            nomes = arquivo_zip.namelist()
            self._formato.conferir(nomes)
            guardados = os.path.join(self._pasta_dados, f"antes-da-restauracao-{agora:%Y%m%d-%H%M%S}")
            os.makedirs(guardados)
            for sufixo in ("", "-wal", "-shm"):
                if os.path.exists(self._banco + sufixo):
                    shutil.move(self._banco + sufixo, guardados)
            if self._formato.com_midia and self._pasta_midia:
                if os.path.exists(self._pasta_midia):
                    shutil.move(self._pasta_midia, os.path.join(guardados, "midia"))
                os.makedirs(self._pasta_midia)
            for nome in nomes:
                midia = self._formato.destino_da_midia(nome)
                if nome == self._formato.banco_no_zip:
                    destino = self._banco
                elif midia is not None and self._pasta_midia:
                    destino = os.path.join(self._pasta_midia, midia)
                else:
                    continue   # a pasta "midia/" em si
                with arquivo_zip.open(nome) as origem, open(destino, "wb") as saida:
                    shutil.copyfileobj(origem, saida)
        log.info("Backup restaurado de %s (dados anteriores em %s)", caminho_zip, guardados)
        return guardados

    def feito_no_dia(self, dia: date) -> bool:
        return feito_no_dia(self._existentes(), dia)

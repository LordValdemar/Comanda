"""Regras do backup: nome dos arquivos, quantos guardar e o que um .zip de backup pode conter."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from .erros import ErroDeDominio

PREFIXO = "backup-"
PASTA_MIDIA_NO_ZIP = "midia/"


class BackupInvalido(ErroDeDominio):
    pass


def nome_do_backup(momento: datetime) -> str:
    return f"{PREFIXO}{momento:%Y%m%d-%H%M%S}.zip"


def a_apagar(existentes: Iterable[str], manter: int) -> list[str]:
    """Os mais antigos, além dos `manter` mais novos (o recém-criado sempre fica)."""
    backups = sorted(n for n in existentes if n.startswith(PREFIXO) and n.endswith(".zip"))
    return backups[: max(0, len(backups) - max(1, manter))]


def feito_no_dia(existentes: Iterable[str], dia: date) -> bool:
    return any(n.startswith(f"{PREFIXO}{dia:%Y%m%d}-") and n.endswith(".zip") for n in existentes)


@dataclass(frozen=True)
class FormatoDoBackup:
    """O que vai no .zip: o banco e, no Painel, os arquivos de mídia (numa pasta só, sem subpastas)."""

    banco_no_zip: str
    com_midia: bool
    sistema: str   # com o artigo, para as mensagens: "do Painel de Propagandas", "da Comanda"

    def destino_da_midia(self, nome: str) -> str | None:
        """O nome do arquivo de mídia, ou None se `nome` não é um arquivo de mídia aceitável."""
        if not self.com_midia or not nome.startswith(PASTA_MIDIA_NO_ZIP):
            return None
        resto = nome[len(PASTA_MIDIA_NO_ZIP):]
        # Bloqueia caminhos maliciosos como "midia/../../etc/passwd" e arquivos ocultos.
        if not resto or "/" in resto or "\\" in resto or resto.startswith("."):
            return None
        return resto

    def conferir(self, nomes: list[str]) -> None:
        if self.banco_no_zip not in nomes:
            raise BackupInvalido(f"Este arquivo não é um backup {self.sistema}.")
        for nome in nomes:
            if nome == self.banco_no_zip or (self.com_midia and nome == PASTA_MIDIA_NO_ZIP):
                continue
            if self.destino_da_midia(nome) is None:
                raise BackupInvalido(f"Backup com conteúdo inesperado: {nome}")

"""Tarefa em segundo plano: backup diário do banco."""

import logging
import threading
import time

from . import backup

log = logging.getLogger("comanda.tarefas")

INTERVALO = 3600  # confere uma vez por hora se o backup do dia já foi feito


def manutencao(config):
    if config["BACKUP_MANTER"] > 0 and not backup.fez_backup_hoje(config):
        backup.criar_backup(config)


def iniciar_tarefas(app):
    def rodar():
        while True:
            try:
                manutencao(app.config)
            except Exception:
                log.exception("Falha no backup automático")
            time.sleep(INTERVALO)

    linha = threading.Thread(target=rodar, name="tarefas", daemon=True)
    linha.start()
    return linha

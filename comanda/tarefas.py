"""Tarefas em segundo plano: fechar o ponto de quem passou do horário e backup diário do banco."""

import logging
import threading
import time

from . import backup, ponto

log = logging.getLogger("comanda.tarefas")

INTERVALO = 60              # o ponto é conferido a cada minuto
INTERVALO_BACKUP = 3600     # e o backup do dia, uma vez por hora


def manutencao(config):
    if config["BACKUP_MANTER"] > 0 and not backup.fez_backup_hoje(config):
        backup.criar_backup(config)


def iniciar_tarefas(app):
    def rodar():
        ultimo_backup = None
        while True:
            with app.app_context():
                try:
                    ponto.fechar_fora_do_horario()
                except Exception:
                    log.exception("Falha ao fechar os pontos fora do horário")
            if ultimo_backup is None or time.monotonic() - ultimo_backup >= INTERVALO_BACKUP:
                ultimo_backup = time.monotonic()
                try:
                    manutencao(app.config)
                except Exception:
                    log.exception("Falha no backup automático")
            time.sleep(INTERVALO)

    linha = threading.Thread(target=rodar, name="tarefas", daemon=True)
    linha.start()
    return linha

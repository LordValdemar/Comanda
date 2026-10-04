"""Dinheiro (centavos ↔ texto) e datas (UTC no banco ↔ horário local na tela)."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

# Dinheiro: as regras são do núcleo (src/domain/dinheiro.py); os nomes seguem valendo daqui.
from src.domain.dinheiro import ValorInvalido, entrada_reais, ler_reais, porcentagem, reais  # noqa: F401

FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"  # o mesmo do CURRENT_TIMESTAMP do SQLite (UTC)


def fuso():
    return ZoneInfo(current_app.config["FUSO_HORARIO"])


def agora_utc():
    return datetime.now(timezone.utc)


def para_texto_utc(momento):
    return momento.astimezone(timezone.utc).strftime(FORMATO_BANCO)


def de_texto_utc(texto):
    return datetime.strptime(texto, FORMATO_BANCO).replace(tzinfo=timezone.utc)


def hoje_local():
    return agora_utc().astimezone(fuso()).date()


def intervalo_utc(inicio, fim):
    """Dias locais [inicio, fim] (datas) → par de textos UTC [de, ate) para filtrar no banco."""
    zona = fuso()
    de = datetime.combine(inicio, time.min, zona)
    ate = datetime.combine(fim + timedelta(days=1), time.min, zona)
    return para_texto_utc(de), para_texto_utc(ate)


def data_hora(texto, formato="%d/%m/%Y %H:%M"):
    """Filtro de template: texto UTC do banco → horário local."""
    if not texto:
        return ""
    return de_texto_utc(texto).astimezone(fuso()).strftime(formato)


MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")


def data_extenso(texto):
    """Texto UTC do banco → "04 de outubro de 2026" (horário local)."""
    if not texto:
        return ""
    momento = de_texto_utc(texto).astimezone(fuso())
    return f"{momento.day:02d} de {MESES[momento.month - 1]} de {momento.year}"


def hora(texto):
    return data_hora(texto, "%H:%M")


def minutos_desde(texto):
    if not texto:
        return 0
    return max(0, int((agora_utc() - de_texto_utc(texto)).total_seconds() // 60))

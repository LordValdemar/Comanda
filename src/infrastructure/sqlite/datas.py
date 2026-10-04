"""Datas no banco: texto UTC "AAAA-MM-DD HH:MM:SS", o mesmo do CURRENT_TIMESTAMP do SQLite."""

from datetime import datetime, timezone

FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"


def para_texto(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(FORMATO_BANCO)


def de_texto(texto: str | None) -> datetime | None:
    return datetime.strptime(texto, FORMATO_BANCO).replace(tzinfo=timezone.utc) if texto else None

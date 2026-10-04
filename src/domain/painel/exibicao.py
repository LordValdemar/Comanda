"""Registros de exibição que a TV manda (o que passou, quando e por quanto tempo)."""

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_REGISTROS_POR_ENVIO = 1000
MAX_DURACAO_REGISTRO = 86400


@dataclass(frozen=True)
class Exibicao:
    propaganda_id: int
    inicio: datetime   # UTC
    duracao: float


def ler_registro(registro: object, agora: datetime, mais_antigo: datetime) -> Exibicao | None:
    """Confere um registro enviado pela TV; o que não fizer sentido é ignorado (None)."""
    if not isinstance(registro, dict):
        return None
    try:
        propaganda_id = int(registro["propaganda_id"])
        duracao = float(registro["duracao"])
        inicio = datetime.fromisoformat(str(registro["inicio"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if inicio.tzinfo is None or not 0 < duracao <= MAX_DURACAO_REGISTRO:
        return None
    if not mais_antigo <= inicio <= agora + timedelta(hours=1):  # relógio da TV muito errado
        return None
    return Exibicao(propaganda_id, inicio, round(duracao, 1))

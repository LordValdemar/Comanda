"""Liberações por QR code (ou código digitado): alguém que pode libera quem precisa de autorização.

O código vale 2 minutos e uma leitura só. Lido, vira uma liberação que vale uma vez,
por um tempo ou sem prazo (até alguém encerrar), e fica guardado quem autorizou quem.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..erros import ErroDeDominio

CODIGO_SEGUNDOS = 120        # o QR code de autorização vale 2 minutos e uma leitura só
LIBERADO_MINUTOS = 5         # tempo sugerido quando quem autoriza escolhe "por um tempo"
MAX_MINUTOS = 12 * 60        # "por um tempo" vai até 12 horas (mais que isso, use "sem prazo")
GUARDAR_DIAS = 90            # histórico de autorizações (as "sem prazo" ainda valendo ficam)
# Como fica a liberação depois que a pessoa lê o QR: uma ação, alguns minutos ou até alguém encerrar.
MODOS: dict[str, str] = {"uma": "Uma vez só", "minutos": "Por um tempo", "sempre": "Sem prazo (até encerrar)"}
LETRAS_DO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I/L: fácil de digitar
TAMANHO_DO_CODIGO = 8


class ErroDeAutorizacao(ErroDeDominio):
    """O código não pôde ser usado (a mensagem diz por quê)."""


class CodigoInvalido(ErroDeAutorizacao):
    def __init__(self) -> None:
        super().__init__("Este código de autorização não vale (já foi usado ou foi trocado). Peça um novo.")


class CodigoVencido(ErroDeAutorizacao):
    def __init__(self) -> None:
        super().__init__("Este código de autorização venceu. Peça um novo.")


class CodigoJaUsado(ErroDeAutorizacao):
    def __init__(self) -> None:
        super().__init__("Este código de autorização já foi usado. Peça um novo.")


def gerar_codigo() -> str:
    return "".join(secrets.choice(LETRAS_DO_CODIGO) for _ in range(TAMANHO_DO_CODIGO))


def normalizar_codigo(texto: str | None) -> str:
    """O que a pessoa digitou → só as letras que existem nos códigos, em maiúsculas."""
    return "".join(c for c in (texto or "").upper() if c in LETRAS_DO_CODIGO)[:TAMANHO_DO_CODIGO]


def ler_minutos(texto: str | int | None) -> int:
    try:
        return max(1, min(MAX_MINUTOS, int(texto)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LIBERADO_MINUTOS


def descrever(modo: str, minutos: int) -> str:
    """'uma vez', 'por 30 minutos', 'por 2 horas', 'sem prazo'."""
    if modo == "uma":
        return "uma vez"
    if modo == "sempre":
        return "sem prazo"
    if minutos % 60 == 0:
        return f"por {minutos // 60} hora{'s' if minutos >= 120 else ''}"
    return f"por {minutos} minutos"


@dataclass(frozen=True)
class Liberacao:
    """Um código de autorização e, depois de lido, a liberação que ele deu."""

    id: int
    codigo: str
    funcao: str
    modo: str
    minutos: int
    criado_em: datetime
    autorizado_por: int | None = None
    quem_autorizou: str | None = None
    usado_por: int | None = None
    quem_usou: str | None = None
    usado_em: datetime | None = None
    ate: datetime | None = None
    consumida_em: datetime | None = None
    revogada_em: datetime | None = None

    @property
    def descricao(self) -> str:
        return descrever(self.modo, self.minutos)

    @property
    def uma_vez(self) -> bool:
        return self.modo == "uma"

    @property
    def usado(self) -> bool:
        return self.usado_em is not None

    def vencido(self, agora: datetime) -> bool:
        """O código (ainda não lido) passou dos 2 minutos."""
        return (agora - self.criado_em).total_seconds() > CODIGO_SEGUNDOS

    def vale(self, agora: datetime) -> bool:
        """A liberação ainda vale (lida, não encerrada, não gasta e dentro do prazo)."""
        if not self.usado or self.revogada_em is not None or self.consumida_em is not None:
            return False
        return self.modo != "minutos" or (self.ate is not None and self.ate > agora)

    def prazo_ao_usar(self, agora: datetime) -> datetime | None:
        return agora + timedelta(minutes=self.minutos) if self.modo == "minutos" else None

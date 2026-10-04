"""Limites do plano de cada empresa: número de telas e armazenamento."""

from dataclasses import dataclass

MB = 1024 * 1024


@dataclass(frozen=True)
class Uso:
    telas: int
    bytes: int

    @property
    def mb(self) -> float:
        return self.bytes / MB


@dataclass(frozen=True)
class Limites:
    """None = sem limite."""

    telas: int | None
    mb: int | None

    def cabe_mais_uma_tela(self, uso: Uso) -> bool:
        return self.telas is None or uso.telas < self.telas

    def cabe_no_armazenamento(self, uso: Uso, bytes_novos: int) -> bool:
        return self.mb is None or uso.bytes + bytes_novos <= self.mb * MB

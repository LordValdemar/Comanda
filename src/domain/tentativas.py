"""Limite de tentativas erradas por pessoa (contra quem tenta adivinhar um código)."""

import time
from collections.abc import Callable, Hashable


class LimiteDeTentativas:
    def __init__(self, maximo: int, janela_segundos: float, relogio: Callable[[], float] = time.time) -> None:
        self.maximo = maximo
        self.janela = janela_segundos
        self._relogio = relogio
        self._erros: dict[Hashable, list[float]] = {}

    def _recentes(self, chave: Hashable) -> list[float]:
        agora = self._relogio()
        return [t for t in self._erros.get(chave, []) if agora - t < self.janela]

    def errou(self, chave: Hashable) -> None:
        self._erros[chave] = [*self._recentes(chave), self._relogio()]

    def bloqueado(self, chave: Hashable) -> bool:
        return len(self._recentes(chave)) >= self.maximo

    def clear(self) -> None:
        self._erros.clear()

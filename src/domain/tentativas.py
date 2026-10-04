"""Limite de tentativas erradas (senha, código de 2FA, código do ponto), contra quem tenta adivinhar."""

import threading
import time
from collections.abc import Callable, Hashable


class LimiteDeTentativas:
    """`maximo` erros dentro de `janela_segundos` bloqueiam a chave (um IP, uma pessoa). Seguro entre threads."""

    def __init__(self, maximo: int, janela_segundos: float, relogio: Callable[[], float] = time.monotonic) -> None:
        self.maximo = maximo
        self.janela = janela_segundos
        self._relogio = relogio
        self._erros: dict[Hashable, list[float]] = {}
        self._trava = threading.Lock()

    def _recentes(self, chave: Hashable) -> list[float]:
        agora = self._relogio()
        recentes = [t for t in self._erros.get(chave, []) if agora - t < self.janela]
        if recentes:
            self._erros[chave] = recentes
        else:
            self._erros.pop(chave, None)   # não guarda chave velha para sempre
        return recentes

    def errou(self, chave: Hashable) -> None:
        with self._trava:
            self._erros[chave] = [*self._recentes(chave), self._relogio()]

    def bloqueado(self, chave: Hashable) -> bool:
        with self._trava:
            return len(self._recentes(chave)) >= self.maximo

    def acertou(self, chave: Hashable) -> None:
        with self._trava:
            self._erros.pop(chave, None)

    def clear(self) -> None:
        with self._trava:
            self._erros.clear()

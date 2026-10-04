"""Período de datas digitado (relatórios, histórico, ponto): datas inválidas viram o padrão, ao contrário se desinverte."""

from dataclasses import dataclass
from datetime import date, timedelta


def _data(texto: str | None, padrao: date) -> date:
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return padrao


@dataclass(frozen=True)
class Periodo:
    inicio: date
    fim: date

    @classmethod
    def ler(cls, de: str | None, ate: str | None, padrao_inicio: date, padrao_fim: date,
            max_dias: int | None = None) -> "Periodo":
        """`max_dias`: o período mais longo aceito (o início anda para perto do fim)."""
        inicio, fim = _data(de, padrao_inicio), _data(ate, padrao_fim)
        if fim < inicio:
            inicio, fim = fim, inicio
        if max_dias is not None and (fim - inicio).days >= max_dias:
            inicio = fim - timedelta(days=max_dias - 1)
        return cls(inicio, fim)

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1

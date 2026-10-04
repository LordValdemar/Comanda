"""Relatório de exibições do Painel (prova de que a propaganda passou): por propaganda, por tela e por dia."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

DIAS_PADRAO = 7
CABECALHO = ["Data", "Tela", "Propaganda", "Exibições", "Tempo total (segundos)"]


def inicio_da_retencao(agora: datetime, dias: int) -> datetime:
    """Exibições de antes disto são apagadas (o histórico guardado é de `dias` dias)."""
    return agora - timedelta(days=dias)


@dataclass(frozen=True)
class ExibicoesDaPropaganda:
    propaganda_id: int
    nome: str
    excluida: bool
    exibicoes: int
    tempo: float
    telas: int


@dataclass(frozen=True)
class ExibicoesDaTela:
    nome: str
    exibicoes: int
    tempo: float


@dataclass(frozen=True)
class ExibicoesDoDia:
    dia: date
    tela: str
    propaganda: str
    exibicoes: int
    tempo: float


@dataclass(frozen=True)
class ResumoDeExibicoes:
    por_propaganda: list[ExibicoesDaPropaganda] = field(default_factory=list)
    por_tela: list[ExibicoesDaTela] = field(default_factory=list)

    @property
    def total_exibicoes(self) -> int:
        return sum(p.exibicoes for p in self.por_propaganda)

    @property
    def total_tempo(self) -> float:
        return sum(p.tempo for p in self.por_propaganda)


def linhas_da_planilha(dias: list[ExibicoesDoDia]) -> list[list[object]]:
    cabecalho: list[object] = list(CABECALHO)
    return [cabecalho, *([d.dia.strftime("%d/%m/%Y"), d.tela, d.propaganda, d.exibicoes, round(d.tempo)] for d in dias)]


class RepositorioDeExibicoes(Protocol):
    """Consultas de uma loja. `de`/`ate` em texto UTC; `tela_id` None = todas."""

    def por_propaganda(self, de: str, ate: str, tela_id: int | None) -> list[ExibicoesDaPropaganda]: ...
    def por_tela(self, de: str, ate: str, tela_id: int | None) -> list[ExibicoesDaTela]: ...
    def por_dia(self, de: str, ate: str, tela_id: int | None, ajuste_minutos: int) -> list[ExibicoesDoDia]: ...


class RelatorioDeExibicoes:
    def __init__(self, repositorio: RepositorioDeExibicoes) -> None:
        self._repo = repositorio

    def resumo(self, de: str, ate: str, tela_id: int | None) -> ResumoDeExibicoes:
        return ResumoDeExibicoes(self._repo.por_propaganda(de, ate, tela_id), self._repo.por_tela(de, ate, tela_id))

    def planilha(self, de: str, ate: str, tela_id: int | None, ajuste_minutos: int) -> list[list[object]]:
        """Uma linha por dia, tela e propaganda. O dia é o local (ajuste do fuso em minutos)."""
        return linhas_da_planilha(self._repo.por_dia(de, ate, tela_id, ajuste_minutos))

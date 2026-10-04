"""Dias da semana e faixas de horário (usados pelo ponto e pela agenda das propagandas)."""

from dataclasses import dataclass
from datetime import datetime

from .erros import ErroDeDominio

DIAS = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")  # índice = datetime.weekday()
TODOS_OS_DIAS = "0123456"


class HorarioInvalido(ErroDeDominio):
    pass


def resumo_dias(dias: str | None) -> str:
    dias = dias or TODOS_OS_DIAS
    if dias == TODOS_OS_DIAS:
        return "Todos os dias"
    if dias == "01234":
        return "Seg a Sex"
    if dias == "56":
        return "Sáb e Dom"
    return ", ".join(DIAS[int(d)] for d in dias)


def resumo_horario(inicio: str | None, fim: str | None) -> str:
    if not inicio and not fim:
        return "o dia todo"
    return f"{inicio or '00:00'} às {fim or '24:00'}"


def ler_hora(valor: str | None) -> str | None:
    """'8:05' → '08:05'; vazio ou inválido → None."""
    valor = (valor or "").strip()
    try:
        return datetime.strptime(valor, "%H:%M").strftime("%H:%M") if valor else None
    except ValueError:
        return None


def ler_dias(escolhidos: list[str]) -> str:
    """As caixas marcadas → '0246' (na ordem da semana, sem repetir nem lixo)."""
    return "".join(d for d in TODOS_OS_DIAS if d in escolhidos)


@dataclass(frozen=True)
class Horario:
    """Dias de trabalho e, se houver, a faixa de horas. Sem faixa, vale o dia inteiro."""

    dias: str = TODOS_OS_DIAS
    inicio: str | None = None
    fim: str | None = None

    @classmethod
    def novo(cls, dias: str, inicio: str | None, fim: str | None) -> "Horario":
        if not dias:
            raise HorarioInvalido("escolha pelo menos um dia de trabalho.")
        if bool(inicio) != bool(fim) or (inicio and inicio == fim):
            raise HorarioInvalido("informe o horário de início e de fim (diferentes), ou deixe os dois em branco.")
        return cls(dias, inicio, fim)

    def vale(self, agora: datetime) -> bool:
        """`agora` (no fuso da loja) está dentro do horário?

        Um turno que vira a noite (ex.: 18:00 às 02:00) pertence ao dia em que começa: o
        sábado às 01:00 conta como o turno de sexta.
        """
        dias = self.dias or TODOS_OS_DIAS
        dia = str(agora.weekday())
        if not self.inicio or not self.fim:
            return dia in dias
        hora = agora.strftime("%H:%M")
        if self.inicio < self.fim:
            return dia in dias and self.inicio <= hora < self.fim
        if hora >= self.inicio:
            return dia in dias
        return hora < self.fim and str((agora.weekday() - 1) % 7) in dias

    @property
    def resumo(self) -> str:
        return f"{resumo_dias(self.dias)}, {resumo_horario(self.inicio, self.fim)}"

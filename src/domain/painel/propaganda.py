"""Propagandas: a agenda de cada uma (datas, dias, horário) e onde aparecem (telas e grupos)."""

from dataclasses import dataclass, field
from datetime import date, datetime

from ..erros import ErroDeDominio
from ..horario import TODOS_OS_DIAS
from ..ordem import trocar_com_vizinho

DURACAO_PADRAO = 10
MAX_DURACAO = 3600
MAX_NOME = 200
MAX_LETREIRO = 500
TIPOS = ("imagem", "video")


class ErroDePropaganda(ErroDeDominio):
    pass


def ler_duracao(valor: str | int | None) -> int:
    """Segundos na tela, de 1 a 3600 (o que não for número vira o padrão)."""
    try:
        return max(1, min(MAX_DURACAO, int(valor)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DURACAO_PADRAO


def ler_data(valor: str | None) -> str | None:
    """Só datas AAAA-MM-DD válidas; qualquer outra coisa vira vazio."""
    valor = (valor or "").strip()
    try:
        return date.fromisoformat(valor).isoformat() if valor else None
    except ValueError:
        return None


def ler_letreiro(modo: str | None, texto: str | None) -> str | None:
    """Letreiro durante a propaganda: None = o geral da loja, '' = nenhum, texto = próprio."""
    if modo == "nenhum":
        return ""
    if modo == "proprio":
        return (texto or "").strip()[:MAX_LETREIRO] or None
    return None


def _no_horario(hora: str, inicio: str | None, fim: str | None) -> bool:
    inicio, fim = inicio or "00:00", fim or "24:00"
    if inicio <= fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim   # faixa que vira a noite, ex.: 22:00 até 02:00


@dataclass(frozen=True)
class Destinos:
    """Telas e grupos escolhidos (vazio com "todas as telas" desligado = não aparece em lugar nenhum)."""

    telas: frozenset[int] = frozenset()
    grupos: frozenset[int] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.telas or self.grupos)

    def inclui(self, tela_id: int, grupo_id: int | None) -> bool:
        return tela_id in self.telas or (grupo_id is not None and grupo_id in self.grupos)

    def so_da_loja(self, telas: set[int], grupos: set[int]) -> "Destinos":
        """Descarta ids que não são da loja (vindos de um formulário adulterado, por exemplo)."""
        return Destinos(self.telas & telas, self.grupos & grupos)

    def combinar(self, modo: str, outros: "Destinos") -> "Destinos":
        if modo == "trocar":
            return outros
        if modo == "acrescentar":
            return Destinos(self.telas | outros.telas, self.grupos | outros.grupos)
        if modo == "tirar":
            return Destinos(self.telas - outros.telas, self.grupos - outros.grupos)
        raise ErroDePropaganda("Escolha trocar, acrescentar ou tirar.")


@dataclass(frozen=True)
class Programacao:
    """O que se edita numa propaganda (nome, tempo, agenda, destino e letreiro)."""

    nome: str
    duracao: int
    ativo: bool
    inicio: str | None
    fim: str | None
    dias_semana: str
    hora_inicio: str | None
    hora_fim: str | None
    para_todas: bool
    letreiro: str | None
    destinos: Destinos = Destinos()

    def conferir(self) -> None:
        if self.inicio and self.fim and self.fim < self.inicio:
            raise ErroDePropaganda("A data de término não pode ser antes da data de início.")
        if not self.dias_semana:
            raise ErroDePropaganda("Escolha pelo menos um dia da semana.")
        if self.hora_inicio and self.hora_fim and self.hora_inicio == self.hora_fim:
            raise ErroDePropaganda("O horário de início e de fim não podem ser iguais.")
        if not self.para_todas and not self.destinos:
            raise ErroDePropaganda("Escolha pelo menos uma tela ou grupo (ou marque “Todas as telas”).")


@dataclass(frozen=True)
class Propaganda:
    id: int
    nome: str
    arquivo: str
    tipo: str
    duracao: int
    posicao: int = 0
    tamanho: int = 0
    ativo: bool = True
    inicio: str | None = None       # AAAA-MM-DD
    fim: str | None = None
    dias_semana: str = TODOS_OS_DIAS
    hora_inicio: str | None = None  # HH:MM
    hora_fim: str | None = None
    para_todas: bool = True
    letreiro: str | None = None     # None = o geral da loja; '' = nenhum
    destinos: Destinos = field(default_factory=Destinos)

    def situacao(self, agora: datetime) -> tuple[str, str]:
        """(código, texto): está no ar agora e, se não, por quê (`agora` no fuso da loja).

        Os dias da semana valem para o dia do relógio: numa faixa 22:00-02:00 marcada só
        na sexta, a parte depois da meia-noite cai no sábado.
        """
        hoje = agora.date().isoformat()
        if not self.ativo:
            return "inativa", "Inativa"
        if self.inicio and hoje < self.inicio:
            return "agendada", "Começa em " + date.fromisoformat(self.inicio).strftime("%d/%m/%Y")
        if self.fim and hoje > self.fim:
            return "encerrada", "Encerrada"
        if str(agora.weekday()) not in (self.dias_semana or TODOS_OS_DIAS):
            return "fora_do_dia", "Fora do dia"
        if not _no_horario(agora.strftime("%H:%M"), self.hora_inicio, self.hora_fim):
            return "fora_do_horario", "Fora do horário"
        return "no_ar", "No ar agora"

    def no_ar(self, agora: datetime) -> bool:
        return self.situacao(agora)[0] == "no_ar"

    def aparece_na(self, tela_id: int | None, grupo_id: int | None) -> bool:
        """Vai para esta tela? (tela None = o player geral, que mostra só as "para todas")."""
        return self.para_todas or (tela_id is not None and self.destinos.inclui(tela_id, grupo_id))


def nova_ordem(ids: list[int], propaganda_id: int, direcao: str) -> list[int] | None:
    """A lista com a propaganda um lugar acima ou abaixo (None se já está na ponta)."""
    if direcao not in ("cima", "baixo"):
        raise ErroDePropaganda("Direção inválida.")
    return trocar_com_vizinho(ids, propaganda_id, para_cima=direcao == "cima")

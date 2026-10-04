"""Relatório de vendas da Comanda: resumo do período e a planilha das contas encerradas."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ..comanda.entidades import FORMAS_DE_PAGAMENTO
from ..dinheiro import entrada_reais, porcentagem

MAX_DIAS = 366
CABECALHO = ["comanda", "mesa", "cliente", "garçom", "situação", "aberta em", "fechada em", "desconto", "total", "pagamentos"]


def taxa_da_comanda(taxa_gravada: int | None, cobrar: bool, percentual: float, subtotal: int) -> int:
    """A taxa de serviço (o que vai para a equipe): a gravada no fechamento, igual à do cupom.
    Comandas fechadas antes dessa gravação existir são recalculadas a partir dos itens."""
    if taxa_gravada is not None:
        return taxa_gravada
    return porcentagem(subtotal, percentual) if cobrar else 0


@dataclass(frozen=True)
class VendaPorForma:
    forma: str
    quantidade: int
    valor: int


@dataclass(frozen=True)
class VendaPorProduto:
    nome: str
    quantidade: int
    valor: int


@dataclass(frozen=True)
class VendaPorGarcom:
    garcom: str
    valor: int


@dataclass(frozen=True)
class ItemCancelado:
    comanda_id: int
    numero: int
    nome: str
    quantidade: int
    motivo_cancelamento: str | None
    cancelado_por_nome: str | None
    atualizado_em: str


@dataclass(frozen=True)
class TaxaDaComanda:
    taxa_gravada: int | None
    cobrar: bool
    percentual: float
    subtotal: int


@dataclass(frozen=True)
class ResumoDeVendas:
    comandas: int = 0
    faturamento: int = 0
    descontos: int = 0
    taxa: int = 0
    abertas: int = 0
    formas: list[VendaPorForma] = field(default_factory=list)
    produtos: list[VendaPorProduto] = field(default_factory=list)
    cancelados: list[ItemCancelado] = field(default_factory=list)
    garcons: list[VendaPorGarcom] = field(default_factory=list)

    @property
    def ticket_medio(self) -> int:
        return self.faturamento // self.comandas if self.comandas else 0


@dataclass(frozen=True)
class ComandaEncerrada:
    """Uma linha da planilha: comanda fechada ou cancelada no período."""

    numero: int
    mesa: str | None
    cliente: str | None
    garcom: str | None
    status: str
    aberta_em: str
    fechada_em: str | None
    desconto: int
    total: int | None
    pagamentos: list[tuple[str, int]]
    motivo_cancelamento: str | None


def linhas_da_planilha(comandas: list[ComandaEncerrada], data_hora: Callable[[str | None], str]) -> list[list[object]]:
    """As linhas do CSV (valores com vírgula decimal: abre direto no Excel em português)."""
    linhas: list[list[object]] = []
    for c in comandas:
        pagamentos = " ".join(f"{FORMAS_DE_PAGAMENTO.get(forma, forma)} {entrada_reais(valor)}" for forma, valor in c.pagamentos)
        linhas.append([
            c.numero, c.mesa or "", c.cliente or "", c.garcom or "", c.status, data_hora(c.aberta_em),
            data_hora(c.fechada_em), entrada_reais(c.desconto), entrada_reais(c.total or 0),
            pagamentos if c.status == "fechada" else (c.motivo_cancelamento or ""),
        ])
    return linhas


class RepositorioDeVendas(Protocol):
    """Consultas de uma loja. `de` e `ate` são os textos UTC do banco (o fim não entra)."""

    def totais(self, de: str, ate: str) -> tuple[int, int, int]: ...   # (comandas fechadas, faturamento, descontos)
    def taxas(self, de: str, ate: str) -> list[TaxaDaComanda]: ...
    def por_forma(self, de: str, ate: str) -> list[VendaPorForma]: ...
    def por_produto(self, de: str, ate: str) -> list[VendaPorProduto]: ...
    def por_garcom(self, de: str, ate: str) -> list[VendaPorGarcom]: ...
    def cancelados(self, de: str, ate: str) -> list[ItemCancelado]: ...
    def abertas(self) -> int: ...
    def encerradas(self, de: str, ate: str) -> list[ComandaEncerrada]: ...


class RelatorioDeVendas:
    def __init__(self, repositorio: RepositorioDeVendas) -> None:
        self._repo = repositorio

    def resumo(self, de: str, ate: str) -> ResumoDeVendas:
        comandas, faturamento, descontos = self._repo.totais(de, ate)
        taxa = sum(taxa_da_comanda(t.taxa_gravada, t.cobrar, t.percentual, t.subtotal) for t in self._repo.taxas(de, ate))
        return ResumoDeVendas(
            comandas=comandas, faturamento=faturamento, descontos=descontos, taxa=taxa, abertas=self._repo.abertas(),
            formas=self._repo.por_forma(de, ate), produtos=self._repo.por_produto(de, ate),
            cancelados=self._repo.cancelados(de, ate), garcons=self._repo.por_garcom(de, ate),
        )

    def planilha(self, de: str, ate: str, data_hora: Callable[[str | None], str]) -> list[list[object]]:
        cabecalho: list[object] = list(CABECALHO)
        return [cabecalho, *linhas_da_planilha(self._repo.encerradas(de, ate), data_hora)]

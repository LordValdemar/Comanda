"""Entidades da Comanda e as regras de negócio (puras: sem banco, sem Flask).

Dinheiro sempre em centavos (int). A comanda carregada traz seus itens e pagamentos; as
contas (subtotal, taxa, total, troco...) e as validações saem daqui, e quem grava é o repositório.
"""

from dataclasses import dataclass, field

from ..dinheiro import porcentagem, reais
from .erros import ErroComanda

FORMAS_DE_PAGAMENTO: dict[str, str] = {
    "dinheiro": "Dinheiro", "pix": "PIX", "debito": "Cartão de débito", "credito": "Cartão de crédito", "outro": "Outro",
}
SITUACOES_DO_ITEM: dict[str, str] = {
    "pendente": "Aguardando", "preparando": "Preparando", "pronto": "Pronto", "entregue": "Entregue", "cancelado": "Cancelado",
}
# Situações que a cozinha e o garçom escolhem (cancelar é outra operação, com motivo).
ANDAMENTO = ("pendente", "preparando", "pronto", "entregue")
NA_COZINHA = ("pendente", "preparando", "pronto")
MAX_QUANTIDADE = 999
MAX_NUMERO = 99999
MAX_TAXA_PERCENTUAL = 30.0
MAX_MOTIVO = 120
MAX_OBSERVACAO = 120
MAX_MESA = 20
MAX_CLIENTE = 60
MAIOR_CEDULA = 20000  # R$ 200,00: ninguém entrega uma nota inteira a mais, então o troco é sempre menor


@dataclass(frozen=True)
class Ator:
    """Quem faz a operação (para o histórico): o usuário e, se foi com autorização por QR, quem autorizou."""

    usuario_id: int | None
    autorizado_por: str | None = None

    def anotar(self, detalhe: str) -> str:
        """O detalhe do histórico, com "(autorizado por X)" quando foi com autorização."""
        if not self.autorizado_por:
            return detalhe
        return f"{detalhe} (autorizado por {self.autorizado_por})" if detalhe else f"autorizado por {self.autorizado_por}"


@dataclass(frozen=True)
class Item:
    id: int
    nome: str
    preco_centavos: int
    quantidade: int
    status: str
    vai_cozinha: bool

    @property
    def valor(self) -> int:
        return self.preco_centavos * self.quantidade

    @property
    def cancelado(self) -> bool:
        return self.status == "cancelado"

    @property
    def cozinha_comecou(self) -> bool:
        """A cozinha já mexeu nele: só quem tem a permissão "Cancelar" pode desfazer."""
        return self.vai_cozinha and self.status not in ("pendente", "cancelado")


@dataclass(frozen=True)
class Pagamento:
    id: int
    forma: str
    valor_centavos: int       # o que abateu da conta
    recebido_centavos: int    # o que o cliente entregou (em dinheiro, pode ser mais: a diferença é troco)

    @property
    def troco(self) -> int:
        return self.recebido_centavos - self.valor_centavos

    @property
    def nome_da_forma(self) -> str:
        return FORMAS_DE_PAGAMENTO.get(self.forma, self.forma)


@dataclass(frozen=True)
class Totais:
    subtotal: int
    taxa: int
    desconto: int
    total: int
    pago: int
    troco: int

    @property
    def restante(self) -> int:
        return self.total - self.pago


@dataclass(frozen=True)
class NovoPagamento:
    """Pagamento conferido, pronto para gravar."""

    forma: str
    valor_centavos: int
    recebido_centavos: int

    @property
    def troco(self) -> int:
        return self.recebido_centavos - self.valor_centavos


@dataclass
class Comanda:
    id: int
    empresa_id: int
    numero: int
    status: str
    taxa_percentual: float
    cobrar_taxa: bool
    desconto_centavos: int
    total_centavos: int | None = None
    garcom_id: int | None = None
    itens: list[Item] = field(default_factory=list)
    pagamentos: list[Pagamento] = field(default_factory=list)

    # -- contas -------------------------------------------------------------

    def calcular_totais(self, cobrar_taxa: bool | None = None, desconto: int | None = None) -> Totais:
        """As contas da comanda (ou como ficariam com outra taxa/desconto, para conferir um ajuste)."""
        cobrar = self.cobrar_taxa if cobrar_taxa is None else cobrar_taxa
        subtotal = sum(item.valor for item in self.itens if not item.cancelado)
        taxa = porcentagem(subtotal, self.taxa_percentual) if cobrar else 0
        desconto_aplicado = min(self.desconto_centavos if desconto is None else desconto, subtotal + taxa)
        return Totais(
            subtotal=subtotal,
            taxa=taxa,
            desconto=desconto_aplicado,
            total=subtotal + taxa - desconto_aplicado,
            pago=sum(p.valor_centavos for p in self.pagamentos),
            troco=sum(p.troco for p in self.pagamentos),
        )

    @property
    def totais(self) -> Totais:
        return self.calcular_totais()

    # -- regras ---------------------------------------------------------------

    @property
    def aberta(self) -> bool:
        return self.status == "aberta"

    def garantir_aberta(self, mensagem: str = "Esta comanda já foi fechada.") -> None:
        if not self.aberta:
            raise ErroComanda(mensagem)

    def item(self, item_id: int) -> Item | None:
        return next((i for i in self.itens if i.id == item_id), None)

    def conferir_pagamento(self, forma: str, valor: int) -> NovoPagamento:
        """Abate `valor` da conta. Em dinheiro, o que passar do restante vira troco."""
        self.garantir_aberta()
        if forma not in FORMAS_DE_PAGAMENTO:
            raise ErroComanda("Forma de pagamento inválida.")
        if valor <= 0:
            raise ErroComanda("Informe o valor do pagamento.")
        restante = self.totais.restante
        if restante <= 0:
            raise ErroComanda("Esta conta já está paga.")
        if valor > restante and forma != "dinheiro":
            raise ErroComanda(f"O valor passa do que falta pagar ({reais(restante)}). Só pagamento em dinheiro tem troco.")
        if valor - restante >= MAIOR_CEDULA:
            raise ErroComanda(f"Troco de {reais(valor - restante)}? Confira o valor recebido (falta pagar {reais(restante)}).")
        return NovoPagamento(forma=forma, valor_centavos=min(valor, restante), recebido_centavos=valor)

    def conferir_fechamento(self) -> Totais:
        """Só fecha com a conta paga, nem mais nem menos."""
        self.garantir_aberta()
        totais = self.totais
        if totais.restante > 0:
            raise ErroComanda(f"Ainda falta receber {reais(totais.restante)}.")
        if totais.restante < 0:
            raise ErroComanda("Os pagamentos passam do total (o desconto mudou?). Remova um pagamento e lance de novo.")
        return totais

    def conferir_ajuste(self, cobrar_taxa: bool, desconto: int) -> None:
        self.garantir_aberta()
        if desconto < 0:
            raise ErroComanda("O desconto não pode ser negativo.")
        totais = self.calcular_totais(cobrar_taxa=cobrar_taxa, desconto=0)
        if desconto > totais.subtotal + totais.taxa:
            raise ErroComanda("O desconto não pode passar do valor da conta.")

    def conferir_cancelamento_do_item(self, item: Item, motivo: str) -> str:
        if not self.aberta:
            raise ErroComanda("A comanda já foi fechada: reabra-a para cancelar itens.")
        if item.cancelado:
            raise ErroComanda("Este item já foi cancelado.")
        return motivo_obrigatorio(motivo)

    def conferir_cancelamento(self, motivo: str) -> str:
        if not self.aberta:
            raise ErroComanda("Só dá para cancelar uma comanda aberta.")
        motivo = (motivo or "").strip()[:MAX_MOTIVO]
        if not motivo:
            raise ErroComanda("Informe o motivo do cancelamento.")
        if self.pagamentos:
            raise ErroComanda("Esta comanda tem pagamentos. Remova-os antes de cancelar.")
        return motivo

    def conferir_reabertura(self) -> None:
        if self.status != "fechada":
            raise ErroComanda("Só dá para reabrir uma comanda fechada.")


# -- regras soltas (valores digitados) ----------------------------------------

def numero_da_comanda(texto: str | int) -> int:
    try:
        numero = int(str(texto).strip())
    except ValueError:
        raise ErroComanda("Informe o número da comanda.") from None
    if not 1 <= numero <= MAX_NUMERO:
        raise ErroComanda(f"O número da comanda vai de 1 a {MAX_NUMERO}.")
    return numero


def quantidade_valida(quantidade: int) -> int:
    if not 1 <= quantidade <= MAX_QUANTIDADE:
        raise ErroComanda(f"Quantidade inválida: {quantidade}.")
    return quantidade


def motivo_obrigatorio(motivo: str | None) -> str:
    texto = (motivo or "").strip()[:MAX_MOTIVO]
    if not texto:
        raise ErroComanda("Informe o motivo do cancelamento.")
    return texto


def conferir_mudanca_de_situacao(item: Item, nova: str) -> None:
    """Andamento do item: pendente → preparando → pronto → entregue (e voltar um passo)."""
    if item.cancelado:
        raise ErroComanda("Este item foi cancelado.")
    if nova not in ANDAMENTO:
        raise ErroComanda("Situação inválida.")


def taxa_percentual_valida(texto: str | float) -> float:
    try:
        taxa = float(str(texto).replace(",", ".") or 0)
    except ValueError:
        raise ErroComanda(f"A taxa de serviço vai de 0 a {MAX_TAXA_PERCENTUAL:g}%.") from None
    if not 0 <= taxa <= MAX_TAXA_PERCENTUAL:
        raise ErroComanda(f"A taxa de serviço vai de 0 a {MAX_TAXA_PERCENTUAL:g}%.")
    return taxa

"""Planos, empresas cobradas e faturas; a regra de suspender e reativar por falta de pagamento."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..erros import ErroDeDominio

STATUS: dict[str, tuple[str, str]] = {      # status do Asaas → (texto, estilo na tela)
    "PENDING": ("Aguardando pagamento", "alerta"),
    "AWAITING_RISK_ANALYSIS": ("Em análise", "alerta"),
    "RECEIVED": ("Paga", "no-ar"),
    "CONFIRMED": ("Paga", "no-ar"),
    "RECEIVED_IN_CASH": ("Paga", "no-ar"),
    "OVERDUE": ("Vencida", "fora"),
    "REFUNDED": ("Estornada", "fora"),
    "REFUND_REQUESTED": ("Estorno solicitado", "fora"),
    "CHARGEBACK_REQUESTED": ("Contestada", "fora"),
    "CHARGEBACK_DISPUTE": ("Contestada", "fora"),
    "DELETED": ("Cancelada", ""),
}
PAGAS = frozenset({"RECEIVED", "CONFIRMED", "RECEIVED_IN_CASH"})
EM_ABERTO = frozenset({"PENDING", "OVERDUE", "AWAITING_RISK_ANALYSIS"})
INADIMPLENCIA = "inadimplencia"
MAX_NOME_DO_PLANO = 60
MAX_DESCRICAO = 200
MAX_EMAIL = 200


class ErroDeCobranca(ErroDeDominio):
    pass


class ErroNoGateway(ErroDeCobranca):
    """O Asaas recusou ou não respondeu (a mensagem vem dele, pronta para mostrar)."""


def referencia(empresa_id: int) -> str:
    """Como a empresa é identificada no Asaas (externalReference)."""
    return f"empresa:{empresa_id}"


def ler_preco(texto: str | None) -> int | None:
    """'49,90', '49.90' ou 'R$ 1.234,56' → centavos; None se não for um preço válido."""
    texto = (texto or "").strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = int((Decimal(texto) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None
    return valor if valor >= 0 else None


@dataclass(frozen=True)
class Plano:
    id: int
    nome: str
    preco_centavos: int
    limite_telas: int | None = None
    limite_mb: int | None = None
    modulos: str = "painel"       # 'painel,comanda'
    descricao: str = ""
    ativo: bool = True


@dataclass(frozen=True)
class DadosDoPlano:
    """O que se digita para criar ou mudar um plano."""

    nome: str
    preco_centavos: int | None
    limite_telas: int | None
    limite_mb: int | None
    modulos: str
    descricao: str = ""
    ativo: bool = True

    def conferido(self) -> "DadosDoPlano":
        nome = (self.nome or "").strip()[:MAX_NOME_DO_PLANO]
        if not self.modulos:
            raise ErroDeCobranca("Marque pelo menos um módulo no plano.")
        if not nome or self.preco_centavos is None:
            raise ErroDeCobranca("Informe o nome e o preço do plano (ex.: 49,90).")
        return DadosDoPlano(nome, self.preco_centavos, self.limite_telas, self.limite_mb, self.modulos,
                            (self.descricao or "").strip()[:MAX_DESCRICAO], self.ativo)


@dataclass(frozen=True)
class EmpresaCobrada:
    id: int
    nome: str
    ativa: bool = True
    motivo_suspensao: str | None = None      # 'manual' ou 'inadimplencia'
    cobranca_automatica: bool = False
    plano_id: int | None = None
    documento: str = ""
    email_cobranca: str = ""
    asaas_cliente_id: str | None = None
    asaas_assinatura_id: str | None = None

    @property
    def tem_assinatura(self) -> bool:
        return bool(self.asaas_assinatura_id)

    def decidir_inadimplencia(self, tem_fatura_atrasada: bool) -> str | None:
        """'suspender', 'reativar' ou None. Suspensão manual nunca é desfeita aqui."""
        if tem_fatura_atrasada and self.ativa and self.cobranca_automatica:
            return "suspender"
        if not tem_fatura_atrasada and not self.ativa and self.motivo_suspensao == INADIMPLENCIA:
            return "reativar"
        return None


@dataclass(frozen=True)
class Fatura:
    asaas_id: str
    valor_centavos: int
    vencimento: str                 # AAAA-MM-DD
    status: str
    link: str | None = None         # página de pagamento (sempre https)
    pago_em: str | None = None

    @property
    def em_aberto(self) -> bool:
        return self.status in EM_ABERTO

    @classmethod
    def do_gateway(cls, pagamento: Mapping[str, object]) -> "Fatura":
        """A fatura a partir do objeto 'payment' do Asaas."""
        try:
            valor = int((Decimal(str(pagamento.get("value") or 0)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            valor = 0
        pago_em = pagamento.get("clientPaymentDate") or pagamento.get("paymentDate") or pagamento.get("confirmedDate")
        status = "DELETED" if pagamento.get("deleted") else str(pagamento.get("status") or "PENDING")
        link = pagamento.get("invoiceUrl")
        if not (isinstance(link, str) and link.startswith("https://")):
            link = None  # o link vira <a href>: nunca aceitar "javascript:" ou similares
        return cls(asaas_id=str(pagamento["id"]), valor_centavos=valor, vencimento=str(pagamento.get("dueDate") or ""),
                   status=status, link=link, pago_em=str(pago_em) if pago_em else None)

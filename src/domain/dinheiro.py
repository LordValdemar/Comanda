"""Dinheiro sempre em centavos (int): sem float, sem erro de arredondamento.

Texto digitado ("1.234,56") ↔ centavos (123456) ↔ texto mostrado ("R$ 1.234,56").
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from .erros import ErroDeDominio

MAX_DIGITOS_INTEIROS = 9  # até R$ 999.999.999,99


class ValorInvalido(ErroDeDominio):
    """Valor digitado que não é um número válido."""


def reais(centavos: int | None) -> str:
    """1234567 → 'R$ 12.345,67'."""
    valor = int(centavos or 0)
    sinal = "-" if valor < 0 else ""
    inteiro, resto = divmod(abs(valor), 100)
    return f"{sinal}R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"


def entrada_reais(centavos: int | None) -> str:
    """Centavos → texto para um campo de formulário ('12,50')."""
    inteiro, resto = divmod(int(centavos or 0), 100)
    return f"{inteiro},{resto:02d}"


def ler_reais(texto: str | None, permitir_zero: bool = True) -> int:
    """'12,50', '12.50', 'R$ 1.234,5' → centavos. Texto vazio vale 0 (se permitido)."""
    limpo = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not limpo:
        if permitir_zero:
            return 0
        raise ValorInvalido("Informe um valor.")
    if "," in limpo or re.fullmatch(r"\d{1,3}(\.\d{3})+", limpo):
        limpo = limpo.replace(".", "").replace(",", ".")  # 1.234,56 ou 1.234 (formato brasileiro)
    if not re.fullmatch(rf"\d{{1,{MAX_DIGITOS_INTEIROS}}}(\.\d{{1,2}})?", limpo):
        raise ValorInvalido(f"Valor inválido: “{limpo}”. Use o formato 12,50.")
    inteiro, _, fracao = limpo.partition(".")
    centavos = int(inteiro) * 100 + int((fracao + "00")[:2])
    if centavos == 0 and not permitir_zero:
        raise ValorInvalido("O valor precisa ser maior que zero.")
    return centavos


def porcentagem(centavos: int, percentual: float | Decimal | str) -> int:
    """`percentual`% de `centavos`, arredondado como no comércio (meio centavo para cima).

    Usa Decimal: o round() do Python arredonda meio para o par (R$ 1,005 → R$ 1,00) e a
    conta com float pode errar na última casa.
    """
    valor = Decimal(int(centavos)) * Decimal(str(percentual)) / Decimal(100)
    return int(valor.quantize(Decimal(1), rounding=ROUND_HALF_UP))

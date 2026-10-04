"""Dinheiro (centavos ↔ texto) e datas (UTC no banco ↔ horário local na tela)."""

import re
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from flask import current_app

FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"  # o mesmo do CURRENT_TIMESTAMP do SQLite (UTC)


class ValorInvalido(ValueError):
    """Valor digitado que não é um número válido (mensagem pode ser mostrada na tela)."""


def reais(centavos):
    """1234567 → 'R$ 12.345,67'."""
    centavos = int(centavos or 0)
    sinal = "-" if centavos < 0 else ""
    inteiro, resto = divmod(abs(centavos), 100)
    return f"{sinal}R$ {inteiro:,}".replace(",", ".") + f",{resto:02d}"


def ler_reais(texto, permitir_zero=True):
    """'12,50', '12.50', 'R$ 1.234,5' → centavos (int). Texto vazio vale 0."""
    texto = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not texto:
        if permitir_zero:
            return 0
        raise ValorInvalido("Informe um valor.")
    if "," in texto or re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "").replace(",", ".")  # 1.234,56 ou 1.234 (formato brasileiro)
    if not re.fullmatch(r"\d{1,9}(\.\d{1,2})?", texto):
        raise ValorInvalido(f"Valor inválido: “{texto}”. Use o formato 12,50.")
    inteiro, _, fracao = texto.partition(".")
    centavos = int(inteiro) * 100 + int((fracao + "00")[:2])
    if centavos == 0 and not permitir_zero:
        raise ValorInvalido("O valor precisa ser maior que zero.")
    return centavos


def porcentagem(centavos, percentual):
    """`percentual`% de `centavos`, arredondado como no comércio (meio centavo para cima).

    Usa Decimal: o round() do Python arredonda meio para o par (R$ 1,005 → R$ 1,00) e a
    conta com float pode errar na última casa.
    """
    valor = Decimal(int(centavos)) * Decimal(str(percentual)) / Decimal(100)
    return int(valor.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def entrada_reais(centavos):
    """Centavos → texto para um campo de formulário ('12,50')."""
    inteiro, resto = divmod(int(centavos or 0), 100)
    return f"{inteiro},{resto:02d}"


def fuso():
    return ZoneInfo(current_app.config["FUSO_HORARIO"])


def agora_utc():
    return datetime.now(timezone.utc)


def para_texto_utc(momento):
    return momento.astimezone(timezone.utc).strftime(FORMATO_BANCO)


def de_texto_utc(texto):
    return datetime.strptime(texto, FORMATO_BANCO).replace(tzinfo=timezone.utc)


def hoje_local():
    return agora_utc().astimezone(fuso()).date()


def intervalo_utc(inicio, fim):
    """Dias locais [inicio, fim] (datas) → par de textos UTC [de, ate) para filtrar no banco."""
    zona = fuso()
    de = datetime.combine(inicio, time.min, zona)
    ate = datetime.combine(fim + timedelta(days=1), time.min, zona)
    return para_texto_utc(de), para_texto_utc(ate)


def data_hora(texto, formato="%d/%m/%Y %H:%M"):
    """Filtro de template: texto UTC do banco → horário local."""
    if not texto:
        return ""
    return de_texto_utc(texto).astimezone(fuso()).strftime(formato)


def hora(texto):
    return data_hora(texto, "%H:%M")


def minutos_desde(texto):
    if not texto:
        return 0
    return max(0, int((agora_utc() - de_texto_utc(texto)).total_seconds() // 60))

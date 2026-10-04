"""Verificação em duas etapas (TOTP, RFC 6238), compatível com Google Authenticator, Authy, etc."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PASSO = 30       # segundos de validade de cada código
DIGITOS = 6
TOLERANCIA = 1   # aceita o código anterior/seguinte (relógio do celular adiantado/atrasado)


def novo_segredo() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def _codigo(segredo: str, contador: int) -> str:
    chave = base64.b32decode(segredo)
    resumo = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = resumo[-1] & 0x0F
    numero = struct.unpack(">I", resumo[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10**DIGITOS).zfill(DIGITOS)


def codigo_atual(segredo: str, agora: float | None = None) -> str:
    return _codigo(segredo, int((agora or time.time()) // PASSO))


def verificar(segredo: str, codigo: str | int | None, ultimo_usado: int = 0, agora: float | None = None) -> int | None:
    """O contador do código aceito (para impedir reuso) ou None se inválido."""
    codigo = "".join(c for c in str(codigo or "") if c.isdigit())
    if len(codigo) != DIGITOS or not segredo:
        return None
    contador_atual = int((agora or time.time()) // PASSO)
    for contador in range(contador_atual - TOLERANCIA, contador_atual + TOLERANCIA + 1):
        if contador > ultimo_usado and hmac.compare_digest(_codigo(segredo, contador), codigo):
            return contador
    return None


def uri(segredo: str, usuario: str, emissor: str = "Painel de Propagandas") -> str:
    rotulo = quote(f"{emissor}:{usuario}")
    return f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor)}&digits={DIGITOS}&period={PASSO}"

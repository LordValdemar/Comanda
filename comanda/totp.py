"""Verificação em duas etapas (TOTP, RFC 6238), compatível com Google Authenticator, Authy, etc."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

import segno

PASSO = 30       # segundos de validade de cada código
DIGITOS = 6
TOLERANCIA = 1   # aceita o código anterior/seguinte (relógio do celular adiantado/atrasado)


def novo_segredo():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def _codigo(segredo, contador):
    chave = base64.b32decode(segredo)
    resumo = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = resumo[-1] & 0x0F
    numero = struct.unpack(">I", resumo[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(numero % 10**DIGITOS).zfill(DIGITOS)


def codigo_atual(segredo, agora=None):
    return _codigo(segredo, int((agora or time.time()) // PASSO))


def verificar(segredo, codigo, ultimo_usado=0, agora=None):
    """Retorna o contador do código aceito (para impedir reuso) ou None se inválido."""
    codigo = "".join(c for c in str(codigo) if c.isdigit())
    if len(codigo) != DIGITOS:
        return None
    contador_atual = int((agora or time.time()) // PASSO)
    for contador in range(contador_atual - TOLERANCIA, contador_atual + TOLERANCIA + 1):
        if contador > ultimo_usado and hmac.compare_digest(_codigo(segredo, contador), codigo):
            return contador
    return None


def uri(segredo, usuario, emissor="Comanda"):
    rotulo = quote(f"{emissor}:{usuario}")
    return f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor)}&digits={DIGITOS}&period={PASSO}"


def qr_code(segredo, usuario, emissor="Comanda"):
    """QR code (imagem SVG embutida) para o aplicativo autenticador ler."""
    return segno.make(uri(segredo, usuario, emissor), error="m").svg_data_uri(scale=5, border=2)

"""Telas (as TVs da loja), grupos e a conexão de cada TV pelo QR code.

Cada tela funciona só no aparelho conectado a ela: a TV guarda um "crachá" secreto (cookie)
e o banco guarda só o hash dele. Para conectar, a TV abre /tela, que mostra um código de
6 letras (QR); quem administra lê com o celular e escolhe a tela.
"""

import hashlib
import hmac
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from ..erros import ErroDeDominio

LETRAS_DO_ENDERECO = "abcdefghjkmnpqrstuvwxyz23456789"   # sem 0/o, 1/l/i: fácil no controle da TV
LETRAS_DO_PEDIDO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TAMANHO_DO_PEDIDO = 6
PEDIDO_VALIDADE = 10 * 60      # o QR code da página /tela vale 10 minutos
MAX_PEDIDOS_ABERTOS = 500      # contra quem tenta encher o banco abrindo /tela sem parar
INTERVALO_CONTATO = 30         # segundos: não grava no banco a cada troca de propaganda
FECHADA_TOLERANCIA = 3         # segundos: pedido que estava a caminho quando a janela fechou não a "reabre"
MAX_NOME = 100
MAX_LETREIRO = 500


class ErroDeTela(ErroDeDominio):
    pass


class PedidoVencido(ErroDeTela):
    def __init__(self) -> None:
        super().__init__("Este código de conexão venceu ou não existe. "
                         "Na TV, abra de novo o endereço /tela e leia o código novo.")


class MuitosPedidos(ErroDeTela):
    def __init__(self) -> None:
        super().__init__("Muitos pedidos de conexão abertos. Tente de novo em alguns minutos.")


def hash_do_cracha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cracha_confere(token: str | None, guardado: str | None) -> bool:
    return bool(token) and bool(guardado) and hmac.compare_digest(hash_do_cracha(token or ""), guardado or "")


def novo_cracha() -> str:
    return secrets.token_urlsafe(32)


def novo_endereco(nome: str) -> str:
    """O nome da tela + 6 letras aleatórias, ex.: "promocoes-k7m2x9".

    O final aleatório impede adivinhar o endereço (31^6, cerca de 900 milhões por nome).
    """
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30].strip("-") or "tela"
    return f"{base}-{''.join(secrets.choice(LETRAS_DO_ENDERECO) for _ in range(6))}"


def novo_codigo_de_pedido() -> str:
    return "".join(secrets.choice(LETRAS_DO_PEDIDO) for _ in range(TAMANHO_DO_PEDIDO))


def normalizar_codigo_de_pedido(texto: str | None) -> str:
    return "".join(c for c in (texto or "").upper() if c.isalnum())[:TAMANHO_DO_PEDIDO]


def nome_obrigatorio(nome: str | None, mensagem: str) -> str:
    nome = (nome or "").strip()[:MAX_NOME]
    if not nome:
        raise ErroDeTela(mensagem)
    return nome


@dataclass(frozen=True)
class Tela:
    id: int
    empresa_id: int
    nome: str
    codigo: str                       # o endereço: /tela/<codigo>
    grupo_id: int | None = None
    letreiro: str | None = None       # None = o geral da loja
    aparelho_hash: str | None = None  # hash do crachá do aparelho conectado
    aceita_link: bool = False         # telas antigas: o primeiro aparelho que chegar pelo endereço fica com ela
    ultimo_contato: datetime | None = None
    fechada_em: datetime | None = None

    @property
    def conectada(self) -> bool:
        return self.aparelho_hash is not None

    def aceita(self, token: str | None) -> bool:
        """Este aparelho (com este crachá) é o conectado à tela?"""
        return self.conectada and cracha_confere(token, self.aparelho_hash)

    def precisa_registrar_contato(self, agora: datetime, com_novidade: bool) -> bool:
        """Grava o "sinal de vida" da TV? Não a cada pedido: no máximo a cada 30 s, a não ser que mude algo."""
        if self.fechada_em is not None and (agora - self.fechada_em).total_seconds() < FECHADA_TOLERANCIA:
            return False  # a janela acabou de fechar: este pedido já estava a caminho
        if com_novidade or self.ultimo_contato is None or self.fechada_em is not None:
            return True
        return (agora - self.ultimo_contato).total_seconds() >= INTERVALO_CONTATO


@dataclass(frozen=True)
class PedidoDeConexao:
    id: int
    codigo: str
    segredo_hash: str
    criado_em: datetime
    tela_id: int | None = None

    def vencido(self, agora: datetime) -> bool:
        return (agora - self.criado_em).total_seconds() > PEDIDO_VALIDADE

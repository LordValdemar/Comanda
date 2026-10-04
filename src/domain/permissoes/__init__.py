"""Permissões por papel e autorizações por QR code (sem banco nem Flask)."""

from ..erros import SemPermissao
from .liberacoes import (
    CODIGO_SEGUNDOS,
    LETRAS_DO_CODIGO,
    MAX_MINUTOS,
    MODOS,
    CodigoInvalido,
    CodigoJaUsado,
    CodigoVencido,
    ErroDeAutorizacao,
    Liberacao,
    descrever,
    ler_minutos,
    normalizar_codigo,
)
from .regras import (
    AUTORIZACAO,
    FIXAS,
    FUNCOES,
    NAO,
    NIVEIS,
    PAPEIS_CONFIGURAVEIS,
    PAPEIS_DO_MODULO,
    SIM,
    Funcao,
    Pessoa,
    TabelaDePermissoes,
    modulos_da_pessoa,
)
from .repositorio import Cadastro, RepositorioDePermissoes
from .servico import ServicoDeAutorizacoes

__all__ = [
    "AUTORIZACAO", "CODIGO_SEGUNDOS", "FIXAS", "FUNCOES", "LETRAS_DO_CODIGO", "MAX_MINUTOS", "MODOS", "NAO", "NIVEIS",
    "PAPEIS_CONFIGURAVEIS", "PAPEIS_DO_MODULO", "SIM", "Cadastro", "CodigoInvalido", "CodigoJaUsado", "CodigoVencido",
    "ErroDeAutorizacao", "Funcao", "Liberacao", "Pessoa", "RepositorioDePermissoes", "SemPermissao",
    "ServicoDeAutorizacoes", "TabelaDePermissoes", "descrever", "ler_minutos", "modulos_da_pessoa", "normalizar_codigo",
]

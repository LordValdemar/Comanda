"""Empresas (lojas): módulos, cadastro, limites do plano e abertura de loja."""

from . import modulos
from .cadastro import (
    AVISO_CODIGO,
    CAMPOS,
    COLUNAS,
    LOGO_MAX_BYTES,
    UFS,
    CadastroInvalido,
    codigo_do_nome,
    codigo_valido,
    documento_formatado,
    endereco_completo,
    ler_dados,
    ler_emails,
    ler_logo,
)
from .limites import MB, Limites, Uso
from .plataforma import DadosDaEmpresa, EmpresaCliente, RepositorioDaPlataforma, ServicoDaPlataforma
from .repositorio import RepositorioDeEmpresas
from .servico import CodigoEmUso, Configuracoes, NovaLoja, ServicoDeEmpresas

__all__ = [
    "AVISO_CODIGO", "CAMPOS", "COLUNAS", "LOGO_MAX_BYTES", "MB", "UFS", "CadastroInvalido", "CodigoEmUso", "Configuracoes",
    "DadosDaEmpresa", "EmpresaCliente", "Limites", "NovaLoja", "RepositorioDaPlataforma", "RepositorioDeEmpresas",
    "ServicoDaPlataforma", "ServicoDeEmpresas", "Uso", "codigo_do_nome", "codigo_valido", "documento_formatado",
    "endereco_completo", "ler_dados", "ler_emails", "ler_logo", "modulos",
]

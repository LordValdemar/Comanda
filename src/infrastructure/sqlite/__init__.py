"""Repositórios no SQLite da Comanda local (uma loja só)."""

from .cardapio import RepositorioDeCardapioSQLite
from .comandas import RepositorioDeComandasSQLite
from .consultas_comanda import ConsultasDaComanda
from .consultas_ponto import ConsultasDoPonto
from .permissoes import RepositorioDePermissoesSQLite
from .ponto import RepositorioDePontoSQLite
from .relatorios import RepositorioDeVendasSQLite

__all__ = [
    "ConsultasDaComanda", "ConsultasDoPonto", "RepositorioDeCardapioSQLite", "RepositorioDeComandasSQLite",
    "RepositorioDePermissoesSQLite", "RepositorioDePontoSQLite", "RepositorioDeVendasSQLite",
]

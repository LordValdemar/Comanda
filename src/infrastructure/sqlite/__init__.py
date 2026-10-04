"""Repositórios no SQLite da Comanda local (uma loja só)."""

from .cardapio import RepositorioDeCardapioSQLite
from .comandas import RepositorioDeComandasSQLite
from .permissoes import RepositorioDePermissoesSQLite
from .ponto import RepositorioDePontoSQLite

__all__ = ["RepositorioDeCardapioSQLite", "RepositorioDeComandasSQLite", "RepositorioDePermissoesSQLite", "RepositorioDePontoSQLite"]

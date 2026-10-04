"""Cardápio da Comanda: categorias e produtos (sem banco nem Flask)."""

from .entidades import (
    Categoria,
    CategoriaRepetida,
    CodigoRepetido,
    DadosDoProduto,
    ErroDeCardapio,
    Produto,
    agrupar,
    nome_de_categoria,
)
from .repositorio import RepositorioDeCardapio
from .servico import ServicoDeCardapio

__all__ = [
    "Categoria", "CategoriaRepetida", "CodigoRepetido", "DadosDoProduto", "ErroDeCardapio", "Produto",
    "RepositorioDeCardapio", "ServicoDeCardapio", "agrupar", "nome_de_categoria",
]

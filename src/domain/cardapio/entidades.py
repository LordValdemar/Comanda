"""Cardápio: categorias (em ordem) e produtos (preço, código de lançamento rápido, se vai para a cozinha)."""

from collections.abc import Mapping
from dataclasses import dataclass

from ..dinheiro import ler_reais
from ..erros import ErroDeDominio

MAX_NOME_CATEGORIA = 40
MAX_NOME_PRODUTO = 80
MAX_CODIGO = 10
OUTROS = "Outros"   # onde aparecem os produtos sem categoria


class ErroDeCardapio(ErroDeDominio):
    pass


class CategoriaRepetida(ErroDeCardapio):
    def __init__(self, nome: str) -> None:
        super().__init__(f"A categoria “{nome}” já existe.")


class CodigoRepetido(ErroDeCardapio):
    def __init__(self) -> None:
        super().__init__("Já existe um produto com esse código.")


@dataclass(frozen=True)
class Categoria:
    id: int
    nome: str
    posicao: int = 0
    produtos: int = 0          # quantos produtos estão nela (para a tela)


@dataclass(frozen=True)
class Produto:
    id: int
    nome: str
    preco_centavos: int
    codigo: str | None = None
    categoria_id: int | None = None
    categoria: str | None = None     # nome da categoria (para a tela)
    vai_cozinha: bool = True         # False: sai pronto (ex.: refrigerante em lata)
    ativo: bool = True


@dataclass(frozen=True)
class DadosDoProduto:
    nome: str
    preco_centavos: int
    codigo: str | None
    categoria_id: int | None
    vai_cozinha: bool

    @classmethod
    def do_formulario(cls, campos: Mapping[str, str]) -> "DadosDoProduto":
        """Confere o que foi digitado (a categoria, se houver, ainda precisa ser da loja)."""
        nome = (campos.get("nome") or "").strip()
        if not nome or len(nome) > MAX_NOME_PRODUTO:
            raise ErroDeCardapio(f"Informe o nome do produto (até {MAX_NOME_PRODUTO} caracteres).")
        preco = ler_reais(campos.get("preco"))
        codigo = (campos.get("codigo") or "").strip() or None
        if codigo is not None and len(codigo) > MAX_CODIGO:
            raise ErroDeCardapio(f"O código pode ter no máximo {MAX_CODIGO} caracteres.")
        categoria = (campos.get("categoria_id") or "").strip()
        if categoria and not categoria.isdigit():
            raise ErroDeCardapio("Categoria não encontrada.")
        return cls(nome, preco, codigo, int(categoria) if categoria else None, bool(campos.get("vai_cozinha")))


def nome_de_categoria(nome: str | None) -> str:
    nome = (nome or "").strip()
    if not nome or len(nome) > MAX_NOME_CATEGORIA:
        raise ErroDeCardapio(f"Informe o nome da categoria (até {MAX_NOME_CATEGORIA} caracteres).")
    return nome


def agrupar(produtos: list[Produto]) -> list[tuple[str, list[Produto]]]:
    """[(categoria, [produtos])] mantendo a ordem do cardápio (o groupby do Jinja reordenaria por nome)."""
    grupos: list[tuple[str, list[Produto]]] = []
    for produto in produtos:
        categoria = produto.categoria or OUTROS
        if not grupos or grupos[-1][0] != categoria:
            grupos.append((categoria, []))
        grupos[-1][1].append(produto)
    return grupos

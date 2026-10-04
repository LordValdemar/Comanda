"""Casos de uso do cardápio. Itens já lançados guardam nome e preço: mudar ou excluir um produto não muda o histórico."""

from ..erros import NaoEncontrado
from ..ordem import trocar_com_vizinho
from .entidades import Categoria, DadosDoProduto, ErroDeCardapio, Produto, agrupar, nome_de_categoria
from .repositorio import RepositorioDeCardapio


class ServicoDeCardapio:
    def __init__(self, repositorio: RepositorioDeCardapio) -> None:
        self._repo = repositorio

    def _categoria(self, categoria_id: int) -> Categoria:
        categoria = self._repo.categoria(categoria_id)
        if categoria is None:
            raise NaoEncontrado("Categoria não encontrada.")
        return categoria

    def _produto(self, produto_id: int) -> Produto:
        produto = self._repo.produto(produto_id)
        if produto is None:
            raise NaoEncontrado("Produto não encontrado.")
        return produto

    # -- consulta ------------------------------------------------------------------------

    def categorias(self) -> list[Categoria]:
        return self._repo.categorias()

    def produtos(self) -> list[Produto]:
        """Todos (os fora do cardápio no fim), para a tela de cadastro."""
        return self._repo.produtos(so_ativos=False)

    def a_venda(self) -> list[Produto]:
        return self._repo.produtos(so_ativos=True)

    def grupos_a_venda(self) -> list[tuple[str, list[Produto]]]:
        return agrupar(self.a_venda())

    # -- categorias ------------------------------------------------------------------------

    def criar_categoria(self, nome: str) -> str:
        nome = nome_de_categoria(nome)
        self._repo.inserir_categoria(nome)
        return nome

    def renomear_categoria(self, categoria_id: int, nome: str) -> None:
        self._categoria(categoria_id)
        self._repo.renomear_categoria(categoria_id, nome_de_categoria(nome))

    def mover_categoria(self, categoria_id: int, para_cima: bool) -> None:
        self._categoria(categoria_id)
        ordem = trocar_com_vizinho([c.id for c in self._repo.categorias()], categoria_id, para_cima)
        if ordem is not None:
            self._repo.gravar_ordem_das_categorias(ordem)

    def excluir_categoria(self, categoria_id: int) -> Categoria:
        categoria = self._categoria(categoria_id)
        self._repo.excluir_categoria(categoria_id)
        return categoria

    # -- produtos ---------------------------------------------------------------------------

    def _conferir_categoria(self, dados: DadosDoProduto) -> None:
        if dados.categoria_id is not None and self._repo.categoria(dados.categoria_id) is None:
            raise ErroDeCardapio("Categoria não encontrada.")   # inclusive a de outra loja

    def criar_produto(self, dados: DadosDoProduto) -> int:
        self._conferir_categoria(dados)
        return self._repo.inserir_produto(dados)

    def atualizar_produto(self, produto_id: int, dados: DadosDoProduto) -> None:
        self._produto(produto_id)
        self._conferir_categoria(dados)
        self._repo.atualizar_produto(produto_id, dados)

    def alternar_ativo(self, produto_id: int) -> Produto:
        """Tira do cardápio (ou volta). Devolve como estava antes."""
        produto = self._produto(produto_id)
        self._repo.definir_ativo(produto_id, not produto.ativo)
        return produto

    def excluir_produto(self, produto_id: int) -> Produto:
        produto = self._produto(produto_id)
        self._repo.excluir_produto(produto_id)
        return produto

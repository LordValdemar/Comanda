"""Repositório do cardápio da Comanda local no SQLite (categorias e produtos; um estabelecimento só)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from src.domain.cardapio import Categoria, CategoriaRepetida, CodigoRepetido, DadosDoProduto, Produto

_PRODUTOS = ("SELECT p.*, c.nome AS categoria FROM produtos p LEFT JOIN categorias c ON c.id = p.categoria_id "
             "WHERE 1 = 1 ")
_ORDEM = "c.id IS NULL, c.posicao, c.nome, p.nome"   # categorias pela posição; sem categoria no fim


def _produto(linha: sqlite3.Row) -> Produto:
    return Produto(id=linha["id"], nome=linha["nome"], preco_centavos=linha["preco_centavos"], codigo=linha["codigo"],
                   categoria_id=linha["categoria_id"], categoria=linha["categoria"],
                   vai_cozinha=bool(linha["vai_cozinha"]), ativo=bool(linha["ativo"]))


class RepositorioDeCardapioSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    @contextmanager
    def _gravando(self, nome_da_categoria: str | None = None) -> Iterator[None]:
        """Grava (commit); nome ou código repetido vira o erro da regra."""
        try:
            with self._c:
                yield
        except sqlite3.IntegrityError as erro:
            if "UNIQUE" in str(erro) and "categorias" in str(erro):
                raise CategoriaRepetida(nome_da_categoria or "") from None
            if "UNIQUE" in str(erro) and "produtos" in str(erro):
                raise CodigoRepetido() from None
            raise

    # -- categorias -----------------------------------------------------------------------

    def categorias(self) -> list[Categoria]:
        return [Categoria(id=linha["id"], nome=linha["nome"], posicao=linha["posicao"], produtos=linha["produtos"])
                for linha in self._c.execute(
                    "SELECT c.*, (SELECT COUNT(*) FROM produtos p WHERE p.categoria_id = c.id) AS produtos "
                    "FROM categorias c ORDER BY posicao, nome")]

    def categoria(self, categoria_id: int) -> Categoria | None:
        linha = self._c.execute("SELECT * FROM categorias WHERE id = ?",
                                (categoria_id,)).fetchone()
        return None if linha is None else Categoria(id=linha["id"], nome=linha["nome"], posicao=linha["posicao"])

    def inserir_categoria(self, nome: str) -> int:
        with self._gravando(nome):
            proxima = self._c.execute("SELECT COALESCE(MAX(posicao), 0) + 1 FROM categorias").fetchone()[0]
            cursor = self._c.execute("INSERT INTO categorias (nome, posicao) VALUES (?, ?)", (nome, proxima))
        return int(cursor.lastrowid or 0)

    def renomear_categoria(self, categoria_id: int, nome: str) -> None:
        with self._gravando(nome):
            self._c.execute("UPDATE categorias SET nome = ? WHERE id = ?",
                            (nome, categoria_id))

    def gravar_ordem_das_categorias(self, ids: list[int]) -> None:
        with self._gravando():
            self._c.executemany("UPDATE categorias SET posicao = ? WHERE id = ?",
                                [(posicao, ident) for posicao, ident in enumerate(ids, start=1)])

    def excluir_categoria(self, categoria_id: int) -> None:
        with self._gravando():   # os produtos ficam "sem categoria" (ON DELETE SET NULL)
            self._c.execute("DELETE FROM categorias WHERE id = ?", (categoria_id,))

    # -- produtos -----------------------------------------------------------------------------

    def produtos(self, so_ativos: bool) -> list[Produto]:
        filtro = "AND p.ativo = 1 " if so_ativos else ""
        ordem = _ORDEM if so_ativos else "p.ativo DESC, " + _ORDEM
        return [_produto(linha) for linha in self._c.execute(_PRODUTOS + filtro + "ORDER BY " + ordem)]

    def produto(self, produto_id: int) -> Produto | None:
        linha = self._c.execute(_PRODUTOS + "AND p.id = ?", (produto_id,)).fetchone()
        return None if linha is None else _produto(linha)

    def inserir_produto(self, dados: DadosDoProduto) -> int:
        with self._gravando():
            cursor = self._c.execute(
                "INSERT INTO produtos (nome, preco_centavos, codigo, categoria_id, vai_cozinha) VALUES (?, ?, ?, ?, ?)",
                (dados.nome, dados.preco_centavos, dados.codigo, dados.categoria_id,
                 int(dados.vai_cozinha)),
            )
        return int(cursor.lastrowid or 0)

    def atualizar_produto(self, produto_id: int, dados: DadosDoProduto) -> None:
        with self._gravando():
            self._c.execute(
                "UPDATE produtos SET nome = ?, preco_centavos = ?, codigo = ?, categoria_id = ?, vai_cozinha = ? "
                "WHERE id = ?",
                (dados.nome, dados.preco_centavos, dados.codigo, dados.categoria_id, int(dados.vai_cozinha),
                 produto_id),
            )

    def definir_ativo(self, produto_id: int, ativo: bool) -> None:
        with self._gravando():
            self._c.execute("UPDATE produtos SET ativo = ? WHERE id = ?",
                            (int(ativo), produto_id))

    def excluir_produto(self, produto_id: int) -> None:
        with self._gravando():   # os itens já vendidos guardam nome e preço: o histórico continua certo
            self._c.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))

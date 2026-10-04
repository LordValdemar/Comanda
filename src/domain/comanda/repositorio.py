"""O que a Comanda precisa do banco de dados (a infraestrutura implementa; os testes usam um falso)."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from .entidades import Comanda, NovoPagamento, Pagamento, Totais


@dataclass(frozen=True)
class ProdutoDoCardapio:
    id: int
    nome: str
    preco_centavos: int
    vai_cozinha: bool


class RepositorioDeComandas(Protocol):
    """Sempre restrito a uma loja: uma comanda de outra loja é como se não existisse."""

    def transacao(self) -> AbstractContextManager[None]:
        """Trava a gravação até o fim do bloco: o que foi conferido não muda antes de gravar."""
        ...

    def carregar(self, comanda_id: int) -> Comanda | None: ...

    def comanda_do_item(self, item_id: int) -> int | None: ...

    def produto_do_cardapio(self, produto_id: int) -> ProdutoDoCardapio | None:
        """Produto ativo do cardápio da loja (ou None, se saiu do cardápio)."""
        ...

    def inserir_comanda(self, numero: int, mesa: str | None, cliente: str | None, taxa_percentual: float,
                        aberta_por: int | None, garcom_id: int | None) -> int:
        """Levanta NumeroEmUso se o número já estiver aberto."""
        ...

    def inserir_item(self, comanda_id: int, produto: ProdutoDoCardapio, quantidade: int, observacao: str | None,
                     status: str, lancado_por: int | None) -> int: ...

    def definir_garcom_se_vazio(self, comanda_id: int, garcom_id: int) -> None: ...

    def gravar_dados(self, comanda_id: int, mesa: str | None, cliente: str | None, garcom_id: int | None) -> None: ...

    def mudar_situacao_do_item(self, item_id: int, nova: str) -> None: ...

    def marcar_tudo_pronto(self, comanda_id: int) -> int: ...

    def cancelar_item(self, item_id: int, motivo: str, usuario_id: int | None) -> None: ...

    def inserir_pagamento(self, comanda_id: int, pagamento: NovoPagamento, usuario_id: int | None) -> int: ...

    def remover_pagamento(self, comanda_id: int, pagamento_id: int) -> Pagamento | None: ...

    def gravar_ajuste(self, comanda_id: int, cobrar_taxa: bool, desconto: int) -> None: ...

    def gravar_fechamento(self, comanda_id: int, totais: Totais, usuario_id: int | None) -> None: ...

    def gravar_cancelamento(self, comanda_id: int, motivo: str, usuario_id: int | None) -> None: ...

    def gravar_reabertura(self, comanda_id: int, numero: int) -> None:
        """Levanta NumeroEmUso se outra comanda com o mesmo número estiver aberta."""
        ...

    def registrar_historico(self, comanda_id: int, acao: str, detalhe: str, usuario_id: int | None) -> None: ...


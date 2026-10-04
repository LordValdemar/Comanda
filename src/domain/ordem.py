"""Mudar um item de lugar numa lista ordenada (propagandas, categorias do cardápio...)."""

from collections.abc import Hashable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


def trocar_com_vizinho(itens: Sequence[T], item: T, para_cima: bool) -> list[T] | None:
    """A lista com `item` um lugar acima (ou abaixo); None se ele já está na ponta. ValueError se não está na lista."""
    posicao = list(itens).index(item)
    destino = posicao - 1 if para_cima else posicao + 1
    if not 0 <= destino < len(itens):
        return None
    ordem = list(itens)
    ordem[posicao], ordem[destino] = ordem[destino], ordem[posicao]
    return ordem

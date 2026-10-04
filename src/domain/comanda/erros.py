"""Exceções da Comanda."""

from ..erros import ErroDeDominio, NaoEncontrado


class ErroComanda(ErroDeDominio):
    """Operação não permitida na comanda (mensagem pode ser mostrada na tela)."""


class ComandaNaoEncontrada(NaoEncontrado):
    """A comanda não existe nesta loja."""


class ItemNaoEncontrado(NaoEncontrado):
    """O item não existe nesta comanda."""


class NumeroEmUso(ErroComanda):
    """Já existe uma comanda aberta com este número na loja."""

    def __init__(self, numero: int) -> None:
        super().__init__(f"A comanda {numero} já está aberta.")
        self.numero = numero

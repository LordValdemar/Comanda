"""Exceções do domínio: cada uma tem uma mensagem que pode ser mostrada para quem usa o sistema."""


class ErroDeDominio(ValueError):
    """Uma regra de negócio impediu a operação (ex.: conta já fechada, valor inválido)."""


class NaoEncontrado(ErroDeDominio):
    """O registro não existe (ou é de outra loja, o que para quem pede dá no mesmo)."""


class SemPermissao(ErroDeDominio):
    """A pessoa não pode fazer isto (na porta de entrada: 403)."""

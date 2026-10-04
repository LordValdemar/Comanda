"""Contas de usuário: papéis, regras de nome e senha, e o acesso conforme a situação da empresa."""

from dataclasses import dataclass

from ..erros import ErroDeDominio

PAPEIS: dict[str, str] = {
    "admin": "Administrador",   # tudo da loja: equipe, ajustes, assinatura e os módulos assinados
    "editor": "Editor",         # Painel: propagandas
    "caixa": "Caixa",           # Comanda: comandas, fechamento, cancelamentos e relatórios
    "garcom": "Garçom",         # Comanda: abre comandas e lança pedidos
    "cozinha": "Cozinha",       # Comanda: só a tela da cozinha
}
SENHA_MINIMA = 8
MAX_NOME = 50
MAX_TENTATIVAS = 5
JANELA_BLOQUEIO = 15 * 60   # segundos


class ErroUsuario(ErroDeDominio):
    """Dados de usuário inválidos ou operação não permitida (mensagem pode ser mostrada na tela)."""


class Bloqueado(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("Muitas tentativas erradas. Aguarde 15 minutos e tente de novo.")


class CredenciaisInvalidas(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("Usuário ou senha incorretos.")


class LojaAmbigua(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("Este usuário e senha existem em mais de uma loja. Informe também o código da sua loja.")


class EmpresaSuspensa(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("O acesso desta empresa está suspenso. Fale com o suporte.")


class CodigoIncorreto(ErroUsuario):
    pass


class PapelInvalido(ErroUsuario):
    pass


def validar_senha(senha: str) -> None:
    if len(senha or "") < SENHA_MINIMA:
        raise ErroUsuario(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")


def nome_de_usuario(nome: str | None) -> str:
    nome = (nome or "").strip()
    if not nome or len(nome) > MAX_NOME:
        raise ErroUsuario(f"Informe um nome de usuário (até {MAX_NOME} caracteres).")
    return nome


def acesso(empresa_ativa: bool, motivo_suspensao: str | None, plataforma: bool) -> str:
    """'liberado', 'so_pagamento' (suspensa por falta de pagamento: só a página de pagamento) ou 'suspenso'."""
    if empresa_ativa or plataforma:
        return "liberado"
    return "so_pagamento" if motivo_suspensao == "inadimplencia" else "suspenso"


@dataclass(frozen=True)
class Conta:
    id: int
    empresa_id: int
    usuario: str
    papel: str
    senha_hash: str
    token_sessao: str
    plataforma: bool = False
    fecha_conta: bool = False
    totp_segredo: str | None = None
    totp_pendente: str | None = None
    totp_ultimo: int = 0
    empresa_ativa: bool = True
    motivo_suspensao: str | None = None

    @property
    def acesso(self) -> str:
        return acesso(self.empresa_ativa, self.motivo_suspensao, self.plataforma)

    @property
    def tem_2fa(self) -> bool:
        return bool(self.totp_segredo)

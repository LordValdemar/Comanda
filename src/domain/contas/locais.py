"""Contas de uma instalação de uma loja só (a Comanda local): sem empresas, com usuários ativos e desativados.

Diferenças das contas da plataforma: senha mínima menor (a equipe entra várias vezes por dia, no celular,
numa rede local), quem sai da equipe é desativado (não excluído) e sempre fica pelo menos um administrador ativo.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .. import totp
from ..erros import NaoEncontrado
from ..tentativas import LimiteDeTentativas
from .entidades import JANELA_BLOQUEIO, MAX_TENTATIVAS, CodigoIncorreto, ErroUsuario, PapelInvalido
from .repositorio import Senhas
from .servico import novo_token

SENHA_MINIMA_LOCAL = 6
MAX_NOME_LOCAL = 40


class BloqueadoAqui(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("Muitas tentativas erradas. Espere 15 minutos e tente de novo.")


class Desativado(ErroUsuario):
    def __init__(self) -> None:
        super().__init__("Este usuário está desativado. Fale com o administrador.")


@dataclass(frozen=True)
class ContaLocal:
    id: int
    usuario: str
    papel: str
    senha_hash: str
    token_sessao: str
    ativo: bool
    fecha_conta: bool
    totp_segredo: str | None
    totp_ultimo: int

    @property
    def tem_2fa(self) -> bool:
        return bool(self.totp_segredo)


class RepositorioDeContasLocais(Protocol):
    def conta(self, usuario_id: int) -> ContaLocal | None: ...
    def conta_com_nome(self, nome: str) -> ContaLocal | None: ...
    def existe_alguem(self) -> bool: ...
    def nome_em_uso(self, nome: str) -> bool: ...
    def admins_ativos(self) -> int: ...
    def inserir(self, nome: str, senha_hash: str, papel: str, token: str) -> int: ...
    def gravar_senha(self, usuario_id: int, senha_hash: str, token: str) -> None: ...
    def ativar_totp(self, usuario_id: int, segredo: str, contador: int) -> None: ...
    def desativar_totp(self, usuario_id: int, token: str) -> None: ...
    def gravar_totp_ultimo(self, usuario_id: int, contador: int) -> None: ...
    def mudar_papel(self, usuario_id: int, papel: str) -> None: ...   # "fecha contas" só fica com garçom
    def definir_fecha_conta(self, usuario_id: int, pode: bool) -> None: ...
    def definir_ativo(self, usuario_id: int, ativo: bool, token: str) -> None: ...


class ServicoDeContasLocais:
    def __init__(self, repositorio: RepositorioDeContasLocais, senhas: Senhas, papeis: Mapping[str, str],
                 tentativas: LimiteDeTentativas | None = None, relogio: Callable[[], float] = time.time) -> None:
        self._repo = repositorio
        self._senhas = senhas
        self._papeis = papeis
        self._tentativas = tentativas or LimiteDeTentativas(MAX_TENTATIVAS, JANELA_BLOQUEIO)
        self._relogio = relogio   # para os códigos de 2FA

    def conta(self, usuario_id: int) -> ContaLocal:
        conta = self._repo.conta(usuario_id)
        if conta is None:
            raise NaoEncontrado("Usuário não encontrado.")
        return conta

    def existe_alguem(self) -> bool:
        return self._repo.existe_alguem()

    def pelo_nome(self, nome: str) -> ContaLocal:
        conta = self._repo.conta_com_nome((nome or "").strip())
        if conta is None:
            raise NaoEncontrado(f"Usuário “{(nome or '').strip()}” não encontrado.")
        return conta

    # -- regras ---------------------------------------------------------------------------------

    @staticmethod
    def validar_senha(senha: str) -> None:
        if len(senha or "") < SENHA_MINIMA_LOCAL:
            raise ErroUsuario(f"A senha precisa ter pelo menos {SENHA_MINIMA_LOCAL} caracteres.")

    def _papel(self, papel: str) -> str:
        if papel not in self._papeis:
            raise PapelInvalido("Papel inválido.")
        return papel

    def _ultimo_admin(self, conta: ContaLocal) -> bool:
        return conta.papel == "admin" and conta.ativo and self._repo.admins_ativos() <= 1

    def _codigo_confere(self, conta: ContaLocal, codigo: str | None) -> bool:
        """Confere e guarda o contador usado: o mesmo código não vale duas vezes."""
        contador = totp.verificar(conta.totp_segredo or "", codigo, conta.totp_ultimo, self._relogio())
        if contador is None:
            return False
        self._repo.gravar_totp_ultimo(conta.id, contador)
        return True

    # -- cadastro e senha -----------------------------------------------------------------------------

    def criar(self, nome: str, senha: str, papel: str = "garcom") -> int:
        nome = (nome or "").strip()
        if not nome or len(nome) > MAX_NOME_LOCAL:
            raise ErroUsuario(f"Informe um nome de usuário (até {MAX_NOME_LOCAL} caracteres).")
        self._papel(papel)
        self.validar_senha(senha)
        if self._repo.nome_em_uso(nome):
            raise ErroUsuario(f"O usuário “{nome}” já existe. Escolha outro nome.")
        return self._repo.inserir(nome, self._senhas.gerar(senha), papel, novo_token())

    def trocar_senha(self, usuario_id: int, nova: str) -> None:
        """Trocar o token derruba as sessões abertas em outros aparelhos."""
        self.validar_senha(nova)
        self._repo.gravar_senha(usuario_id, self._senhas.gerar(nova), novo_token())

    def recuperar_acesso(self, usuario_id: int, nova: str) -> None:
        """Linha de comando, para quem esqueceu a senha: senha nova e o usuário volta a ficar ativo."""
        self.trocar_senha(usuario_id, nova)
        self._repo.definir_ativo(usuario_id, True, novo_token())

    def mudar_minha_senha(self, conta: ContaLocal, atual: str, nova: str, confirmacao: str) -> None:
        if not self._senhas.confere(conta.senha_hash, atual):
            raise ErroUsuario("A senha atual está errada.")
        if nova != confirmacao:
            raise ErroUsuario("As senhas novas não conferem.")
        self.trocar_senha(conta.id, nova)

    # -- login -----------------------------------------------------------------------------------------

    def entrar(self, nome: str, senha: str, ip: str) -> ContaLocal:
        """Confere usuário e senha. A conta devolvida pode ainda precisar do código de 2FA (conta.tem_2fa)."""
        if self._tentativas.bloqueado(ip):
            raise BloqueadoAqui()
        conta = self._repo.conta_com_nome((nome or "").strip())
        if conta is None or not self._senhas.confere(conta.senha_hash, senha):
            self._tentativas.errou(ip)
            raise ErroUsuario("Usuário ou senha incorretos.")
        if not conta.ativo:
            raise Desativado()
        self._tentativas.acertou(ip)
        return conta

    def pode_pedir_codigo(self, usuario_id: int) -> ContaLocal | None:
        """A conta que está na segunda etapa do login (None se não existe mais, foi desativada ou tirou o 2FA)."""
        conta = self._repo.conta(usuario_id)
        return conta if conta is not None and conta.ativo and conta.tem_2fa else None

    def confirmar_codigo(self, conta: ContaLocal, codigo: str | None, ip: str) -> ContaLocal:
        if self._tentativas.bloqueado(ip):
            raise BloqueadoAqui()
        if not self._codigo_confere(conta, codigo):
            self._tentativas.errou(ip)
            raise CodigoIncorreto("Código incorreto. Confira o relógio do celular e tente o código novo.")
        self._tentativas.acertou(ip)
        return self.conta(conta.id)

    # -- 2FA da própria conta (o segredo novo fica com quem chama até ser confirmado) -------------------

    def ativar_2fa(self, conta: ContaLocal, segredo: str, codigo: str | None) -> None:
        if conta.tem_2fa:
            return
        contador = totp.verificar(segredo, codigo, 0, self._relogio())
        if contador is None:
            raise CodigoIncorreto("Código incorreto. Confira se leu o QR code certo e se o relógio do celular está certo.")
        self._repo.ativar_totp(conta.id, segredo, contador)

    def desativar_2fa_propria(self, conta: ContaLocal, senha: str, codigo: str | None) -> None:
        if not self._senhas.confere(conta.senha_hash, senha):
            raise ErroUsuario("Senha incorreta.")
        if not self._codigo_confere(conta, codigo):
            raise CodigoIncorreto("Código incorreto.")
        self.desativar_2fa(conta.id)

    def desativar_2fa(self, usuario_id: int) -> None:
        """Troca o token: quem tinha o celular perdido não continua dentro."""
        self._repo.desativar_totp(usuario_id, novo_token())

    # -- equipe (administrador) ---------------------------------------------------------------------------

    def mudar_papel(self, alvo_id: int, papel: str) -> ContaLocal:
        alvo = self.conta(alvo_id)
        self._papel(papel)
        if self._ultimo_admin(alvo) and papel != "admin":
            raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")
        self._repo.mudar_papel(alvo_id, papel)
        return alvo

    def alternar_fecha_conta(self, alvo_id: int) -> tuple[ContaLocal, bool]:
        alvo = self.conta(alvo_id)
        if alvo.papel != "garcom":
            raise ErroUsuario("Só garçons recebem esta permissão (caixa e administrador já fecham contas).")
        self._repo.definir_fecha_conta(alvo_id, not alvo.fecha_conta)
        return alvo, not alvo.fecha_conta

    def alternar_ativo(self, alvo_id: int) -> tuple[ContaLocal, bool]:
        """Desativar também derruba as sessões abertas (troca o token)."""
        alvo = self.conta(alvo_id)
        ativar = not alvo.ativo
        if not ativar and self._ultimo_admin(alvo):
            raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")
        self._repo.definir_ativo(alvo_id, ativar, novo_token())
        return alvo, ativar

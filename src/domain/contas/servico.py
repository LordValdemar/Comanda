"""Casos de uso das contas: criar, entrar (senha e 2FA), trocar senha, 2FA e a equipe da loja.

Trocar o token de sessão derruba as sessões abertas nos outros aparelhos: acontece ao trocar a
senha e ao ligar ou desligar a 2FA. O nome de usuário é único dentro da empresa ("joao" pode
existir em várias lojas); no login, vale a loja em que a senha confere.
"""

import secrets
import time
from collections.abc import Callable, Iterable

from .. import totp
from ..erros import NaoEncontrado, SemPermissao
from ..permissoes.regras import PAPEIS_DO_MODULO
from ..tentativas import LimiteDeTentativas
from .entidades import (
    JANELA_BLOQUEIO,
    MAX_TENTATIVAS,
    PAPEIS,
    Bloqueado,
    CodigoIncorreto,
    Conta,
    CredenciaisInvalidas,
    EmpresaSuspensa,
    ErroUsuario,
    LojaAmbigua,
    PapelInvalido,
    nome_de_usuario,
    validar_senha,
)
from .repositorio import RepositorioDeContas, Senhas


def novo_token() -> str:
    return secrets.token_hex(16)


class ServicoDeContas:
    def __init__(self, repositorio: RepositorioDeContas, senhas: Senhas, tentativas: LimiteDeTentativas | None = None,
                 relogio: Callable[[], float] = time.time) -> None:
        self._repo = repositorio
        self._senhas = senhas
        self._tentativas = tentativas or LimiteDeTentativas(MAX_TENTATIVAS, JANELA_BLOQUEIO)
        self._relogio = relogio   # para os códigos de 2FA

    def conta(self, usuario_id: int) -> Conta:
        conta = self._repo.conta(usuario_id)
        if conta is None:
            raise NaoEncontrado("Usuário não encontrado.")
        return conta

    def existe_alguem(self) -> bool:
        return self._repo.existe_alguem()

    def contas_chamadas(self, nome: str, loja: str | None = None) -> list[Conta]:
        """Para a linha de comando: o mesmo nome pode existir em mais de uma loja (o código da loja desempata)."""
        return self._repo.contas_com_nome((nome or "").strip(), loja or None)

    # -- cadastro e senha ------------------------------------------------------------------------

    def criar(self, empresa_id: int, nome: str, senha: str, papel: str = "editor", plataforma: bool = False) -> int:
        nome = nome_de_usuario(nome)
        if papel not in PAPEIS:
            raise ErroUsuario("Papel inválido.")
        validar_senha(senha)
        if not self._repo.empresa_existe(empresa_id):
            raise ErroUsuario("Empresa não encontrada.")
        if self._repo.nome_em_uso(empresa_id, nome):
            raise ErroUsuario(f"O usuário “{nome}” já existe. Escolha outro nome.")
        return self._repo.inserir(empresa_id, nome, self._senhas.gerar(senha), papel, plataforma, novo_token())

    def trocar_senha(self, usuario_id: int, nova: str) -> None:
        validar_senha(nova)
        self._repo.gravar_senha(usuario_id, self._senhas.gerar(nova), novo_token())

    def mudar_minha_senha(self, conta: Conta, atual: str, nova: str, confirmacao: str) -> None:
        if not self._senhas.confere(conta.senha_hash, atual):
            raise ErroUsuario("A senha atual está incorreta.")
        if nova != confirmacao:
            raise ErroUsuario("As senhas novas não conferem.")
        self.trocar_senha(conta.id, nova)

    # -- entrar -------------------------------------------------------------------------------------

    def entrar(self, nome: str, senha: str, loja: str | None, ip: str) -> Conta:
        """Confere usuário e senha. A conta devolvida pode ainda precisar do código de 2FA (conta.tem_2fa)."""
        if self._tentativas.bloqueado(ip):
            raise Bloqueado()
        # A senha é conferida antes de pedir o código da loja: quem não sabe a senha não descobre que o nome existe.
        certas = [c for c in self._repo.contas_com_nome((nome or "").strip(), loja or None)
                  if self._senhas.confere(c.senha_hash, senha)]
        if len(certas) > 1:
            raise LojaAmbigua()
        if not certas:
            self._tentativas.errou(ip)
            raise CredenciaisInvalidas()
        conta = certas[0]
        if conta.acesso == "suspenso":
            raise EmpresaSuspensa()
        if not conta.tem_2fa:
            self._tentativas.acertou(ip)
        return conta

    def confirmar_codigo(self, usuario_id: int, codigo: str | None, ip: str) -> Conta:
        """Segunda etapa do login. O mesmo código não vale duas vezes."""
        if self._tentativas.bloqueado(ip):
            raise Bloqueado()
        conta = self._repo.conta(usuario_id)
        contador = totp.verificar(conta.totp_segredo or "", codigo, conta.totp_ultimo, self._relogio()) if conta else None
        if conta is None or contador is None:
            self._tentativas.errou(ip)
            raise CodigoIncorreto("Código incorreto ou já usado. Confira o aplicativo e tente de novo.")
        self._repo.gravar_totp_ultimo(conta.id, contador)
        self._tentativas.acertou(ip)
        return conta

    # -- 2FA da própria conta --------------------------------------------------------------------------

    def segredo_para_ativar(self, conta: Conta) -> str:
        """Segredo provisório (no banco, não no cookie): só vale depois de confirmar um código do aplicativo."""
        if conta.totp_pendente:
            return conta.totp_pendente
        segredo = totp.novo_segredo()
        self._repo.gravar_totp_pendente(conta.id, segredo)
        return segredo

    def ativar_2fa(self, conta: Conta, codigo: str | None) -> None:
        contador = totp.verificar(conta.totp_pendente or "", codigo, 0, self._relogio())
        if not conta.totp_pendente or contador is None:
            raise CodigoIncorreto("Código incorreto. Confira se o aplicativo leu o QR code e tente de novo.")
        self._repo.ativar_totp(conta.id, conta.totp_pendente, contador, novo_token())

    def desativar_2fa_propria(self, conta: Conta, senha: str, codigo: str | None) -> None:
        if not self._senhas.confere(conta.senha_hash, senha):
            raise ErroUsuario("Senha incorreta.")
        if totp.verificar(conta.totp_segredo or "", codigo, conta.totp_ultimo, self._relogio()) is None:
            raise CodigoIncorreto("Código incorreto.")
        self.desativar_2fa(conta.id)

    def desativar_2fa(self, usuario_id: int) -> None:
        self._repo.desativar_totp(usuario_id, novo_token())

    # -- equipe da loja (administrador) ------------------------------------------------------------------

    def _da_loja(self, empresa_id: int, usuario_id: int) -> Conta:
        alvo = self._repo.conta(usuario_id)
        if alvo is None or alvo.empresa_id != empresa_id:
            raise NaoEncontrado("Usuário não encontrado.")   # de outra loja: para quem pede, não existe
        return alvo

    @staticmethod
    def papel_permitido(papel: str, modulos_da_loja: Iterable[str]) -> str:
        """Só papéis dos módulos que a loja tem (admin sempre)."""
        if papel == "admin" or papel not in PAPEIS:
            return papel
        if any(papel in PAPEIS_DO_MODULO.get(m, ()) for m in modulos_da_loja):
            return papel
        raise ErroUsuario("Este papel é de um módulo que sua loja não assinou.")

    def criar_na_loja(self, empresa_id: int, modulos_da_loja: Iterable[str], nome: str, senha: str, papel: str) -> int:
        return self.criar(empresa_id, nome, senha, self.papel_permitido(papel, modulos_da_loja))

    def editar(self, empresa_id: int, quem_edita: int, alvo_id: int, papel: str | None, senha: str,
               modulos_da_loja: Iterable[str]) -> tuple[Conta, list[str]]:
        """Troca o papel e/ou define senha nova (para quem esqueceu). Devolve a pessoa e o que mudou."""
        alvo = self._da_loja(empresa_id, alvo_id)
        if alvo.id == quem_edita or alvo.plataforma:
            # O próprio papel não muda (evita ficar sem administrador); a própria senha é em "Minha conta".
            raise SemPermissao("Não é possível editar este usuário.")
        papel = papel or alvo.papel
        if papel != alvo.papel:
            papel = self.papel_permitido(papel, modulos_da_loja)
        if papel not in PAPEIS:
            raise ErroUsuario("Papel inválido.")
        if senha:
            self.trocar_senha(alvo_id, senha)   # derruba as sessões abertas da pessoa
        mudancas = []
        if papel != alvo.papel:
            self._repo.mudar_papel(alvo_id, papel)
            mudancas.append(f"agora é {PAPEIS[papel]}")
        if senha:
            mudancas.append("tem senha nova (os aparelhos dela precisam entrar de novo)")
        return alvo, mudancas

    def excluir(self, empresa_id: int, quem_exclui: int, alvo_id: int) -> Conta:
        alvo = self._da_loja(empresa_id, alvo_id)
        if alvo.id == quem_exclui:
            raise ErroUsuario("Você não pode excluir o próprio usuário.")
        self._repo.excluir(alvo_id)
        return alvo

    def alternar_fecha_conta(self, empresa_id: int, alvo_id: int) -> tuple[Conta, bool]:
        """Comanda: autoriza (ou não) um garçom a receber pagamentos e fechar contas."""
        alvo = self._da_loja(empresa_id, alvo_id)
        if alvo.papel != "garcom":
            raise PapelInvalido("Só garçons recebem esta permissão.")
        novo = not alvo.fecha_conta
        self._repo.definir_fecha_conta(alvo_id, novo)
        return alvo, novo

    def desativar_2fa_de(self, empresa_id: int, alvo_id: int) -> Conta:
        """Para quando alguém da equipe perde o celular."""
        alvo = self._da_loja(empresa_id, alvo_id)
        self.desativar_2fa(alvo_id)
        return alvo

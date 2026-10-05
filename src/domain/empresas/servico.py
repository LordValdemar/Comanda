"""Casos de uso das empresas: módulos, limites do plano, configurações e abertura de loja pelo cadastro."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TypeVar

from ..erros import NaoEncontrado
from . import modulos as _modulos
from .cadastro import AVISO_CODIGO, NOME_MAX, CadastroInvalido, codigo_do_nome, codigo_valido, ler_dados, ler_emails, ler_logo
from .limites import Uso
from .repositorio import RepositorioDeEmpresas

T = TypeVar("T")
WEBHOOK_MAX = 500
EMAIL_MAX = 200


class CodigoEmUso(CadastroInvalido):
    def __init__(self, codigo: str) -> None:
        super().__init__(f"O código “{codigo}” já é de outra loja. Escolha outro.")


@dataclass(frozen=True)
class Configuracoes:
    """O formulário "Empresa": só os campos de cadastro que vieram são gravados."""

    nome: str
    codigo: str
    alerta_emails: str = ""
    alerta_webhook: str = ""
    cadastro: Mapping[str, str] = field(default_factory=dict)
    logo: bytes | None = None


@dataclass(frozen=True)
class NovaLoja:
    nome: str
    codigo: str
    email: str
    senhas_conferem: bool
    aceitou_termos: bool


class ServicoDeEmpresas:
    def __init__(self, repositorio: RepositorioDeEmpresas, empresa_principal: int,
                 conferir_webhook: Callable[[str], str | None] = lambda _url: None) -> None:
        """`conferir_webhook` devolve o motivo de recusar o endereço (ou None)."""
        self._repo = repositorio
        self._principal = empresa_principal
        self._conferir_webhook = conferir_webhook

    # Módulos e limites -------------------------------------------------

    def modulos(self, empresa_id: int) -> set[str]:
        if empresa_id == self._principal:
            return set(_modulos.MODULOS)
        linha = self._repo.modulos(empresa_id)
        return set() if linha is None else _modulos.da_empresa(False, *linha)

    def uso(self, empresa_id: int) -> Uso:
        return self._repo.uso(empresa_id)

    def cabe_mais_uma_tela(self, empresa_id: int) -> bool:
        return self._repo.limites(empresa_id).cabe_mais_uma_tela(self._repo.uso(empresa_id))

    def cabe_no_armazenamento(self, empresa_id: int, bytes_novos: int) -> bool:
        return self._repo.limites(empresa_id).cabe_no_armazenamento(self._repo.uso(empresa_id), bytes_novos)

    # Código da loja ----------------------------------------------------

    def codigo_livre(self, nome: str, empresa_id: int | None = None) -> str:
        """Código a partir do nome que nenhuma outra loja usa: padeiro-lanches, padeiro-lanches-2…"""
        base = codigo_do_nome(nome)
        candidato, numero = base, 2
        while self._repo.codigo_em_uso(candidato, empresa_id):
            candidato, numero = f"{base}-{numero}", numero + 1
        return candidato

    def _conferir_codigo(self, codigo: str, empresa_id: int | None) -> None:
        if not codigo_valido(codigo):
            raise CadastroInvalido(AVISO_CODIGO)
        if self._repo.codigo_em_uso(codigo, empresa_id):
            raise CodigoEmUso(codigo)

    # Configurações (administrador da loja) -----------------------------

    def salvar_configuracoes(self, empresa_id: int, configuracoes: Configuracoes) -> None:
        nome = configuracoes.nome.strip()[:NOME_MAX]
        if not nome:
            raise CadastroInvalido("Informe o nome da empresa.")
        cadastro = ler_dados(configuracoes.cadastro)
        if configuracoes.logo is not None:
            cadastro["logo"] = ler_logo(configuracoes.logo)
        codigo = configuracoes.codigo.strip().lower()
        self._conferir_codigo(codigo, empresa_id)
        emails = ler_emails(configuracoes.alerta_emails)
        webhook = configuracoes.alerta_webhook.strip()[:WEBHOOK_MAX]
        if webhook and (motivo := self._conferir_webhook(webhook)):
            raise CadastroInvalido(f"Webhook recusado: {motivo}.")
        self._repo.salvar_configuracoes(empresa_id, nome, codigo, ", ".join(emails), webhook, cadastro)

    def remover_logo(self, empresa_id: int) -> None:
        self._repo.remover_logo(empresa_id)

    def renomear(self, empresa_id: int, nome: str) -> None:
        """Só o nome (o primeiro acesso dá nome à empresa principal); em branco, fica como está."""
        if nome.strip():
            self._repo.renomear(empresa_id, nome.strip()[:NOME_MAX])

    # Cadastro aberto: a loja e o administrador dela ---------------------

    def abrir_loja(self, loja: NovaLoja, criar_administrador: Callable[[int], T]) -> tuple[int, T]:
        """Cria a empresa e, nela, o administrador. Se o administrador for recusado, a empresa é desfeita."""
        nome = loja.nome.strip()[:NOME_MAX]
        codigo = loja.codigo.strip().lower()
        email = loja.email.strip()
        if not nome:
            raise CadastroInvalido("Informe o nome da loja.")
        if codigo:
            self._conferir_codigo(codigo, None)
        if "@" not in email or len(email) > EMAIL_MAX:
            raise CadastroInvalido("Informe um e-mail válido (é para onde vão as faturas e avisos).")
        if not loja.senhas_conferem:
            raise CadastroInvalido("As senhas não conferem.")
        if not loja.aceitou_termos:
            raise CadastroInvalido("Para criar a conta, aceite os Termos de Uso e a Política de Privacidade.")
        empresa_id = self._repo.criar(nome, codigo or self.codigo_livre(nome), email)
        try:
            return empresa_id, criar_administrador(empresa_id)
        except Exception:
            self._repo.apagar(empresa_id)
            raise

    def conferir_existe(self, empresa_id: int) -> None:
        if not self._repo.existe(empresa_id):
            raise NaoEncontrado("Empresa não encontrada.")

"""A plataforma administrando as empresas clientes: criar, limites, módulos liberados, suspender e excluir."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from ..erros import NaoEncontrado
from .cadastro import NOME_MAX, CadastroInvalido, ler_dados
from .limites import Limites

T = TypeVar("T")
SUSPENSAO_MANUAL = "manual"


@dataclass(frozen=True)
class EmpresaCliente:
    id: int
    nome: str
    ativa: bool
    motivo_suspensao: str | None
    modulos_liberados: str
    tem_assinatura: bool


@dataclass(frozen=True)
class DadosDaEmpresa:
    """O que a plataforma escolhe para uma empresa: nome, limites e módulos liberados à mão."""

    nome: str
    limites: Limites
    modulos_liberados: str
    cadastro: Mapping[str, str] = field(default_factory=dict)


def motivo_da_suspensao(antes: EmpresaCliente, ativa: bool) -> str | None:
    """Reativada: sem motivo. Já suspensa: mantém o motivo (ex.: atraso). Suspensa agora pela plataforma: manual."""
    if ativa:
        return None
    return antes.motivo_suspensao if not antes.ativa else SUSPENSAO_MANUAL


class RepositorioDaPlataforma(Protocol):
    def cliente(self, empresa_id: int) -> EmpresaCliente | None: ...
    def codigo_em_uso(self, codigo: str, exceto_id: int | None = None) -> bool: ...
    def criar_cliente(self, dados: DadosDaEmpresa, codigo: str, cadastro: Mapping[str, str]) -> int: ...
    def atualizar_cliente(self, empresa_id: int, nome: str, limites: Limites, ativa: bool, motivo_suspensao: str | None,
                          modulos_liberados: str) -> None: ...
    def arquivos_de_midia(self, empresa_id: int) -> list[str]: ...
    def apagar(self, empresa_id: int) -> None: ...


class ServicoDaPlataforma:
    def __init__(self, repositorio: RepositorioDaPlataforma, empresa_principal: int,
                 codigo_livre: Callable[[str], str]) -> None:
        self._repo = repositorio
        self._principal = empresa_principal
        self._codigo_livre = codigo_livre

    def cliente(self, empresa_id: int) -> EmpresaCliente:
        empresa = self._repo.cliente(empresa_id)
        if empresa is None:
            raise NaoEncontrado("Empresa não encontrada.")
        return empresa

    def criar(self, dados: DadosDaEmpresa, criar_administrador: Callable[[int], T]) -> tuple[int, T]:
        """Cria a empresa com o administrador dela; se o administrador for recusado, a empresa é desfeita."""
        nome = dados.nome.strip()[:NOME_MAX]
        if not nome:
            raise CadastroInvalido("Informe o nome da empresa.")
        try:
            cadastro = ler_dados(dados.cadastro)
        except CadastroInvalido as erro:
            raise CadastroInvalido(f"Empresa não criada: {erro}") from None
        empresa_id = self._repo.criar_cliente(DadosDaEmpresa(nome, dados.limites, dados.modulos_liberados),
                                              self._codigo_livre(nome), cadastro)
        try:
            return empresa_id, criar_administrador(empresa_id)
        except Exception:
            self._repo.apagar(empresa_id)
            raise

    def atualizar(self, empresa_id: int, dados: DadosDaEmpresa, ativa: bool) -> tuple[EmpresaCliente, bool]:
        """Devolve a empresa como estava e se a situação (ativa/suspensa) mudou. A principal nunca é suspensa."""
        antes = self.cliente(empresa_id)
        ativa = ativa or empresa_id == self._principal
        self._repo.atualizar_cliente(empresa_id, dados.nome.strip()[:NOME_MAX] or antes.nome, dados.limites, ativa,
                                     motivo_da_suspensao(antes, ativa), dados.modulos_liberados)
        return antes, antes.ativa != ativa

    def excluir(self, empresa_id: int, confirmacao: str, cancelar_cobranca: Callable[[int], object],
                apagar_arquivo: Callable[[str], None]) -> EmpresaCliente:
        """Apaga a empresa e tudo dela. Antes, para a cobrança: sem isso o Asaas cobraria um cliente que não existe mais."""
        empresa = self.cliente(empresa_id)
        if empresa_id == self._principal:
            raise CadastroInvalido("A empresa principal não pode ser excluída.")
        if confirmacao.strip() != empresa.nome:
            raise CadastroInvalido("Para excluir, digite o nome exato da empresa.")
        if empresa.tem_assinatura:
            cancelar_cobranca(empresa_id)
        arquivos = self._repo.arquivos_de_midia(empresa_id)
        self._repo.apagar(empresa_id)   # o banco apaga em cascata usuários, telas, propagandas, comandas...
        for arquivo in arquivos:
            apagar_arquivo(arquivo)
        return empresa

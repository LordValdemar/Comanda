"""Casos de uso das autorizações: gerar o código, usar o código, gastar e encerrar a liberação.

O relógio e o sorteio do código são injetados: os testes controlam a hora e o código.
Quem pode autorizar e quem precisa de autorização vem da tabela de permissões da loja.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ..erros import NaoEncontrado, SemPermissao
from .liberacoes import (
    GUARDAR_DIAS,
    MODOS,
    CodigoInvalido,
    CodigoJaUsado,
    CodigoVencido,
    ErroDeAutorizacao,
    Liberacao,
    gerar_codigo,
    ler_minutos,
)
from .regras import AUTORIZACAO, FUNCOES, SIM, Pessoa, TabelaDePermissoes, modulos_da_pessoa
from .repositorio import RepositorioDePermissoes

RECENTES = 15


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class ServicoDeAutorizacoes:
    def __init__(self, repositorio: RepositorioDePermissoes, tabela: TabelaDePermissoes, modulos_da_loja: Iterable[str],
                 relogio: Callable[[], datetime] = _agora, sortear: Callable[[], str] = gerar_codigo) -> None:
        self._repo = repositorio
        self._tabela = tabela
        self._modulos_da_loja = frozenset(modulos_da_loja)
        self._relogio = relogio
        self._sortear = sortear

    def pessoa(self, usuario_id: int | None) -> Pessoa | None:
        """Um funcionário desta loja, com os módulos que ele usa (None se não existe aqui)."""
        cadastro = self._repo.cadastro(usuario_id) if usuario_id is not None else None
        if cadastro is None:
            return None
        return Pessoa(id=cadastro.id, papel=cadastro.papel, nome=cadastro.nome, fecha_conta=cadastro.fecha_conta,
                      modulos=modulos_da_pessoa(cadastro.papel, cadastro.plataforma, self._modulos_da_loja))

    # -- quem autoriza ------------------------------------------------------------

    def gerar_codigo(self, autorizador: Pessoa, funcao: str, modo: str, minutos: str | int | None) -> Liberacao:
        """Um código novo (o anterior desta pessoa, se ninguém leu, deixa de valer)."""
        if funcao not in self._tabela.funcoes_que_pode_autorizar(autorizador):
            raise SemPermissao("Você não pode autorizar isso.")
        if modo not in MODOS:
            raise ErroDeAutorizacao("Escolha como a liberação vai valer.")
        agora = self._relogio()
        codigo, tempo = self._sortear(), ler_minutos(minutos)
        with self._repo.transacao():
            self._repo.apagar_antigas(agora - timedelta(days=GUARDAR_DIAS))
            self._repo.apagar_codigos_abertos(autorizador.id)
            liberacao_id = self._repo.inserir_codigo(codigo, funcao, autorizador.id, agora, modo, tempo)
        return Liberacao(id=liberacao_id, codigo=codigo, funcao=funcao, modo=modo, minutos=tempo, criado_em=agora,
                         autorizado_por=autorizador.id, quem_autorizou=autorizador.nome)

    def situacao_do_codigo(self, codigo: str, autorizador_id: int) -> tuple[str, str | None]:
        """Para a tela do QR: ("aguardando"|"usado"|"trocado", quem usou)."""
        liberacao = self._repo.por_codigo(codigo)
        if liberacao is None or liberacao.autorizado_por != autorizador_id:
            return "trocado", None
        if liberacao.usado:
            return "usado", liberacao.quem_usou
        return "aguardando", None

    def encerrar(self, liberacao_id: int, pessoa: Pessoa) -> Liberacao:
        """Acaba com uma liberação antes da hora: quem deu, ou o administrador."""
        liberacao = self._repo.por_id(liberacao_id)
        if liberacao is None:
            raise NaoEncontrado("Liberação não encontrada.")
        if not pessoa.administrador and liberacao.autorizado_por != pessoa.id:
            raise SemPermissao("Só quem deu a liberação (ou o administrador) pode encerrá-la.")
        self._repo.revogar(liberacao_id, self._relogio(), pessoa.id)
        return liberacao

    def ativas(self, pessoa: Pessoa) -> list[Liberacao]:
        """Liberações valendo agora: o administrador vê todas; quem autoriza, as que deu."""
        return self._repo.ativas(self._relogio(), None if pessoa.administrador else pessoa.id)

    def recentes(self, pessoa: Pessoa) -> list[Liberacao]:
        return self._repo.recentes(None if pessoa.administrador else pessoa.id, RECENTES)

    # -- quem pede -----------------------------------------------------------------

    def usar_codigo(self, codigo: str, pessoa: Pessoa) -> Liberacao:
        """A pessoa leu (ou digitou) o código: confere tudo e libera. Devolve a liberação dada."""
        liberacao = self._repo.por_codigo(codigo.upper())
        if liberacao is None or liberacao.usado or liberacao.funcao not in FUNCOES:
            raise CodigoInvalido()
        agora = self._relogio()
        if liberacao.vencido(agora):
            raise CodigoVencido()
        if liberacao.autorizado_por == pessoa.id:
            raise ErroDeAutorizacao("Quem autoriza não pode usar o próprio código.")
        nivel = self._tabela.nivel(liberacao.funcao, pessoa)
        if nivel == SIM:
            raise ErroDeAutorizacao("Você não precisa de autorização para isso.")
        if nivel != AUTORIZACAO:
            raise ErroDeAutorizacao("Seu papel não pode fazer isso, nem com autorização.")
        # Quem autorizou ainda pode a função? (pode ter mudado de papel depois de abrir o QR)
        if not self._tabela.pode_autorizar(liberacao.funcao, self.pessoa(liberacao.autorizado_por)):
            raise ErroDeAutorizacao("Quem mostrou o código não pode mais autorizar isso.")
        ate = liberacao.prazo_ao_usar(agora)
        if not self._repo.marcar_usado(liberacao.id, pessoa.id, agora, ate):
            raise CodigoJaUsado()  # alguém leu o mesmo QR um instante antes
        return replace(liberacao, usado_por=pessoa.id, quem_usou=pessoa.nome, usado_em=agora, ate=ate)

    def liberacao_vigente(self, pessoa: Pessoa | None, funcao: str) -> Liberacao | None:
        """A liberação valendo agora para esta pessoa nesta função (prefere a que não é de "uma vez")."""
        if pessoa is None:
            return None
        return self._repo.vigente(pessoa.id, funcao, self._relogio())

    def gastar(self, liberacao_ids: Iterable[int]) -> None:
        """A ação liberada "uma vez" deu certo: a liberação acaba."""
        ids = list(liberacao_ids)
        if ids:
            self._repo.consumir(ids, self._relogio())

"""Casos de uso das telas: cadastro e grupos (quem administra) e a conexão da TV pelo QR code.

O crachá da TV chega e sai como texto: pôr e tirar o cookie é da porta de entrada.
"""

import hmac
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from ..erros import NaoEncontrado
from .repositorio import RepositorioDeConexoes, RepositorioDeTelas
from .telas import (
    MAX_LETREIRO,
    MAX_NOME,
    MAX_PEDIDOS_ABERTOS,
    PEDIDO_VALIDADE,
    ErroDeTela,
    MuitosPedidos,
    PedidoDeConexao,
    PedidoVencido,
    Tela,
    hash_do_cracha,
    nome_obrigatorio,
    novo_codigo_de_pedido,
    novo_cracha,
    novo_endereco,
)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class ServicoDeTelas:
    """Quem administra a loja: telas, grupos e escolher a tela de uma TV que pediu conexão."""

    def __init__(self, repositorio: RepositorioDeTelas, relogio: Callable[[], datetime] = _agora,
                 sortear_endereco: Callable[[str], str] = novo_endereco) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._sortear = sortear_endereco

    def telas(self) -> list[Tela]:
        return self._repo.telas()

    def tela(self, tela_id: int) -> Tela:
        tela = self._repo.tela(tela_id)
        if tela is None:
            raise NaoEncontrado("Tela não encontrada.")
        return tela

    def _endereco_livre(self, nome: str) -> str:
        while True:
            codigo = self._sortear(nome)
            if not self._repo.endereco_em_uso(codigo):
                return codigo

    def _grupo_da_loja(self, grupo_id: int | None) -> int | None:
        return grupo_id if grupo_id is not None and self._repo.grupo(grupo_id) is not None else None

    def cadastrar(self, nome: str, grupo_id: int | None, cabe_no_plano: bool) -> Tela:
        """Tela nova: só funciona no aparelho conectado pelo QR code da página /tela."""
        nome = nome_obrigatorio(nome, "Dê um nome para a tela (ex.: “Balcão”, “Vitrine”).")
        if not cabe_no_plano:
            raise ErroDeTela("O limite de telas do seu plano foi atingido. Fale com o suporte para ampliar.")
        return self.tela(self._repo.inserir_tela(nome, self._endereco_livre(nome), self._grupo_da_loja(grupo_id)))

    def atualizar(self, tela_id: int, nome: str, grupo_id: int | None, letreiro: str | None) -> Tela:
        atual = self.tela(tela_id)
        nome = (nome or "").strip()[:MAX_NOME] or atual.nome
        letreiro = (letreiro or "").strip()[:MAX_LETREIRO] or None
        self._repo.atualizar_tela(tela_id, nome, self._grupo_da_loja(grupo_id), letreiro)
        return self.tela(tela_id)

    def trocar_endereco(self, tela_id: int) -> Tela:
        """Endereço novo: o antigo para de funcionar."""
        tela = self.tela(tela_id)
        self._repo.trocar_endereco(tela_id, self._endereco_livre(tela.nome))
        return tela

    def desconectar_aparelho(self, tela_id: int) -> Tela:
        tela = self.tela(tela_id)
        self._repo.desligar_aparelho(tela_id)
        return tela

    def excluir(self, tela_id: int) -> Tela:
        """O histórico de exibições da tela continua nos relatórios."""
        tela = self.tela(tela_id)
        self._repo.excluir_tela(tela_id)
        return tela

    def criar_grupo(self, nome: str) -> str:
        nome = nome_obrigatorio(nome, "Dê um nome para o grupo (ex.: “Lojas de SP”).")
        if self._repo.grupo_com_nome(nome):
            raise ErroDeTela(f"O grupo “{nome}” já existe.")
        self._repo.inserir_grupo(nome)
        return nome

    def excluir_grupo(self, grupo_id: int) -> str:
        """As telas dele ficam sem grupo; propagandas que só iam para ele ficam sem destino (nunca "todas")."""
        nome = self._repo.grupo(grupo_id)
        if nome is None:
            raise NaoEncontrado("Grupo não encontrado.")
        self._repo.excluir_grupo(grupo_id)
        return nome

    # -- conectar uma TV ------------------------------------------------------------------

    def pedido(self, codigo: str) -> PedidoDeConexao:
        """O pedido de conexão que a TV mostrou (ainda dentro dos 10 minutos)."""
        pedido = self._repo.pedido((codigo or "").upper())
        if pedido is None or pedido.vencido(self._relogio()):
            raise PedidoVencido()
        return pedido

    def conectar(self, codigo: str, tela_id: int | None) -> Tela:
        """Liga a TV do pedido à tela escolhida. O aparelho que estava nela deixa de funcionar."""
        pedido = self.pedido(codigo)
        tela = self._repo.tela(tela_id) if tela_id is not None else None
        if tela is None:
            raise ErroDeTela("Escolha uma das telas da lista.")
        if pedido.tela_id is not None:
            raise ErroDeTela("Esta TV já foi conectada.")
        self._repo.ligar_aparelho(tela.id, pedido, self._relogio())
        return tela


class ServicoDeConexao:
    """O lado da TV: abrir o pedido (QR), saber quando foi atendido e conferir o crachá a cada contato."""

    def __init__(self, repositorio: RepositorioDeConexoes, relogio: Callable[[], datetime] = _agora,
                 sortear_codigo: Callable[[], str] = novo_codigo_de_pedido,
                 sortear_cracha: Callable[[], str] = novo_cracha) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._sortear_codigo = sortear_codigo
        self._sortear_cracha = sortear_cracha

    def tela(self, codigo: str) -> Tela | None:
        return self._repo.tela_por_endereco(codigo)

    def autorizar(self, tela: Tela, cracha: str | None) -> tuple[bool, str | None]:
        """(pode, crachá novo para entregar). Telas de antes do pareamento aceitam o primeiro aparelho, uma vez."""
        if tela.conectada:
            return tela.aceita(cracha), None
        if not tela.aceita_link:
            return False, None
        cracha = cracha or self._sortear_cracha()
        if self._repo.ligar_primeiro_aparelho(tela.id, hash_do_cracha(cracha), self._relogio()):
            return True, cracha
        return False, None   # outro aparelho chegou um instante antes

    def telas_do_aparelho(self, crachas: dict[int, str]) -> list[Tela]:
        """Telas cujo crachá está neste navegador (um computador pode mostrar várias)."""
        telas = [tela for tela_id, cracha in crachas.items()
                 if (tela := self._repo.tela(tela_id)) is not None and tela.aceita(cracha)]
        return sorted(telas, key=lambda t: t.nome.lower())

    def abrir_pedido(self) -> tuple[str, str]:
        """Novo pedido de conexão: (código para o QR, segredo que fica só no cookie da TV)."""
        agora = self._relogio()
        self._repo.apagar_pedidos_antigos(agora - timedelta(seconds=PEDIDO_VALIDADE))
        if self._repo.pedidos_abertos() >= MAX_PEDIDOS_ABERTOS:
            raise MuitosPedidos()
        codigo = self._sortear_codigo()
        while self._repo.codigo_de_pedido_em_uso(codigo):
            codigo = self._sortear_codigo()
        segredo = self._sortear_cracha()
        self._repo.inserir_pedido(codigo, hash_do_cracha(segredo), agora)
        return codigo, segredo

    def situacao_do_pedido(self, segredo: str | None) -> tuple[str, Tela | None]:
        """("vencido" | "aguardando" | "pronto", tela). No "pronto", o segredo do pedido vira o crachá da TV."""
        pedido = self._repo.pedido_pelo_segredo(hash_do_cracha(segredo)) if segredo else None
        if pedido is None or pedido.vencido(self._relogio()):
            return "vencido", None
        if pedido.tela_id is None:
            return "aguardando", None
        tela = self._repo.tela(pedido.tela_id)
        self._repo.apagar_pedido(pedido.id)
        if tela is None or not hmac.compare_digest(tela.aparelho_hash or "", pedido.segredo_hash):
            return "vencido", None   # a tela foi excluída ou outra TV ficou com ela
        return "pronto", tela

    def registrar_contato(self, tela: Tela, ip: str, navegador: str, exibindo: str | None = None,
                          mudar_exibindo: bool = False) -> None:
        agora = self._relogio()
        if tela.precisa_registrar_contato(agora, com_novidade=mudar_exibindo):
            self._repo.registrar_contato(tela.id, agora, ip[:45], navegador[:200], exibindo, mudar_exibindo)

    def marcar_fechada(self, tela: Tela) -> None:
        """A janela da TV foi fechada (ou recarregada): offline na hora."""
        self._repo.marcar_fechada(tela.id, self._relogio())

"""Casos de uso do painel de propagandas: cadastro, agenda, destinos, ações em lote e o que vai para cada TV.

Os arquivos (salvar e apagar do disco) ficam com a porta de entrada: aqui chega o nome no
disco e voltam as propagandas excluídas, para ela apagar os arquivos.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo

from ..erros import NaoEncontrado
from .exibicao import MAX_REGISTROS_POR_ENVIO, ler_registro
from .propaganda import (
    MAX_LETREIRO,
    MAX_NOME,
    Destinos,
    ErroDePropaganda,
    Programacao,
    Propaganda,
    ler_duracao,
    nova_ordem,
)
from .repositorio import RepositorioDePropagandas

PAUSADO, LETREIRO = "pausado", "letreiro"
CAMPOS_EM_LOTE = ("ativo", "duracao", "letreiro")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TelaDaPlaylist:
    id: int
    grupo_id: int | None = None
    letreiro: str | None = None   # o da tela; vazio = o geral da loja


@dataclass(frozen=True)
class Playlist:
    itens: list[Propaganda]
    letreiro: str | None
    pausado: bool = False


class ServicoDePropagandas:
    def __init__(self, repositorio: RepositorioDePropagandas, fuso: tzinfo,
                 relogio: Callable[[], datetime] = _agora) -> None:
        self._repo = repositorio
        self._fuso = fuso
        self._relogio = relogio

    def agora_local(self) -> datetime:
        return self._relogio().astimezone(self._fuso)

    # -- consulta ------------------------------------------------------------------

    def propaganda(self, propaganda_id: int) -> Propaganda:
        propaganda = self._repo.buscar(propaganda_id)
        if propaganda is None:
            raise NaoEncontrado("Propaganda não encontrada.")
        return propaganda

    def lista(self) -> tuple[list[Propaganda], dict[int, tuple[str, str]]]:
        """As propagandas na ordem de exibição e a situação de cada uma agora."""
        itens, agora = self._repo.listar(), self.agora_local()
        return itens, {item.id: item.situacao(agora) for item in itens}

    def destinos_da_loja(self, destinos: Destinos) -> Destinos:
        return destinos.so_da_loja(self._repo.telas_da_loja(), self._repo.grupos_da_loja())

    # -- cadastro e edição --------------------------------------------------------------

    def cadastrar(self, nome: str, arquivo: str, tipo: str, tamanho: int, duracao: int | str | None,
                  destinos: Destinos | None) -> int:
        """Nova propaganda no fim da lista. `destinos` None = todas as telas; vazio = nenhuma ainda."""
        escolhidos = None if destinos is None else self.destinos_da_loja(destinos)
        with self._repo.transacao():
            propaganda_id = self._repo.inserir(nome[:MAX_NOME], arquivo, tipo, tamanho, ler_duracao(duracao),
                                               para_todas=escolhidos is None)
            if escolhidos:
                self._repo.gravar_destinos(propaganda_id, escolhidos)
        return propaganda_id

    def atualizar(self, propaganda_id: int, programacao: Programacao) -> Propaganda:
        atual = self.propaganda(propaganda_id)
        programacao = Programacao(
            nome=programacao.nome.strip()[:MAX_NOME] or atual.nome,
            duracao=ler_duracao(programacao.duracao), ativo=programacao.ativo, inicio=programacao.inicio,
            fim=programacao.fim, dias_semana=programacao.dias_semana, hora_inicio=programacao.hora_inicio,
            hora_fim=programacao.hora_fim, para_todas=programacao.para_todas, letreiro=programacao.letreiro,
            destinos=Destinos() if programacao.para_todas else self.destinos_da_loja(programacao.destinos),
        )
        try:
            programacao.conferir()
        except ErroDePropaganda as erro:
            raise ErroDePropaganda(f"“{atual.nome}”: {erro}") from None
        with self._repo.transacao():
            self._repo.gravar_programacao(propaganda_id, programacao)
            self._repo.gravar_destinos(propaganda_id, programacao.destinos)
        return self.propaganda(propaganda_id)

    def mover(self, propaganda_id: int, direcao: str) -> None:
        with self._repo.transacao():
            ids = [item.id for item in self._repo.listar()]
            if propaganda_id not in ids:
                raise NaoEncontrado("Propaganda não encontrada.")
            ordem = nova_ordem(ids, propaganda_id, direcao)
            if ordem is not None:
                self._repo.gravar_ordem(ordem)

    def excluir(self, propaganda_id: int) -> Propaganda:
        """Tira do banco; devolve a propaganda para a porta de entrada apagar o arquivo."""
        propaganda = self.propaganda(propaganda_id)
        self._repo.excluir(propaganda_id)
        return propaganda

    # -- várias de uma vez --------------------------------------------------------------

    def marcadas(self, ids: Iterable[int]) -> list[Propaganda]:
        """As propagandas marcadas que são desta loja, na ordem da lista."""
        escolhidas = set(ids)
        itens = [item for item in self._repo.listar() if item.id in escolhidas]
        if not itens:
            raise ErroDePropaganda("Marque pelo menos uma propaganda na lista.")
        return itens

    def definir_em_lote(self, itens: list[Propaganda], campo: str, valor: object) -> None:
        if campo not in CAMPOS_EM_LOTE:
            raise ErroDePropaganda("Ação inválida.")
        if campo == "duracao":
            valor = ler_duracao(valor)  # type: ignore[arg-type]
        self._repo.definir([item.id for item in itens], campo, valor)

    def definir_destinos_em_lote(self, itens: list[Propaganda], modo: str, destinos: Destinos | None) -> None:
        """`destinos` None = todas as telas; senão troca, acrescenta ou tira das telas de cada uma."""
        if destinos is None:
            with self._repo.transacao():
                self._repo.definir([item.id for item in itens], "para_todas", True)
                for item in itens:
                    self._repo.gravar_destinos(item.id, Destinos())
            return
        escolhidos = self.destinos_da_loja(destinos)
        if not escolhidos:
            raise ErroDePropaganda("Marque pelo menos uma tela ou grupo.")
        with self._repo.transacao():
            for item in itens:
                atuais = Destinos() if item.para_todas else item.destinos  # "todas" não tem lista: parte do zero
                self._repo.definir([item.id], "para_todas", False)
                self._repo.gravar_destinos(item.id, atuais.combinar(modo, escolhidos))

    # -- ajustes gerais da loja ------------------------------------------------------------

    @property
    def pausado(self) -> bool:
        return self._repo.config(PAUSADO) == "1"

    def pausar(self, pausar: bool) -> None:
        """Pausa geral: as TVs da loja ficam sem propagandas até alguém retomar."""
        self._repo.gravar_config(PAUSADO, "1" if pausar else "")

    @property
    def letreiro(self) -> str:
        return self._repo.config(LETREIRO) or ""

    def gravar_letreiro(self, texto: str) -> None:
        self._repo.gravar_config(LETREIRO, (texto or "").strip()[:MAX_LETREIRO])

    # -- o que a TV recebe ---------------------------------------------------------------------

    def playlist(self, tela: TelaDaPlaylist | None) -> Playlist:
        """O que esta tela mostra agora (tela None = o player geral: só o que é para todas)."""
        if self.pausado:
            return Playlist([], "", pausado=True)
        agora = self.agora_local()
        itens = [item for item in self._repo.listar()
                 if item.no_ar(agora) and item.aparece_na(tela.id if tela else None, tela.grupo_id if tela else None)]
        letreiro = tela.letreiro if tela is not None and tela.letreiro else self.letreiro
        return Playlist(itens, letreiro)

    def nome_exibindo(self, propaganda_id: object) -> str | None:
        """O nome do que a TV diz que está mostrando (None se não for uma propaganda desta loja)."""
        if not isinstance(propaganda_id, int) or isinstance(propaganda_id, bool):
            return None
        return self._repo.nomes().get(propaganda_id)

    def registrar_exibicoes(self, tela_id: int, registros: list[object], reter_dias: int) -> tuple[int, int]:
        """Grava o que a TV exibiu (repetidos são ignorados). Devolve (recebidos, gravados)."""
        registros = registros[:MAX_REGISTROS_POR_ENVIO]
        agora = self._relogio()
        mais_antigo = agora - timedelta(days=reter_dias)
        nomes = self._repo.nomes()
        lidos = [ler_registro(r, agora, mais_antigo) for r in registros]
        validos = [(e, nomes.get(e.propaganda_id, "(propaganda excluída)")) for e in lidos if e is not None]
        self._repo.gravar_exibicoes(tela_id, validos)
        return len(registros), len(validos)

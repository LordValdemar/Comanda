"""Repositório das permissões e autorizações no SQLite da Comanda local (um estabelecimento só, sem empresa_id)."""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime

from src.domain.permissoes import Cadastro, Liberacao

from .datas import de_texto, para_texto

_CHAVE = "permissao.{}.{}"
_SELECT = (
    "SELECT a.*, u.usuario AS quem_usou, p.usuario AS quem_autorizou FROM autorizacoes a "
    "LEFT JOIN usuarios u ON u.id = a.usado_por LEFT JOIN usuarios p ON p.id = a.autorizado_por "
)
_VALENDO = "a.usado_em IS NOT NULL AND a.revogada_em IS NULL AND a.consumida_em IS NULL AND (a.modo != 'minutos' OR a.ate > ?)"


def _liberacao(linha: sqlite3.Row) -> Liberacao:
    criado_em = de_texto(linha["criado_em"])
    assert criado_em is not None
    return Liberacao(
        id=linha["id"], codigo=linha["codigo"], funcao=linha["funcao"], modo=linha["modo"], minutos=linha["minutos"],
        criado_em=criado_em, autorizado_por=linha["autorizado_por"], quem_autorizou=linha["quem_autorizou"],
        usado_por=linha["usado_por"], quem_usou=linha["quem_usou"], usado_em=de_texto(linha["usado_em"]),
        ate=de_texto(linha["ate"]), consumida_em=de_texto(linha["consumida_em"]),
        revogada_em=de_texto(linha["revogada_em"]),
    )


class RepositorioDePermissoesSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao
        self._na_transacao = False

    @contextmanager
    def transacao(self) -> Iterator[None]:
        if self._na_transacao:
            yield
            return
        with self._c:
            self._c.execute("BEGIN IMMEDIATE")
            self._na_transacao = True
            try:
                yield
            finally:
                self._na_transacao = False

    @contextmanager
    def _gravando(self) -> Iterator[None]:
        if self._na_transacao:
            yield
        else:
            with self._c:
                yield

    # -- tabela de permissões ----------------------------------------------------------

    def niveis_configurados(self) -> dict[tuple[str, str], int]:
        niveis: dict[tuple[str, str], int] = {}
        for linha in self._c.execute(
            "SELECT chave, valor FROM configuracoes WHERE chave LIKE 'permissao.%'"
        ):
            partes = linha["chave"].split(".", 2)
            if len(partes) == 3 and str(linha["valor"]).isdigit():
                niveis[(partes[1], partes[2])] = int(linha["valor"])
        return niveis

    def gravar_niveis(self, niveis: dict[tuple[str, str], int]) -> None:
        with self._gravando():
            self._c.executemany(
                "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                [(_CHAVE.format(funcao, papel), str(nivel)) for (funcao, papel), nivel in niveis.items()],
            )

    def cadastro(self, usuario_id: int) -> Cadastro | None:
        linha = self._c.execute(
            "SELECT id, usuario, papel, fecha_conta FROM usuarios WHERE id = ? AND ativo = 1", (usuario_id,)
        ).fetchone()
        if linha is None:
            return None
        return Cadastro(id=linha["id"], nome=linha["usuario"], papel=linha["papel"], fecha_conta=bool(linha["fecha_conta"]))

    # -- códigos e liberações -------------------------------------------------------------

    def apagar_antigas(self, antes_de: datetime) -> None:
        """Histórico velho sai; a "sem prazo" que ainda vale fica."""
        with self._gravando():
            self._c.execute(
                "DELETE FROM autorizacoes WHERE criado_em < ? "
                "AND NOT (modo = 'sempre' AND usado_em IS NOT NULL AND revogada_em IS NULL)",
                (para_texto(antes_de),),
            )

    def apagar_codigos_abertos(self, autorizador_id: int) -> None:
        with self._gravando():
            self._c.execute("DELETE FROM autorizacoes WHERE autorizado_por = ? AND usado_em IS NULL", (autorizador_id,))

    def inserir_codigo(self, codigo: str, funcao: str, autorizador_id: int, criado_em: datetime, modo: str,
                       minutos: int) -> int:
        with self._gravando():
            cursor = self._c.execute(
                "INSERT INTO autorizacoes (codigo, funcao, autorizado_por, criado_em, modo, minutos) VALUES (?, ?, ?, ?, ?, ?)",
                (codigo, funcao, autorizador_id, para_texto(criado_em), modo, minutos),
            )
        return int(cursor.lastrowid or 0)

    def _uma(self, onde: str, parametros: tuple[object, ...]) -> Liberacao | None:
        linha = self._c.execute(_SELECT + f"WHERE {onde}", parametros).fetchone()
        return None if linha is None else _liberacao(linha)

    def por_codigo(self, codigo: str) -> Liberacao | None:
        return self._uma("a.codigo = ?", (codigo,))

    def por_id(self, liberacao_id: int) -> Liberacao | None:
        return self._uma("a.id = ?", (liberacao_id,))

    def marcar_usado(self, liberacao_id: int, usuario_id: int, usado_em: datetime, ate: datetime | None) -> bool:
        """Só um consegue: quem chegar depois (mesmo um instante) encontra o código já usado."""
        with self._gravando():
            alterados = self._c.execute(
                "UPDATE autorizacoes SET usado_por = ?, usado_em = ?, ate = ? "
                "WHERE id = ? AND usado_em IS NULL",
                (usuario_id, para_texto(usado_em), None if ate is None else para_texto(ate), liberacao_id),
            ).rowcount
        return bool(alterados)

    def vigente(self, usuario_id: int, funcao: str, agora: datetime) -> Liberacao | None:
        # Prefere a que tem prazo ou é sem prazo: a de "uma vez" fica guardada para quando precisar.
        return self._uma(f"a.usado_por = ? AND a.funcao = ? AND {_VALENDO} ORDER BY a.modo = 'uma' LIMIT 1",
                         (usuario_id, funcao, para_texto(agora)))

    def consumir(self, liberacao_ids: Iterable[int], agora: datetime) -> None:
        with self._gravando():
            self._c.executemany(
                "UPDATE autorizacoes SET consumida_em = ? WHERE id = ? AND consumida_em IS NULL",
                [(para_texto(agora), liberacao_id) for liberacao_id in liberacao_ids],
            )

    def revogar(self, liberacao_id: int, agora: datetime, encerrada_por: int) -> None:
        with self._gravando():
            self._c.execute(
                "UPDATE autorizacoes SET revogada_em = ?, encerrada_por = ? "
                "WHERE id = ? AND revogada_em IS NULL",
                (para_texto(agora), encerrada_por, liberacao_id),
            )

    def ativas(self, agora: datetime, autorizador_id: int | None) -> list[Liberacao]:
        return [_liberacao(linha) for linha in self._c.execute(
            _SELECT + f"WHERE {_VALENDO} AND (? IS NULL OR a.autorizado_por = ?) ORDER BY a.usado_em DESC",
            (para_texto(agora), autorizador_id, autorizador_id),
        )]

    def recentes(self, autorizador_id: int | None, limite: int) -> list[Liberacao]:
        return [_liberacao(linha) for linha in self._c.execute(
            _SELECT + "WHERE a.usado_em IS NOT NULL AND (? IS NULL OR a.autorizado_por = ?) ORDER BY a.usado_em DESC LIMIT ?",
            (autorizador_id, autorizador_id, limite),
        )]

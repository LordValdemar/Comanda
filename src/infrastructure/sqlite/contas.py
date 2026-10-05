"""Contas de usuário no SQLite da Comanda local (tabela usuarios, sem empresas)."""

import sqlite3
from typing import Any

from src.domain.contas import ContaLocal


def _conta(linha: sqlite3.Row) -> ContaLocal:
    return ContaLocal(
        id=linha["id"], usuario=linha["usuario"], papel=linha["papel"], senha_hash=linha["senha_hash"],
        token_sessao=linha["token_sessao"], ativo=bool(linha["ativo"]), fecha_conta=bool(linha["fecha_conta"]),
        totp_segredo=linha["totp_segredo"], totp_ultimo=int(linha["totp_ultimo"] or 0),
    )


class RepositorioDeContasSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    def _gravar(self, sql: str, parametros: tuple[object, ...]) -> int:
        with self._c:
            return int(self._c.execute(sql, parametros).lastrowid or 0)

    # -- leitura ------------------------------------------------------------------------------

    def conta(self, usuario_id: int) -> ContaLocal | None:
        linha = self._c.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return None if linha is None else _conta(linha)

    def conta_com_nome(self, nome: str) -> ContaLocal | None:
        linha = self._c.execute("SELECT * FROM usuarios WHERE usuario = ?", (nome,)).fetchone()
        return None if linha is None else _conta(linha)

    def existe_alguem(self) -> bool:
        return self._c.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None

    def nome_em_uso(self, nome: str) -> bool:
        return self._c.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (nome,)).fetchone() is not None

    def admins_ativos(self) -> int:
        return int(self._c.execute("SELECT COUNT(*) FROM usuarios WHERE papel = 'admin' AND ativo = 1").fetchone()[0])

    # -- gravação -------------------------------------------------------------------------------

    def inserir(self, nome: str, senha_hash: str, papel: str, token: str) -> int:
        return self._gravar("INSERT INTO usuarios (usuario, senha_hash, papel, token_sessao) VALUES (?, ?, ?, ?)",
                            (nome, senha_hash, papel, token))

    def gravar_senha(self, usuario_id: int, senha_hash: str, token: str) -> None:
        self._gravar("UPDATE usuarios SET senha_hash = ?, token_sessao = ? WHERE id = ?", (senha_hash, token, usuario_id))

    def ativar_totp(self, usuario_id: int, segredo: str, contador: int) -> None:
        self._gravar("UPDATE usuarios SET totp_segredo = ?, totp_ultimo = ? WHERE id = ?", (segredo, contador, usuario_id))

    def desativar_totp(self, usuario_id: int, token: str) -> None:
        self._gravar("UPDATE usuarios SET totp_segredo = NULL, totp_ultimo = 0, token_sessao = ? WHERE id = ?",
                     (token, usuario_id))

    def gravar_totp_ultimo(self, usuario_id: int, contador: int) -> None:
        self._gravar("UPDATE usuarios SET totp_ultimo = ? WHERE id = ?", (contador, usuario_id))

    def mudar_papel(self, usuario_id: int, papel: str) -> None:
        """"Fecha contas" é uma permissão extra do garçom: não acompanha a pessoa para outro papel."""
        self._gravar("UPDATE usuarios SET papel = ?, fecha_conta = CASE WHEN ? = 'garcom' THEN fecha_conta ELSE 0 END "
                     "WHERE id = ?", (papel, papel, usuario_id))

    def definir_fecha_conta(self, usuario_id: int, pode: bool) -> None:
        self._gravar("UPDATE usuarios SET fecha_conta = ? WHERE id = ?", (int(pode), usuario_id))

    def definir_ativo(self, usuario_id: int, ativo: bool, token: str) -> None:
        self._gravar("UPDATE usuarios SET ativo = ?, token_sessao = ? WHERE id = ?", (int(ativo), token, usuario_id))


class ConsultasDeUsuarios:
    """O que as telas leem dos usuários (a pessoa logada e a lista da equipe)."""

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    def usuario(self, usuario_id: int) -> dict[str, Any] | None:
        linha = self._c.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return None if linha is None else dict(linha)

    def equipe(self) -> list[dict[str, Any]]:
        """Todos, os ativos primeiro."""
        return [dict(linha) for linha in self._c.execute("SELECT * FROM usuarios ORDER BY ativo DESC, usuario")]

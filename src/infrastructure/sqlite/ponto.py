"""Repositório do ponto no SQLite da Comanda local (ponto_registros, horários em usuarios, ajustes em configuracoes)."""

import secrets
import sqlite3
from datetime import datetime

from src.domain.horario import Horario
from src.domain.ponto import Funcionario, RegistroDePonto

from .datas import de_texto, para_texto

ESTABELECIMENTO = 1   # o QR do ponto é assinado com a "loja"; aqui só existe uma


def _funcionario(linha: sqlite3.Row) -> Funcionario:
    return Funcionario(
        id=linha["id"], nome=linha["usuario"], papel=linha["papel"], exige_ponto=bool(linha["exige_ponto"]),
        horario=Horario(linha["horario_dias"] or "", linha["horario_inicio"], linha["horario_fim"]),
    )


def _registro(linha: sqlite3.Row) -> RegistroDePonto:
    entrada = de_texto(linha["entrada"])
    assert entrada is not None
    return RegistroDePonto(
        id=linha["id"], usuario_id=linha["usuario_id"], usuario_nome=linha["usuario_nome"], entrada=entrada,
        saida=de_texto(linha["saida"]), motivo_saida=linha["motivo_saida"],
        encerrado_por_nome=linha["encerrado_por_nome"],
    )


_REGISTROS = (
    "SELECT p.*, u.usuario AS encerrado_por_nome FROM ponto_registros p LEFT JOIN usuarios u ON u.id = p.encerrado_por "
)


class RepositorioDePontoSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    @property
    def empresa_id(self) -> int:
        return ESTABELECIMENTO

    # -- ajustes ---------------------------------------------------------------------------

    def config(self, chave: str) -> str | None:
        linha = self._c.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
        return None if linha is None else str(linha["valor"])

    def gravar_config(self, chave: str, valor: str) -> None:
        with self._c:
            self._c.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
                            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, valor))

    def trocar_geracao(self, de: int, para: int) -> bool:
        """Troca atômica: se duas pessoas lerem o mesmo QR ao mesmo tempo, só uma consegue."""
        with self._c:
            self._c.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('ponto_qr_geracao', '0')")
            trocou = self._c.execute(
                "UPDATE configuracoes SET valor = ? WHERE chave = 'ponto_qr_geracao' AND valor = ?", (str(para), str(de))
            ).rowcount
        return bool(trocou == 1)

    # -- pessoas ------------------------------------------------------------------------------

    def funcionario(self, usuario_id: int) -> Funcionario | None:
        linha = self._c.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return None if linha is None else _funcionario(linha)

    def funcionarios_com_ponto_aberto(self) -> list[Funcionario]:
        return [_funcionario(linha) for linha in self._c.execute(
            "SELECT u.* FROM ponto_registros p JOIN usuarios u ON u.id = p.usuario_id WHERE p.saida IS NULL")]

    def gravar_horario(self, usuario_id: int, horario: Horario, exige_ponto: bool) -> None:
        with self._c:
            self._c.execute(
                "UPDATE usuarios SET horario_dias = ?, horario_inicio = ?, horario_fim = ?, exige_ponto = ? WHERE id = ?",
                (horario.dias, horario.inicio, horario.fim, int(exige_ponto), usuario_id),
            )

    def encerrar_sessoes(self, usuario_id: int) -> None:
        """Troca o token de sessão: a pessoa sai de todos os aparelhos."""
        with self._c:
            self._c.execute("UPDATE usuarios SET token_sessao = ? WHERE id = ?", (secrets.token_hex(16), usuario_id))

    # -- registros ----------------------------------------------------------------------------------

    def aberto(self, usuario_id: int) -> RegistroDePonto | None:
        linha = self._c.execute(_REGISTROS + "WHERE p.usuario_id = ? AND p.saida IS NULL", (usuario_id,)).fetchone()
        return None if linha is None else _registro(linha)

    def abrir(self, funcionario: Funcionario, entrada: datetime, ip: str) -> bool:
        """INSERT OR IGNORE: o índice único deixa só um ponto aberto por pessoa (dois toques = um registro)."""
        with self._c:
            inseridos = self._c.execute(
                "INSERT OR IGNORE INTO ponto_registros (usuario_id, usuario_nome, entrada, ip) VALUES (?, ?, ?, ?)",
                (funcionario.id, funcionario.nome, para_texto(entrada), ip),
            ).rowcount
        return bool(inseridos)

    def fechar(self, usuario_id: int, saida: datetime, motivo: str, encerrado_por: int | None) -> int:
        with self._c:
            return int(self._c.execute(
                "UPDATE ponto_registros SET saida = ?, motivo_saida = ?, encerrado_por = ? WHERE usuario_id = ? AND saida IS NULL",
                (para_texto(saida), motivo, encerrado_por, usuario_id),
            ).rowcount)

    def registros(self, de: datetime, ate: datetime, usuario_id: int | None) -> list[RegistroDePonto]:
        filtro = ""
        parametros: list[object] = [para_texto(de), para_texto(ate)]
        if usuario_id:
            filtro, parametros = " AND p.usuario_id = ?", [*parametros, usuario_id]
        return [_registro(linha) for linha in self._c.execute(
            _REGISTROS + f"WHERE p.entrada >= ? AND p.entrada < ?{filtro} ORDER BY p.entrada DESC", parametros)]

"""O que a tela da equipe do ponto mostra (só leitura), no banco da Comanda local."""

import sqlite3
from typing import Any

Linha = dict[str, Any]


class ConsultasDoPonto:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    def equipe(self) -> list[Linha]:
        """As pessoas ativas e desde quando estão trabalhando (se estão); o administrador por último."""
        return [dict(linha) for linha in self._c.execute(
            "SELECT u.*, p.entrada AS trabalhando_desde FROM usuarios u "
            "LEFT JOIN ponto_registros p ON p.usuario_id = u.id AND p.saida IS NULL "
            "WHERE u.ativo = 1 ORDER BY u.papel = 'admin', u.usuario")]

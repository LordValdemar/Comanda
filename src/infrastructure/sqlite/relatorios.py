"""Consultas do relatório de vendas no SQLite da Comanda local (uma loja só)."""

import sqlite3

from src.domain.relatorios.vendas import (
    ComandaEncerrada,
    ItemCancelado,
    TaxaDaComanda,
    VendaPorForma,
    VendaPorGarcom,
    VendaPorProduto,
)

_FECHADAS = "c.status = 'fechada' AND c.fechada_em >= ? AND c.fechada_em < ?"


class RepositorioDeVendasSQLite:
    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._c = conexao

    def _consulta(self, sql: str, de: str, ate: str) -> list[sqlite3.Row]:
        return self._c.execute(sql, (de, ate)).fetchall()

    def totais(self, de: str, ate: str) -> tuple[int, int, int]:
        linha = self._consulta(
            "SELECT COUNT(*), COALESCE(SUM(c.total_centavos), 0), COALESCE(SUM(c.desconto_centavos), 0) "
            f"FROM comandas c WHERE {_FECHADAS}", de, ate)[0]
        return int(linha[0]), int(linha[1]), int(linha[2])

    def taxas(self, de: str, ate: str) -> list[TaxaDaComanda]:
        return [TaxaDaComanda(linha["taxa_centavos"], bool(linha["cobrar_taxa"]), linha["taxa_percentual"], int(linha["sub"]))
                for linha in self._consulta(
                    "SELECT c.taxa_centavos, c.cobrar_taxa, c.taxa_percentual, COALESCE(s.sub, 0) AS sub FROM comandas c "
                    "LEFT JOIN (SELECT comanda_id, SUM(preco_centavos * quantidade) AS sub FROM itens "
                    f"WHERE status != 'cancelado' GROUP BY comanda_id) s ON s.comanda_id = c.id WHERE {_FECHADAS}", de, ate)]

    def por_forma(self, de: str, ate: str) -> list[VendaPorForma]:
        return [VendaPorForma(linha["forma"], linha["quantidade"], linha["valor"]) for linha in self._consulta(
            "SELECT p.forma, COUNT(*) AS quantidade, SUM(p.valor_centavos) AS valor FROM pagamentos p "
            f"JOIN comandas c ON c.id = p.comanda_id WHERE {_FECHADAS} GROUP BY p.forma ORDER BY valor DESC", de, ate)]

    def por_produto(self, de: str, ate: str) -> list[VendaPorProduto]:
        return [VendaPorProduto(linha["nome"], linha["quantidade"], linha["valor"]) for linha in self._consulta(
            "SELECT i.nome, SUM(i.quantidade) AS quantidade, SUM(i.quantidade * i.preco_centavos) AS valor FROM itens i "
            f"JOIN comandas c ON c.id = i.comanda_id WHERE {_FECHADAS} AND i.status != 'cancelado' "
            "GROUP BY i.nome ORDER BY quantidade DESC, valor DESC", de, ate)]

    def por_garcom(self, de: str, ate: str) -> list[VendaPorGarcom]:
        return [VendaPorGarcom(linha["garcom"], linha["valor"]) for linha in self._consulta(
            "SELECT COALESCE(u.usuario, '—') AS garcom, SUM(i.quantidade * i.preco_centavos) AS valor FROM itens i "
            "JOIN comandas c ON c.id = i.comanda_id LEFT JOIN usuarios u ON u.id = i.lancado_por "
            f"WHERE {_FECHADAS} AND i.status != 'cancelado' GROUP BY u.usuario ORDER BY valor DESC", de, ate)]

    def cancelados(self, de: str, ate: str) -> list[ItemCancelado]:
        return [ItemCancelado(linha["comanda_id"], linha["numero"], linha["nome"], linha["quantidade"],
                              linha["motivo_cancelamento"], linha["cancelado_por_nome"], linha["atualizado_em"])
                for linha in self._consulta(
                    "SELECT i.*, c.numero, u.usuario AS cancelado_por_nome FROM itens i "
                    "JOIN comandas c ON c.id = i.comanda_id LEFT JOIN usuarios u ON u.id = i.cancelado_por "
                    "WHERE i.status = 'cancelado' AND i.atualizado_em >= ? AND i.atualizado_em < ? "
                    "ORDER BY i.atualizado_em", de, ate)]

    def abertas(self) -> int:
        return int(self._c.execute("SELECT COUNT(*) FROM comandas WHERE status = 'aberta'").fetchone()[0])

    def encerradas(self, de: str, ate: str) -> list[ComandaEncerrada]:
        resultado = []
        for c in self._consulta(
            "SELECT c.*, GROUP_CONCAT(p.forma || ':' || p.valor_centavos, ' ') AS pagamentos, "
            "(SELECT usuario FROM usuarios WHERE id = c.garcom_id) AS garcom_nome FROM comandas c "
            "LEFT JOIN pagamentos p ON p.comanda_id = c.id "
            "WHERE c.status != 'aberta' AND c.fechada_em >= ? AND c.fechada_em < ? "
            "GROUP BY c.id ORDER BY c.fechada_em", de, ate,
        ):
            pagamentos = [(forma, int(valor)) for forma, _, valor in (p.partition(":") for p in (c["pagamentos"] or "").split())]
            resultado.append(ComandaEncerrada(
                numero=c["numero"], mesa=c["mesa"], cliente=c["cliente"], garcom=c["garcom_nome"], status=c["status"],
                aberta_em=c["aberta_em"], fechada_em=c["fechada_em"], desconto=c["desconto_centavos"],
                total=c["total_centavos"], pagamentos=pagamentos, motivo_cancelamento=c["motivo_cancelamento"],
            ))
        return resultado

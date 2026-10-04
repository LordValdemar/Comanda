"""Módulos da plataforma (Painel de Propagandas e Comanda) e quais uma empresa usa."""

from collections.abc import Iterable

MODULOS = {
    "painel": "Painel de Propagandas",
    "comanda": "Comanda",
}
DESCRICOES = {
    "painel": "Propagandas nas TVs da loja, com agendamento e relatórios de exibição.",
    "comanda": "Pedidos pelo celular dos garçons, tela da cozinha, fechamento de conta e relatórios de vendas.",
}


def ler(texto: str | None) -> set[str]:
    """'painel,comanda' → {'painel', 'comanda'} (ignora nomes desconhecidos)."""
    return {m.strip() for m in (texto or "").split(",") if m.strip() in MODULOS}


def juntar(modulos: Iterable[str]) -> str:
    """O texto gravado no banco, sempre na mesma ordem."""
    escolhidos = set(modulos)
    return ",".join(m for m in MODULOS if m in escolhidos)


def em_ordem(texto: str | None) -> list[str]:
    """Os módulos de um plano, na ordem de exibição."""
    escolhidos = ler(texto)
    return [m for m in MODULOS if m in escolhidos]


def da_empresa(principal: bool, liberados: str | None, do_plano: str | None) -> set[str]:
    """Os do plano mais os liberados à mão pela plataforma. A empresa principal usa todos."""
    if principal:
        return set(MODULOS)
    return ler(liberados) | ler(do_plano)

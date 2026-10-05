"""A tela da cozinha: os itens agrupados por comanda, o que falta fazer no alto."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

SITUACOES_DA_COZINHA = ("pendente", "preparando", "pronto", "entregue")   # a cozinha pode voltar uma etapa
RECENTES_MINUTOS = 30   # itens entregues que ainda aparecem embaixo, para desfazer
RECENTES_MAXIMO = 15


def agrupar_por_comanda(itens: Iterable[Mapping[str, Any]], hora: Callable[[str], str],
                        minutos_desde: Callable[[str], int]) -> list[dict[str, Any]]:
    """Itens (em ordem de chegada) → comandas com seus itens. Comandas com tudo pronto vão para o fim."""
    grupos: dict[int, dict[str, Any]] = {}
    for item in itens:
        grupo = grupos.setdefault(item["comanda_id"], {
            "comanda_id": item["comanda_id"], "numero": item["numero"], "mesa": item["mesa"] or "",
            "minutos": minutos_desde(item["lancado_em"]), "itens": [],
        })
        grupo["itens"].append({
            "id": item["id"], "nome": item["nome"], "quantidade": item["quantidade"],
            "observacao": item["observacao"] or "", "status": item["status"], "hora": hora(item["lancado_em"]),
            "minutos": minutos_desde(item["lancado_em"]), "garcom": item["garcom"] or "",
        })
    resultado = list(grupos.values())
    for grupo in resultado:
        grupo["tudo_pronto"] = all(i["status"] == "pronto" for i in grupo["itens"])
    resultado.sort(key=lambda grupo: grupo["tudo_pronto"])   # sort estável: a ordem de chegada se mantém
    return resultado


def entregues(itens: Iterable[Mapping[str, Any]], hora: Callable[[str], str]) -> list[dict[str, Any]]:
    """Os entregues há pouco, como a tela mostra (se foi engano, a cozinha traz de volta)."""
    return [{"id": i["id"], "nome": i["nome"], "quantidade": i["quantidade"], "numero": i["numero"],
             "mesa": i["mesa"] or "", "hora": hora(i["atualizado_em"])} for i in itens]

"""Lê o arquivo configuracao.env (CHAVE=valor), para quem não quer usar variáveis de ambiente.

Útil principalmente no Windows. Variáveis de ambiente já definidas têm prioridade
sobre o arquivo.
"""

import os

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO_PADRAO = os.path.join(PASTA_PROJETO, "configuracao.env")


def _valor(texto):
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "'\"":
        return texto[1:-1]  # aspas simples ou duplas em volta (ex.: valores com espaço ou "$")
    return texto.split(" #", 1)[0].strip()  # comentário no fim da linha


def ler(caminho):
    """Retorna {CHAVE: valor} do arquivo. Linhas vazias e começadas com # são ignoradas."""
    valores = {}
    with open(caminho, encoding="utf-8-sig") as arquivo:  # -sig: aceita arquivo salvo pelo Bloco de Notas
        for numero, linha in enumerate(arquivo, start=1):
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            if linha.startswith("export "):
                linha = linha[len("export "):]
            chave, separador, valor = linha.partition("=")
            chave = chave.strip()
            if not separador or not chave.replace("_", "").isalnum():
                raise ValueError(f"{caminho}, linha {numero}: use o formato CHAVE=valor")
            valores[chave] = _valor(valor)
    return valores


def carregar(caminho=None):
    """Aplica o arquivo nas variáveis de ambiente (sem sobrescrever as já definidas)."""
    caminho = caminho or os.environ.get("ARQUIVO_CONFIG") or ARQUIVO_PADRAO
    if not os.path.exists(caminho):
        return None
    for chave, valor in ler(caminho).items():
        if valor != "":
            os.environ.setdefault(chave, valor)
    return caminho

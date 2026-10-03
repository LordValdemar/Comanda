"""Aponta o nome da Comanda (ex.: comanda.sualoja.com.br) para o IP interno do servidor, no DNS da Cloudflare.

Usado por deploy/ativar-https.sh. A chave vem da variável CLOUDFLARE_API_TOKEN.

    python3 cloudflare.py comanda.sualoja.com.br 192.168.0.10

Só usa a biblioteca padrão do Python (roda antes de existir o ambiente da Comanda).
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("CLOUDFLARE_API", "https://api.cloudflare.com/client/v4")


class ErroCloudflare(Exception):
    pass


def chamar(metodo, caminho, dados=None):
    pedido = urllib.request.Request(
        API + caminho,
        method=metodo,
        data=json.dumps(dados).encode() if dados is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            corpo = json.load(resposta)
    except urllib.error.HTTPError as erro:
        try:
            corpo = json.load(erro)
        except ValueError:
            raise ErroCloudflare(f"a Cloudflare respondeu {erro.code}") from None
    except (urllib.error.URLError, TimeoutError) as erro:
        raise ErroCloudflare(f"sem conexão com a Cloudflare ({erro})") from None
    if not corpo.get("success"):
        mensagens = "; ".join(e.get("message", "") for e in corpo.get("errors", [])) or "erro desconhecido"
        raise ErroCloudflare(mensagens)
    return corpo["result"]


def achar_zona(nome):
    """A zona (domínio) da Cloudflare que contém o nome: comanda.loja.com.br → loja.com.br."""
    partes = nome.split(".")
    for i in range(len(partes) - 1):
        candidato = ".".join(partes[i:])
        zonas = chamar("GET", f"/zones?name={candidato}")
        if zonas:
            return zonas[0]
    return None


def apontar(nome, ip):
    chamar("GET", "/user/tokens/verify")
    zona = achar_zona(nome)
    if zona is None:
        raise ErroCloudflare(
            "o domínio não está nesta conta da Cloudflare (ou a chave não tem acesso a ele). "
            "Confira se o site foi adicionado na Cloudflare e se a chave tem a permissão Zona > Zona > Ler"
        )
    if zona.get("status") != "active":
        print(f"!!  Aviso: o domínio {zona['name']} ainda está “{zona.get('status')}” na Cloudflare. "
              "Os servidores DNS do registro.br precisam apontar para a Cloudflare (pode levar algumas horas).")
    registros = chamar("GET", f"/zones/{zona['id']}/dns_records?type=A&name={nome}")
    # proxied=False: a Cloudflare só responde o IP; o tráfego não passa por ela (nem conseguiria, o IP é interno).
    dados = {"type": "A", "name": nome, "content": ip, "ttl": 1, "proxied": False,
             "comment": "Comanda (gerado por deploy/ativar-https.sh)"}
    if registros:
        chamar("PUT", f"/zones/{zona['id']}/dns_records/{registros[0]['id']}", dados)
        print(f"==> DNS: {nome} atualizado para {ip}")
    else:
        chamar("POST", f"/zones/{zona['id']}/dns_records", dados)
        print(f"==> DNS: {nome} criado apontando para {ip}")


def main():
    if len(sys.argv) != 3 or not os.environ.get("CLOUDFLARE_API_TOKEN"):
        sys.exit("uso: CLOUDFLARE_API_TOKEN=... python3 cloudflare.py NOME IP")
    try:
        apontar(sys.argv[1], sys.argv[2])
    except ErroCloudflare as erro:
        sys.exit(f"Cloudflare: {erro}")


if __name__ == "__main__":
    main()

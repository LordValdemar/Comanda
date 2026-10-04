"""Cadastro da empresa: código da loja, CPF/CNPJ, contato, endereço, logo e e-mails de alerta."""

import base64
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from ..documentos import documento_valido, so_numeros
from ..erros import ErroDeDominio

UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
LOGO_MAX_BYTES = 300 * 1024  # o logo vai junto em cada cupom: pequeno imprime melhor e mais rápido
TIPOS_DE_LOGO = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}
# Campos de texto (coluna em empresas, tamanho máximo).
CAMPOS = (("razao_social", 120), ("email", 120), ("telefone", 20), ("cep", 9), ("logradouro", 120), ("numero", 20),
          ("complemento", 60), ("bairro", 60), ("cidade", 60), ("uf", 2))
COLUNAS = frozenset(campo for campo, _ in CAMPOS) | {"documento", "logo"}   # o que o cadastro grava em empresas
NOME_MAX = 100

CODIGO_VALIDO = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
CODIGOS_RESERVADOS = frozenset({"admin", "api", "plataforma", "login", "entrar", "cadastro", "conta", "planos", "static",
                                "suporte"})
AVISO_CODIGO = "O código da loja usa só letras minúsculas, números e hífen (de 3 a 40), ex.: padeiro-lanches."


class CadastroInvalido(ErroDeDominio):
    pass


def codigo_valido(codigo: str) -> bool:
    return bool(CODIGO_VALIDO.match(codigo)) and codigo not in CODIGOS_RESERVADOS


def codigo_do_nome(nome: str) -> str:
    """"Padeiro Lanches" → "padeiro-lanches" (sem garantir que está livre)."""
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40].strip("-") or "loja"


def ler_dados(formulario: Mapping[str, str]) -> dict[str, str]:
    """Campos do cadastro, conferidos. Devolve {coluna: valor} (só os que vieram) ou levanta CadastroInvalido."""
    dados = {campo: (formulario.get(campo) or "").strip()[:tamanho] for campo, tamanho in CAMPOS if campo in formulario}
    if "documento" in formulario:
        documento = so_numeros(formulario.get("documento"))
        if documento and not documento_valido(documento):
            raise CadastroInvalido("Confira o CPF ou CNPJ: os dígitos não conferem.")
        dados["documento"] = documento
    if dados.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", dados["email"]):
        raise CadastroInvalido("Confira o e-mail da empresa.")
    if dados.get("telefone"):
        numeros = so_numeros(dados["telefone"])
        if len(numeros) not in (10, 11):
            raise CadastroInvalido("Informe o telefone com DDD, ex.: (99) 98436-9495.")
        dados["telefone"] = f"({numeros[:2]}) {numeros[2:-4]}-{numeros[-4:]}"
    if dados.get("cep"):
        numeros = so_numeros(dados["cep"])
        if len(numeros) != 8:
            raise CadastroInvalido("O CEP tem 8 números.")
        dados["cep"] = f"{numeros[:5]}-{numeros[5:]}"
    if "uf" in dados:
        dados["uf"] = dados["uf"].upper()
        if dados["uf"] and dados["uf"] not in UFS:
            raise CadastroInvalido("Escolha o estado (UF) da lista.")
    return dados


def ler_logo(conteudo: bytes) -> str:
    """PNG ou JPG pequeno → data URI. Levanta CadastroInvalido se não servir.

    Quem lê o arquivo enviado lê no máximo LOGO_MAX_BYTES + 1 bytes (para saber se passou do limite).
    """
    if len(conteudo) > LOGO_MAX_BYTES:
        raise CadastroInvalido("O logo pode ter até 300 KB. Diminua a imagem e envie de novo.")
    tipo = next((t for inicio, t in TIPOS_DE_LOGO.items() if conteudo.startswith(inicio)), None)
    if tipo is None:
        raise CadastroInvalido("O logo precisa ser uma imagem PNG ou JPG.")
    return f"data:{tipo};base64,{base64.b64encode(conteudo).decode()}"


def ler_emails(texto: str | None) -> list[str]:
    """E-mails de alerta separados por vírgula."""
    emails = [e.strip() for e in (texto or "").split(",") if e.strip()]
    if any("@" not in e or " " in e for e in emails):
        raise CadastroInvalido("Confira os e-mails de alerta (separe por vírgula).")
    return emails


def documento_formatado(documento: str | None) -> str:
    d = so_numeros(documento)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return documento or ""


def endereco_completo(empresa: Mapping[str, Any]) -> str:
    """'Travessa Manoel de Oliveira Gomes, 03 - Centro - Dom Pedro/MA'."""
    rua = ", ".join(p for p in (empresa["logradouro"], empresa["numero"]) if p)
    if rua and empresa["complemento"]:
        rua += f" ({empresa['complemento']})"
    cidade = "/".join(p for p in (empresa["cidade"], empresa["uf"]) if p)
    return " - ".join(p for p in (rua, empresa["bairro"], cidade) if p)

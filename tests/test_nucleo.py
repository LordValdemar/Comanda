"""O núcleo (src/domain) é uma cópia da plataforma: confere que ninguém o mudou aqui.

Este arquivo também é copiado pela ferramenta da plataforma (ferramentas/copiar_nucleo.py).
Para mudar uma regra de negócio: mude na plataforma-comanda, rode lá
`python ferramentas/copiar_nucleo.py <este repositório>` e faça o commit aqui.
"""

import hashlib
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _impressao_digital(raiz):
    soma = hashlib.sha256()
    arquivos = [raiz / "src" / "__init__.py", *sorted((raiz / "src" / "domain").rglob("*.py"))]
    for caminho in arquivos:
        soma.update(caminho.relative_to(raiz).as_posix().encode() + b"\0" + caminho.read_bytes() + b"\0")
    return soma.hexdigest()


def test_nucleo_igual_ao_da_plataforma():
    registro = json.loads((RAIZ / "src" / "nucleo.json").read_text(encoding="utf-8"))
    assert _impressao_digital(RAIZ) == registro["impressao_digital"], (
        "src/domain foi mudado aqui. As regras são da plataforma-comanda: mude lá e copie de novo "
        "com ferramentas/copiar_nucleo.py."
    )

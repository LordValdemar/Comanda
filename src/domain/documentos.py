"""CPF e CNPJ (e outros campos que guardam só números)."""


def so_numeros(texto: str | None) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def _digito(numeros: str, pesos: list[int]) -> str:
    resto = sum(int(n) * p for n, p in zip(numeros, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def documento_valido(documento: str | None) -> bool:
    """Confere os dígitos verificadores de CPF (11 dígitos) ou CNPJ (14 dígitos)."""
    d = so_numeros(documento)
    if len(d) == 11 and len(set(d)) > 1:
        return d[9] == _digito(d[:9], list(range(10, 1, -1))) and d[10] == _digito(d[:10], list(range(11, 1, -1)))
    if len(d) == 14 and len(set(d)) > 1:
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        return d[12] == _digito(d[:12], pesos) and d[13] == _digito(d[:13], [6, *pesos])
    return False

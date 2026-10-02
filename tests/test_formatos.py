import pytest

from comanda.formatos import ValorInvalido, entrada_reais, ler_reais, reais


def test_reais():
    assert reais(0) == "R$ 0,00"
    assert reais(1250) == "R$ 12,50"
    assert reais(123456789) == "R$ 1.234.567,89"
    assert reais(-500) == "-R$ 5,00"


@pytest.mark.parametrize("texto, centavos", [
    ("12,50", 1250), ("12.50", 1250), ("12", 1200), ("R$ 1.234,5", 123450), ("0,05", 5), ("", 0), ("1.234", 123400),
])
def test_ler_reais(texto, centavos):
    assert ler_reais(texto) == centavos


@pytest.mark.parametrize("texto", ["abc", "12,345", "-3", "1e5"])
def test_ler_reais_invalido(texto):
    with pytest.raises(ValorInvalido):
        ler_reais(texto)


def test_ler_reais_sem_zero():
    with pytest.raises(ValorInvalido):
        ler_reais("0", permitir_zero=False)


def test_entrada_reais():
    assert entrada_reais(1250) == "12,50"
    assert entrada_reais(5) == "0,05"

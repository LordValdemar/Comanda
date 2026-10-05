"""Contas no SQLite da Comanda local (regras do núcleo, hash de senha real): desativar, último administrador e 2FA."""

import pytest

from comanda import db
from comanda.auth import PAPEIS
from src.domain import totp
from src.domain.contas import ErroUsuario, ServicoDeContasLocais
from src.infrastructure.senhas import SenhasWerkzeug
from src.infrastructure.sqlite import ConsultasDeUsuarios, RepositorioDeContasSQLite


@pytest.fixture
def contas(app):
    conexao = db.conectar(app.config["BANCO"])
    yield ServicoDeContasLocais(RepositorioDeContasSQLite(conexao), SenhasWerkzeug(), PAPEIS), conexao
    conexao.close()


def test_equipe_no_banco(contas):
    servico, conexao = contas
    dono, ze = servico.criar("dono", "123456", "admin"), servico.criar("ze", "123456")
    assert "123456" not in conexao.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (ze,)).fetchone()[0]
    with pytest.raises(ErroUsuario, match="pelo menos um administrador"):
        servico.alternar_ativo(dono)
    assert servico.alternar_fecha_conta(ze)[1] and servico.conta(ze).fecha_conta
    servico.mudar_papel(ze, "caixa")
    assert not servico.conta(ze).fecha_conta
    token = servico.conta(ze).token_sessao
    servico.alternar_ativo(ze)
    assert not servico.conta(ze).ativo and servico.conta(ze).token_sessao != token
    assert [u["usuario"] for u in ConsultasDeUsuarios(conexao).equipe()] == ["dono", "ze"]   # ativos primeiro
    servico.recuperar_acesso(ze, "outra-senha")
    assert servico.entrar("ze", "outra-senha", "ip").ativo
    segredo = totp.novo_segredo()
    servico.ativar_2fa(servico.conta(dono), segredo, totp.codigo_atual(segredo))
    assert servico.pode_pedir_codigo(dono).tem_2fa
    servico.desativar_2fa(dono)
    assert servico.pode_pedir_codigo(dono) is None

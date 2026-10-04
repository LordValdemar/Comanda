"""Repositórios locais de permissões e de ponto no SQLite de verdade (regras do núcleo, banco desta versão)."""

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from comanda import db
from src.domain.permissoes import AUTORIZACAO, ErroDeAutorizacao, ServicoDeAutorizacoes, TabelaDePermissoes
from src.domain.ponto import ErroDePonto, ServicoDePonto
from src.infrastructure.sqlite import RepositorioDePermissoesSQLite, RepositorioDePontoSQLite

AGORA = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)   # sexta, 10:00 em São Paulo
FUSO = ZoneInfo("America/Sao_Paulo")


def _pessoas(caminho):
    conexao = db.conectar(caminho)
    with conexao:
        conexao.execute("INSERT INTO usuarios (id, usuario, senha_hash, papel, token_sessao) VALUES (10, 'caixa', 'x', 'caixa', 't')")
        conexao.executemany("INSERT INTO usuarios (id, usuario, senha_hash, papel, token_sessao) VALUES (?, ?, 'x', 'garcom', 't')",
                            [(i, f"garcom{i}") for i in range(11, 19)])
        conexao.execute("INSERT INTO usuarios (id, usuario, senha_hash, papel, token_sessao, ativo) "
                        "VALUES (20, 'saiu', 'x', 'caixa', 't', 0)")
    conexao.close()


def autorizacoes(caminho):
    conexao = db.conectar(caminho)
    repo = RepositorioDePermissoesSQLite(conexao)
    repo.gravar_niveis({("fechar_conta", "garcom"): AUTORIZACAO})
    return ServicoDeAutorizacoes(repo, TabelaDePermissoes(repo.niveis_configurados()), {"comanda"}), conexao


def test_oito_garcons_lendo_o_mesmo_codigo_so_um_consegue(app):
    caminho = app.config["BANCO"]
    _pessoas(caminho)
    servico, conexao = autorizacoes(caminho)
    codigo = servico.gerar_codigo(servico.pessoa(10), "fechar_conta", "uma", None).codigo
    assert servico.pessoa(20) is None                          # quem saiu da equipe não autoriza
    conexao.close()
    largada, resultados = threading.Barrier(8), []

    def ler(garcom_id):
        outro, conexao = autorizacoes(caminho)
        largada.wait()
        try:
            resultados.append(outro.usar_codigo(codigo, outro.pessoa(garcom_id)).usado_por)
        except ErroDeAutorizacao:
            resultados.append(None)
        finally:
            conexao.close()

    garcons = [threading.Thread(target=ler, args=(i,)) for i in range(11, 19)]
    for garcom in garcons:
        garcom.start()
    for garcom in garcons:
        garcom.join()
    vencedores = [r for r in resultados if r is not None]
    assert len(vencedores) == 1
    servico, conexao = autorizacoes(caminho)
    liberacao = servico.liberacao_vigente(servico.pessoa(vencedores[0]), "fechar_conta")
    assert (liberacao.quem_autorizou, liberacao.descricao) == ("caixa", "uma vez")
    servico.gastar([liberacao.id])
    assert servico.liberacao_vigente(servico.pessoa(vencedores[0]), "fechar_conta") is None
    assert [lib.quem_usou for lib in servico.recentes(servico.pessoa(10))] == [f"garcom{vencedores[0]}"]
    conexao.close()


def ponto(caminho, momento=AGORA):
    conexao = db.conectar(caminho)
    return ServicoDePonto(RepositorioDePontoSQLite(conexao), FUSO, relogio=lambda: momento), conexao


def test_oito_pessoas_lendo_o_mesmo_qr_do_ponto(app):
    caminho = app.config["BANCO"]
    _pessoas(caminho)
    servico, conexao = ponto(caminho)
    servico.ligar(True)
    token = servico.token_atual()
    conexao.close()
    largada, resultados = threading.Barrier(8), []

    def ler():
        outro, conexao = ponto(caminho)
        largada.wait()
        try:
            outro.usar_token(token)
            resultados.append("leu")
        except ErroDePonto as erro:
            resultados.append(type(erro).__name__)
        finally:
            conexao.close()

    leitores = [threading.Thread(target=ler) for _ in range(8)]
    for leitor in leitores:
        leitor.start()
    for leitor in leitores:
        leitor.join()
    assert resultados.count("leu") == 1 and set(resultados) == {"leu", "QrJaUsado"}


def test_jornada_no_banco_local(app):
    caminho = app.config["BANCO"]
    _pessoas(caminho)
    servico, conexao = ponto(caminho)
    servico.ligar(True)
    servico.exigir_qr(False)
    servico.salvar_horario(11, "01234", "08:00", "18:00", isento=False)
    garcom = servico._repo.funcionario(11)
    assert servico.registrar_entrada(garcom, leu_o_qr=False, ip="10.0.0.9")
    assert not servico.registrar_entrada(garcom, leu_o_qr=False)          # dois toques: um registro
    tarde, conexao2 = ponto(caminho, AGORA + timedelta(hours=8, minutes=5))  # 18:05
    assert tarde.fechar_fora_do_horario() == ["garcom11"]
    [registro] = tarde.historico(AGORA - timedelta(days=1), AGORA + timedelta(days=1))
    assert (registro.motivo_saida, registro.segundos) == ("fim do horário", 8 * 3600 + 300)
    servico.desconectar(12, servico._repo.funcionario(10))
    assert conexao.execute("SELECT token_sessao FROM usuarios WHERE id = 12").fetchone()[0] != "t"
    conexao.close()
    conexao2.close()

"""Controle de ponto: a equipe só usa a Comanda com o ponto aberto e dentro do horário de trabalho.

- O administrador liga o controle (fica desligado até alguém ligar).
- Com ele ligado, quem não é administrador precisa "registrar a entrada" para usar o sistema.
- Cada pessoa pode ter um horário (dias e faixa de horas). Fora dele não dá para registrar a
  entrada, e o ponto aberto fecha sozinho quando o horário acaba.
- O administrador vê quem está trabalhando, desconecta qualquer pessoa (todos os aparelhos)
  e tira o relatório de horas.
- QR code (ligado por padrão): um aparelho fixo no estabelecimento mostra um QR que muda a cada
  2 minutos e é de uso único. Só depois de ler o QR com o celular a pessoa registra a entrada;
  assim ninguém bate ponto de fora. A saída também pede o QR; sem ele, fica anotada no relatório.

Funciona sem internet: tudo acontece na rede local. As regras ficam no núcleo (src/domain/ponto,
o mesmo da plataforma); aqui ficam as rotas, a sessão e o before_request.
"""

import csv
import hmac
import io
import logging
import time
from datetime import timedelta

import segno
from flask import Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from src.domain.erros import NaoEncontrado
from src.domain.horario import DIAS, Horario, HorarioInvalido, ler_dias, ler_hora
from src.domain.periodo import Periodo
from src.domain.ponto import MAX_CODIGOS_ERRADOS, QR_TROCA_SEGUNDOS, ErroDePonto, Funcionario, ServicoDePonto
from src.domain.tentativas import LimiteDeTentativas
from src.infrastructure.sqlite import RepositorioDePontoSQLite

from . import db
from .auth import INICIO, login_obrigatorio, papel_exigido
from .formatos import agora_utc, de_texto_utc, fuso, hoje_local, intervalo_utc

__all__ = ["DIAS", "MAX_CODIGOS_ERRADOS", "QR_TROCA_SEGUNDOS", "bp", "registrar"]

bp = Blueprint("ponto", __name__)
log = logging.getLogger("comanda.ponto")

MAX_DIAS_RELATORIO = 92
PRESENCA_SEGUNDOS = 300      # depois de ler o QR, 5 minutos para tocar em "Registrar"
_codigos_errados = LimiteDeTentativas(MAX_CODIGOS_ERRADOS, 600)  # por pessoa, neste processo

# O que quem está sem ponto aberto ainda pode abrir.
LIBERADAS_SEM_PONTO = {
    "ponto.meu", "ponto.entrada", "ponto.saida", "ponto.ler_qr", "ponto.digitar_codigo", "ponto.quiosque", "ponto.quiosque_api",
    "auth.entrar", "auth.codigo", "auth.sair", "auth.minha_conta", "auth.minha_senha", "auth.ativar_2fa",
    "auth.desativar_2fa_proprio", "static", "certificado.instrucoes", "certificado.baixar", "saude",
}


def servico():
    # O relógio é lido a cada uso (lambda): os testes podem trocá-lo.
    return ServicoDePonto(RepositorioDePontoSQLite(db.obter()), fuso(), relogio=lambda: agora_utc(),
                          tentativas=_codigos_errados)


def _horario(usuario):
    return Horario(usuario["horario_dias"] or "", usuario["horario_inicio"], usuario["horario_fim"])


def funcionario(usuario):
    """Uma linha de usuarios → Funcionario (para as regras do ponto)."""
    return Funcionario(id=usuario["id"], nome=usuario["usuario"], papel=usuario["papel"],
                       exige_ponto=bool(usuario["exige_ponto"]), horario=_horario(usuario))


# Atalhos usados pelas telas e pelos testes.

def resumo_da_pessoa(usuario):
    return _horario(usuario).resumo


def no_horario(usuario, agora=None):
    return _horario(usuario).vale(agora or servico().agora_local())


def ativo():
    return servico().ativo


def token_qr(agora=None):
    return servico().token_atual(agora)


def token_valido(token, agora=None):
    return servico().situacao(token, agora) == "valido"


def duracao(segundos):
    segundos = int(segundos or 0)
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos:02d} min"
    if minutos:
        return f"{minutos} min {seg:02d} s"
    return f"{seg} s"


def pagina_inicial():
    return url_for(INICIO[g.usuario["papel"]])


def presenca_confirmada():
    """A pessoa leu o QR há pouco (guardado na sessão dela)?"""
    return (session.get("ponto_presenca") or 0) > time.time()


def _sair_desta_sessao():
    """Sai só deste aparelho; o aviso ("Saída registrada às...") continua para a tela de entrada."""
    guardar = {chave: session[chave] for chave in ("csrf", "_flashes") if chave in session}
    session.clear()
    session.update(guardar)


# ---------------------------------------------------------------------------
# Antes de cada página e a tarefa de fundo
# ---------------------------------------------------------------------------

def exigir():
    """before_request: sem ponto aberto (ou fora do horário), a pessoa só vê a página do ponto."""
    usuario = getattr(g, "usuario", None)
    g.ponto_aberto = None
    g.ponto_exige = False
    if usuario is None:
        return None
    ponto, pessoa = servico(), funcionario(usuario)
    g.ponto_exige = ponto.bate_ponto(pessoa)
    if not g.ponto_exige:
        return None
    registro, fechou = ponto.conferir_expediente(pessoa)
    if fechou:
        log.info("Ponto de “%s” fechado: fim do horário", pessoa.nome)
        flash("Seu horário de trabalho terminou e o ponto foi encerrado.", "erro")
    g.ponto_aberto = registro
    if registro or request.endpoint in LIBERADAS_SEM_PONTO:
        return None
    if request.path.startswith("/api/"):
        return {"erro": "registre a entrada no ponto"}, 401  # a tela da cozinha recarrega e cai no ponto
    return redirect(url_for("ponto.meu"))


def fechar_fora_do_horario():
    """Tarefa de fundo (a cada minuto): fecha os pontos de quem passou do horário sem registrar a saída."""
    for nome in servico().fechar_fora_do_horario():
        log.info("Ponto de “%s” fechado automaticamente: fim do horário", nome)


# ---------------------------------------------------------------------------
# Funcionário: registrar entrada e saída
# ---------------------------------------------------------------------------

def _periodo_utc(inicio, fim):
    de, ate = intervalo_utc(inicio, fim)
    return de_texto_utc(de), de_texto_utc(ate)


@bp.route("/ponto")
@login_obrigatorio
def meu():
    if g.usuario["papel"] == "admin":
        return redirect(url_for("ponto.equipe"))
    ponto, pessoa = servico(), funcionario(g.usuario)
    hoje = hoje_local()
    return render_template(
        "ponto.html",
        exige=ponto.bate_ponto(pessoa),
        registro=ponto.aberto(pessoa.id),
        no_horario=ponto.no_horario(pessoa),
        exige_qr=ponto.exige_qr,
        presenca=presenca_confirmada(),
        horario=pessoa.horario.resumo,
        registros=ponto.historico(*_periodo_utc(hoje - timedelta(days=6), hoje), pessoa.id),
        inicio=pagina_inicial(),
    )


@bp.route("/ponto/entrada", methods=["POST"])
@login_obrigatorio
def entrada():
    ponto, pessoa = servico(), funcionario(g.usuario)
    if not ponto.bate_ponto(pessoa):
        return redirect(pagina_inicial())
    try:
        abriu = ponto.registrar_entrada(pessoa, presenca_confirmada(), request.remote_addr or "")
    except ErroDePonto as erro:
        flash(str(erro), "erro")
        return redirect(url_for("ponto.meu"))
    session.pop("ponto_presenca", None)  # o QR lido vale para um registro só
    if abriu:
        log.info("“%s” registrou a entrada", pessoa.nome)
        flash(f"Entrada registrada às {ponto.agora_local():%H:%M}. Bom trabalho!", "ok")
    return redirect(pagina_inicial())


@bp.route("/ponto/saida", methods=["POST"])
@login_obrigatorio
def saida():
    ponto, pessoa = servico(), funcionario(g.usuario)
    fechou = ponto.registrar_saida(pessoa, presenca_confirmada())
    session.pop("ponto_presenca", None)
    if fechou:
        log.info("“%s” registrou a saída", pessoa.nome)
        flash(f"Saída registrada às {ponto.agora_local():%H:%M}. Até a próxima!", "ok")
    _sair_desta_sessao()
    return redirect(url_for("auth.entrar"))


@bp.route("/ponto/codigo", methods=["POST"])
@login_obrigatorio
def digitar_codigo():
    """Para quando a câmera não abre: a pessoa digita o código curto que aparece embaixo do QR."""
    return _confirmar_presenca(lambda ponto: ponto.usar_codigo(request.form.get("codigo"), g.usuario["id"]))


@bp.route("/ponto/qr/<token>")
@login_obrigatorio
def ler_qr(token):
    """Endereço do QR code: o celular abre, e a presença fica confirmada por alguns minutos."""
    return _confirmar_presenca(lambda ponto: ponto.usar_token(token))


def _confirmar_presenca(usar):
    try:
        usar(servico())
    except ErroDePonto as erro:
        flash(str(erro), "erro")
    else:
        session["ponto_presenca"] = time.time() + PRESENCA_SEGUNDOS
        flash("QR code lido. Confirme abaixo.", "ok")
    return redirect(url_for("ponto.meu"))


def _conferir_quiosque(codigo):
    if not hmac.compare_digest(codigo, servico().codigo_quiosque()):
        abort(404)


@bp.route("/ponto/quiosque/<codigo>")
def quiosque(codigo):
    """Tela fixa (TV, tablet ou computador do caixa) que mostra o QR do ponto. Não precisa de login."""
    _conferir_quiosque(codigo)
    return render_template("ponto_quiosque.html", codigo=codigo)


@bp.route("/api/ponto/quiosque/<codigo>")
def quiosque_api(codigo):
    _conferir_quiosque(codigo)
    ponto = servico()
    if not ponto.ativo:
        resposta = {"ativo": False}
    else:
        # A tela pergunta a cada 2 s; o QR só vai na resposta quando mudou (outra versão).
        token = ponto.token_atual()
        versao = token.rsplit("-", 1)[0]
        resposta = {"ativo": True, "versao": versao, "troca_em": QR_TROCA_SEGUNDOS - int(time.time()) % QR_TROCA_SEGUNDOS}
        if request.args.get("versao") != versao:
            resposta["codigo"] = ponto.codigo_digitavel(token)
            # O endereço usa o mesmo IP e porta pelos quais a tela foi aberta: o celular, na mesma rede, alcança.
            endereco = url_for("ponto.ler_qr", token=token, _external=True)
            resposta["qr"] = segno.make(endereco, error="m").svg_data_uri(scale=10, border=2)
    resposta = jsonify(resposta)
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


# ---------------------------------------------------------------------------
# Administrador: equipe, horários, desconectar e relatório
# ---------------------------------------------------------------------------

def _ler_periodo():
    hoje = hoje_local()
    periodo = Periodo.ler(request.args.get("de"), request.args.get("ate"), hoje - timedelta(days=6), hoje,
                          MAX_DIAS_RELATORIO)
    return periodo.inicio, periodo.fim


@bp.route("/ponto/equipe")
@papel_exigido()
def equipe():
    ponto = servico()
    inicio, fim = _ler_periodo()
    pessoa_id = request.args.get("pessoa", type=int)
    registros = ponto.historico(*_periodo_utc(inicio, fim), pessoa_id)
    pessoas = db.obter().execute(
        "SELECT u.*, p.entrada AS trabalhando_desde FROM usuarios u "
        "LEFT JOIN ponto_registros p ON p.usuario_id = u.id AND p.saida IS NULL "
        "WHERE u.ativo = 1 ORDER BY u.papel = 'admin', u.usuario"
    ).fetchall()
    return render_template(
        "ponto_equipe.html",
        ativo=ponto.ativo,
        exige_qr=ponto.exige_qr,
        endereco_quiosque=url_for("ponto.quiosque", codigo=ponto.codigo_quiosque(), _external=True),
        pessoas=pessoas,
        no_horario={p["id"]: ponto.no_horario(funcionario(p)) for p in pessoas},
        registros=registros,
        totais=ponto.totais(registros),
        inicio=inicio, fim=fim, pessoa_id=pessoa_id,
        dias=DIAS,
        resumo_da_pessoa=resumo_da_pessoa,
    )


@bp.route("/ponto/ajustes", methods=["POST"])
@papel_exigido()
def ajustes():
    ligar = request.form.get("ativo") == "1"
    servico().ligar(ligar)
    log.info("“%s” %s o controle de ponto", g.usuario["usuario"], "ligou" if ligar else "desligou")
    if ligar:
        flash("Controle de ponto ligado. A equipe precisa registrar a entrada para usar o sistema.", "ok")
    else:
        flash("Controle de ponto desligado.", "ok")
    return redirect(url_for("ponto.equipe"))


@bp.route("/ponto/qr-ajustes", methods=["POST"])
@papel_exigido()
def qr_ajustes():
    acao = request.form.get("acao")
    ponto = servico()
    if acao == "novo_endereco":
        ponto.codigo_quiosque(novo=True)
        flash("Novo endereço da tela do QR code criado. Abra o endereço novo no aparelho do ponto.", "ok")
    elif acao in ("exigir", "dispensar"):
        ponto.exigir_qr(acao == "exigir")
        flash("QR code exigido para registrar o ponto." if acao == "exigir"
              else "QR code dispensado: o ponto passa a ser registrado por um botão.", "ok")
    else:
        abort(400)
    log.info("“%s” alterou o QR code do ponto: %s", g.usuario["usuario"], acao)
    return redirect(url_for("ponto.equipe"))


@bp.route("/ponto/pessoa/<int:usuario_id>", methods=["POST"])
@papel_exigido()
def salvar_pessoa(usuario_id):
    try:
        pessoa = servico().salvar_horario(
            usuario_id, ler_dias(request.form.getlist("dias")), ler_hora(request.form.get("inicio")),
            ler_hora(request.form.get("fim")), isento=bool(request.form.get("isento")),
        )
    except NaoEncontrado:
        abort(404)
    except HorarioInvalido as erro:
        flash(str(erro), "erro")
    else:
        log.info("“%s” alterou o horário de “%s”", g.usuario["usuario"], pessoa.nome)
        flash(f"Horário de “{pessoa.nome}” salvo.", "ok")
    return redirect(url_for("ponto.equipe"))


@bp.route("/ponto/pessoa/<int:usuario_id>/desconectar", methods=["POST"])
@papel_exigido()
def desconectar_pessoa(usuario_id):
    try:
        pessoa = servico().desconectar(usuario_id, funcionario(g.usuario))
    except NaoEncontrado:
        abort(404)
    except ErroDePonto as erro:
        flash(str(erro), "erro")
    else:
        log.info("“%s” desconectou “%s”", g.usuario["usuario"], pessoa.nome)
        flash(f"“{pessoa.nome}” foi desconectado de todos os aparelhos.", "ok")
    return redirect(url_for("auth.usuarios" if request.form.get("voltar") == "usuarios" else "ponto.equipe"))


@bp.route("/ponto/relatorio.csv")
@papel_exigido()
def relatorio_csv():
    inicio, fim = _ler_periodo()
    registros = servico().historico(*_periodo_utc(inicio, fim), request.args.get("pessoa", type=int))
    saida_csv = io.StringIO()
    escritor = csv.writer(saida_csv, delimiter=";")
    escritor.writerow(["Pessoa", "Entrada", "Saída", "Horas trabalhadas", "Como saiu"])

    def local(momento):
        return momento.astimezone(fuso()).strftime("%d/%m/%Y %H:%M")

    for r in reversed(registros):
        escritor.writerow([
            r.usuario_nome, local(r.entrada), local(r.saida) if r.saida else "(trabalhando)",
            f"{r.segundos / 3600:.2f}".replace(".", ","), r.motivo_saida or "",
        ])
    nome = f"ponto-{inicio.isoformat()}-a-{fim.isoformat()}.csv"
    return Response("﻿" + saida_csv.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={nome}"})


def registrar(app):
    app.register_blueprint(bp)
    app.before_request(exigir)  # depois do login (auth.registrar): sem ponto aberto, só a página do ponto
    app.jinja_env.filters["duracao"] = duracao

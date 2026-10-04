"""Casos de uso do ponto: entrada, saída, QR code da loja, horários e o relatório de horas.

O relógio é injetado (UTC) e o fuso da loja também: os testes escolhem a hora.
O que fica na sessão do navegador (a presença confirmada pelo QR) é da porta de entrada:
aqui chega só "leu o QR há pouco: sim/não".
"""

import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone, tzinfo

from ..erros import NaoEncontrado, SemPermissao
from ..horario import Horario, HorarioInvalido
from ..tentativas import LimiteDeTentativas
from .entidades import (
    DESCONECTADO,
    FIM_DO_HORARIO,
    SAIDA,
    SAIDA_SEM_QR,
    CodigoErrado,
    ErroDePonto,
    FaltaLerQr,
    ForaDoHorario,
    Funcionario,
    MuitasTentativas,
    QrJaUsado,
    QrVencido,
    RegistroDePonto,
)
from .qr import USADO, VALIDO, QrDoPonto, ler_token
from .repositorio import RepositorioDePonto

ATIVO, EXIGE_QR, SEGREDO, QUIOSQUE, GERACAO = "ponto_ativo", "ponto_qr", "ponto_segredo", "ponto_quiosque", "ponto_qr_geracao"
MAX_CODIGOS_ERRADOS = 5   # por pessoa, a cada 10 minutos


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class ServicoDePonto:
    def __init__(self, repositorio: RepositorioDePonto, fuso: tzinfo, relogio: Callable[[], datetime] = _agora,
                 tentativas: LimiteDeTentativas | None = None) -> None:
        self._repo = repositorio
        self._fuso = fuso
        self._relogio = relogio
        self._tentativas = tentativas or LimiteDeTentativas(MAX_CODIGOS_ERRADOS, 600)

    # -- ajustes da loja ---------------------------------------------------------------

    @property
    def ativo(self) -> bool:
        return self._repo.config(ATIVO) == "1"

    def ligar(self, ligado: bool) -> None:
        self._repo.gravar_config(ATIVO, "1" if ligado else "")

    @property
    def exige_qr(self) -> bool:
        return self._repo.config(EXIGE_QR) != "0"  # ligado, a não ser que o administrador desligue

    def exigir_qr(self, exigir: bool) -> None:
        self._repo.gravar_config(EXIGE_QR, "1" if exigir else "0")

    def codigo_quiosque(self, novo: bool = False) -> str:
        """Parte secreta do endereço da tela do QR code (quem tem o endereço vê o QR)."""
        codigo = self._repo.config(QUIOSQUE)
        if novo or not codigo:
            codigo = secrets.token_urlsafe(12)
            self._repo.gravar_config(QUIOSQUE, codigo)
        return codigo

    # -- QR code da loja ------------------------------------------------------------------

    def _qr(self) -> QrDoPonto:
        segredo = self._repo.config(SEGREDO)
        if not segredo:
            segredo = secrets.token_hex(32)
            self._repo.gravar_config(SEGREDO, segredo)
        return QrDoPonto(self._repo.empresa_id, segredo)

    def _instante(self, instante: float | None) -> float:
        return self._relogio().timestamp() if instante is None else instante

    @property
    def geracao(self) -> int:
        """Quantas vezes o QR da loja já foi usado: cada uso troca o código."""
        try:
            return int(self._repo.config(GERACAO) or 0)
        except ValueError:
            return 0

    def token_atual(self, instante: float | None = None) -> str:
        return self._qr().token(self.geracao, self._instante(instante))

    def codigo_digitavel(self, token: str) -> str | None:
        return self._qr().codigo_do_token(token)

    def situacao(self, token: str, instante: float | None = None) -> str:
        return self._qr().situacao(token, self.geracao, self._instante(instante))

    def usar_token(self, token: str) -> None:
        """Gasta o QR: só a primeira pessoa que o lê consegue, e a tela da loja troca de código."""
        situacao = self.situacao(token)
        if situacao == VALIDO:
            partes = ler_token(token)
            assert partes is not None
            if self._repo.trocar_geracao(partes[0], partes[0] + 1):
                return
            situacao = USADO  # outra pessoa leu o mesmo QR um instante antes
        raise QrJaUsado() if situacao == USADO else QrVencido()

    def usar_codigo(self, codigo: str | None, quem: int) -> None:
        """O código curto digitado (quando a câmera não abre). Errar muitas vezes bloqueia por um tempo."""
        if self._tentativas.bloqueado(quem):
            raise MuitasTentativas()
        token = self._qr().token_do_codigo(codigo, self.geracao, self._instante(None))
        if token is None:
            self._tentativas.errou(quem)
            raise CodigoErrado()
        self.usar_token(token)

    # -- entrada e saída ---------------------------------------------------------------------

    def agora_local(self) -> datetime:
        return self._relogio().astimezone(self._fuso)

    def no_horario(self, funcionario: Funcionario) -> bool:
        return funcionario.horario.vale(self.agora_local())

    def bate_ponto(self, funcionario: Funcionario) -> bool:
        return funcionario.bate_ponto(self.ativo)

    def aberto(self, usuario_id: int) -> RegistroDePonto | None:
        return self._repo.aberto(usuario_id)

    def conferir_expediente(self, funcionario: Funcionario) -> tuple[RegistroDePonto | None, bool]:
        """O ponto aberto da pessoa; se o horário dela acabou, fecha. Devolve (aberto, fechou_agora)."""
        registro = self._repo.aberto(funcionario.id)
        if registro is not None and not self.no_horario(funcionario):
            self._repo.fechar(funcionario.id, self._relogio(), FIM_DO_HORARIO, None)
            return None, True
        return registro, False

    def registrar_entrada(self, funcionario: Funcionario, leu_o_qr: bool, ip: str = "") -> bool:
        """Abre o ponto (False se já estava aberto)."""
        if not self.no_horario(funcionario):
            raise ForaDoHorario(f"Fora do seu horário de trabalho ({funcionario.horario.resumo}). Fale com o administrador.")
        if self.exige_qr and not leu_o_qr:
            raise FaltaLerQr()
        if self._repo.aberto(funcionario.id) is not None:
            return False
        return self._repo.abrir(funcionario, self._relogio(), ip[:45])

    def registrar_saida(self, funcionario: Funcionario, leu_o_qr: bool) -> bool:
        """Fecha o ponto. Sem o QR (quando ele é exigido), a saída fica anotada no relatório."""
        sem_qr = self.bate_ponto(funcionario) and self.exige_qr and not leu_o_qr
        return self._repo.fechar(funcionario.id, self._relogio(), SAIDA_SEM_QR if sem_qr else SAIDA, None) > 0

    def fechar_fora_do_horario(self) -> list[str]:
        """Fecha os pontos de quem passou do horário sem registrar a saída. Devolve os nomes."""
        fechados = []
        for funcionario in self._repo.funcionarios_com_ponto_aberto():
            if self.bate_ponto(funcionario) and not self.no_horario(funcionario):
                self._repo.fechar(funcionario.id, self._relogio(), FIM_DO_HORARIO, None)
                fechados.append(funcionario.nome)
        return fechados

    # -- administrador ---------------------------------------------------------------------------

    def _funcionario(self, usuario_id: int) -> Funcionario:
        funcionario = self._repo.funcionario(usuario_id)
        if funcionario is None:
            raise NaoEncontrado("Pessoa não encontrada.")
        return funcionario

    def salvar_horario(self, usuario_id: int, dias: str, inicio: str | None, fim: str | None, isento: bool) -> Funcionario:
        funcionario = self._funcionario(usuario_id)
        try:
            horario = Horario.novo(dias, inicio, fim)
        except HorarioInvalido as erro:
            raise HorarioInvalido(f"“{funcionario.nome}”: {erro}") from None
        self._repo.gravar_horario(usuario_id, horario, exige_ponto=not isento)
        return funcionario

    def desconectar(self, usuario_id: int, por: Funcionario) -> Funcionario:
        """Encerra as sessões da pessoa em todos os aparelhos e fecha o ponto dela."""
        alvo = self._funcionario(usuario_id)
        if alvo.id == por.id:
            raise ErroDePonto("Para sair, use o botão Sair.")
        if alvo.plataforma:
            raise SemPermissao("Quem opera a plataforma não é desconectado por uma loja.")
        self._repo.encerrar_sessoes(alvo.id)
        self._repo.fechar(alvo.id, self._relogio(), DESCONECTADO, por.id)
        return alvo

    def historico(self, de: datetime, ate: datetime, usuario_id: int | None = None) -> list[RegistroDePonto]:
        """Registros com entrada no período (mais novos primeiro), com as horas de cada um."""
        agora = self._relogio()
        return [replace(r, segundos=int(((r.saida or agora) - r.entrada).total_seconds()))
                for r in self._repo.registros(de, ate, usuario_id)]

    @staticmethod
    def totais(registros: list[RegistroDePonto]) -> list[tuple[str, int]]:
        """Horas por pessoa, em ordem alfabética."""
        soma: dict[str, int] = {}
        for registro in registros:
            soma[registro.usuario_nome] = soma.get(registro.usuario_nome, 0) + registro.segundos
        return sorted(soma.items())

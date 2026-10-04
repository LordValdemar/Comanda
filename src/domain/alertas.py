"""Alertas de tela offline: por quais canais avisar, quando uma tela está online e quando avisar que caiu ou voltou.

O envio (e-mail e webhook) fica na infraestrutura; aqui só as regras.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

ONLINE_SEGUNDOS = 75  # a TV manda sinal de vida a cada 30 s: offline depois de dois sinais perdidos


@dataclass(frozen=True)
class Canais:
    """Para onde vão os alertas de uma empresa."""

    emails: tuple[str, ...] = ()
    webhook: str = ""

    @property
    def nomes(self) -> list[str]:
        return (["e-mail"] if self.emails else []) + (["webhook"] if self.webhook else [])


def canais(alerta_emails: str, alerta_webhook: str, smtp_configurado: bool, padrao_emails: str = "",
           padrao_webhook: str = "") -> Canais:
    """Os canais escolhidos na página "Empresa"; em branco, valem os padrões (só a empresa principal tem).

    Sem servidor de e-mail configurado na plataforma, e-mail não é canal.
    """
    emails = alerta_emails or padrao_emails
    lista = tuple(e.strip() for e in emails.split(",") if e.strip()) if smtp_configurado else ()
    return Canais(lista, alerta_webhook or padrao_webhook)


def esta_online(ultimo_contato: datetime | None, fechada_em: datetime | None, agora: datetime) -> bool:
    if ultimo_contato is None:
        return False
    if fechada_em is not None and fechada_em >= ultimo_contato:
        return False  # a TV avisou que a janela foi fechada
    return (agora - ultimo_contato).total_seconds() < ONLINE_SEGUNDOS


@dataclass(frozen=True)
class TelaMonitorada:
    id: int
    nome: str
    empresa_id: int
    ultimo_contato: datetime
    avisado: bool   # já foi avisado que está fora


@dataclass(frozen=True)
class EmpresaAvisada:
    id: int
    nome: str
    alerta_emails: str
    alerta_webhook: str


class RepositorioDeMonitoramento(Protocol):
    def empresas_ativas(self) -> list[EmpresaAvisada]: ...
    def telas_com_contato(self) -> list[TelaMonitorada]: ...
    def marcar_aviso(self, tela_id: int, avisado: bool) -> None: ...


class MonitorDeTelas:
    """Avisa uma vez quando uma tela cai e outra vez quando ela volta (só de empresas ativas)."""

    def __init__(self, repositorio: RepositorioDeMonitoramento, avisar: Callable[[str, EmpresaAvisada], object],
                 limite_minutos: int, relogio: Callable[[], datetime], hora_local: Callable[[datetime], str]) -> None:
        self._repo = repositorio
        self._avisar = avisar
        self._limite = limite_minutos * 60
        self._relogio = relogio
        self._hora_local = hora_local

    def mensagem(self, tela: TelaMonitorada, agora: datetime) -> str | None:
        """O aviso a mandar agora (ou None, se nada mudou)."""
        fora = (agora - tela.ultimo_contato).total_seconds() > self._limite
        if fora and not tela.avisado:
            return f"⚠️ A tela “{tela.nome}” está sem comunicação desde {self._hora_local(tela.ultimo_contato)}."
        if not fora and tela.avisado:
            return f"✅ A tela “{tela.nome}” voltou a funcionar."
        return None

    def verificar(self) -> int:
        """Devolve quantos avisos foram mandados."""
        agora = self._relogio()
        empresas = {e.id: e for e in self._repo.empresas_ativas()}
        avisos = 0
        for tela in self._repo.telas_com_contato():
            empresa = empresas.get(tela.empresa_id)
            mensagem = None if empresa is None else self.mensagem(tela, agora)
            if empresa is None or mensagem is None:
                continue
            self._avisar(f"[{empresa.nome}] {mensagem}", empresa)
            self._repo.marcar_aviso(tela.id, not tela.avisado)
            avisos += 1
        return avisos

"""Casos de uso da cobrança: planos, assinatura no Asaas, faturas, webhook e bloqueio por atraso.

Fluxo:
1. A plataforma cadastra planos (preço + limites) e escolhe o plano de cada empresa (ou o
   cliente assina sozinho, pela página da conta).
2. Ativar a cobrança cria o cliente e a assinatura mensal no Asaas.
3. O Asaas gera as faturas, avisa o cliente e chama o webhook quando algo muda.
4. Fatura vencida há mais de `tolerancia_dias` → empresa suspensa (motivo "inadimplencia");
   pagou → reativada sozinha. Suspensão manual nunca é desfeita automaticamente.

O conteúdo do webhook NUNCA é usado como verdade: ele só avisa que algo mudou, e a situação
da fatura é consultada direto no Asaas. Assim, quem descobrir o token do webhook não libera
um cliente com um aviso falso de pagamento.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..dinheiro import reais
from ..documentos import documento_valido, so_numeros
from ..erros import NaoEncontrado
from .entidades import MAX_EMAIL, DadosDoPlano, EmpresaCobrada, ErroDeCobranca, ErroNoGateway, Fatura, Plano, referencia
from .gateway import GatewayDeCobranca
from .repositorio import RepositorioDeCobranca

log = logging.getLogger("propagandas.cobranca")


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _nada(_mensagem: str) -> None:
    return None


class ServicoDeCobranca:
    def __init__(self, repositorio: RepositorioDeCobranca, gateway: GatewayDeCobranca, *, empresa_principal: int,
                 tolerancia_dias: int, hoje: Callable[[], date], relogio: Callable[[], datetime] = _agora,
                 avisar_plataforma: Callable[[str], None] = _nada) -> None:
        self._repo = repositorio
        self._gateway = gateway
        self._principal = empresa_principal
        self._tolerancia = tolerancia_dias
        self._hoje = hoje
        self._relogio = relogio
        self._avisar = avisar_plataforma

    def empresa(self, empresa_id: int) -> EmpresaCobrada:
        empresa = self._repo.empresa(empresa_id)
        if empresa is None:
            raise NaoEncontrado("Empresa não encontrada.")
        return empresa

    def _plano(self, plano_id: int) -> Plano:
        plano = self._repo.plano(plano_id)
        if plano is None:
            raise NaoEncontrado("Plano não encontrado.")
        return plano

    # -- faturas e bloqueio por atraso ---------------------------------------------------------

    def gravar_fatura(self, empresa_id: int, pagamento: dict[str, Any]) -> Fatura:
        fatura = Fatura.do_gateway(pagamento)
        self._repo.gravar_fatura(empresa_id, fatura, self._relogio())
        return fatura

    def avaliar_inadimplencia(self, empresa_id: int, hoje: date | None = None) -> str | None:
        """Suspende ou reativa a empresa conforme as faturas. Devolve 'suspensa', 'reativada' ou None."""
        empresa = self._repo.empresa(empresa_id)
        if empresa is None or empresa_id == self._principal:
            return None
        limite = (hoje or self._hoje()) - timedelta(days=self._tolerancia)
        decisao = empresa.decidir_inadimplencia(self._repo.tem_fatura_vencida_antes_de(empresa_id, limite))
        if decisao == "suspender":
            self._repo.suspender_por_inadimplencia(empresa_id)
            log.warning("Empresa “%s” suspensa por falta de pagamento", empresa.nome)
            self._avisar(f"⛔ “{empresa.nome}” foi suspensa por falta de pagamento.")
            return "suspensa"
        if decisao == "reativar":
            self._repo.reativar(empresa_id)
            log.info("Empresa “%s” reativada após pagamento", empresa.nome)
            self._avisar(f"💰 “{empresa.nome}” pagou e foi reativada automaticamente.")
            return "reativada"
        return None

    def sincronizar(self, empresa: EmpresaCobrada) -> int:
        """Busca as faturas da assinatura no Asaas (caso algum webhook tenha se perdido)."""
        if not empresa.asaas_assinatura_id:
            return 0
        pagamentos = self._gateway.faturas_da_assinatura(empresa.asaas_assinatura_id)
        for pagamento in pagamentos:
            self.gravar_fatura(empresa.id, pagamento)
        # Fatura em aberto aqui que não existe mais no Asaas foi cancelada lá (e o aviso
        # se perdeu): sem isso ela ficaria "vencida" para sempre e suspenderia o cliente.
        no_gateway = {str(p["id"]) for p in pagamentos}
        self._repo.cancelar_faturas([i for i in self._repo.faturas_em_aberto(empresa.id) if i not in no_gateway])
        self.avaliar_inadimplencia(empresa.id)
        return len(pagamentos)

    def sincronizar_todas(self) -> None:
        """Tarefa diária. Erro numa empresa não impede as outras; depois aplica a tolerância de atraso."""
        for empresa in self._repo.empresas_com_assinatura():
            try:
                self.sincronizar(empresa)
            except ErroNoGateway:
                log.exception("Falha ao sincronizar as faturas da empresa %s", empresa.id)
        for empresa_id in self._repo.empresas_com_cobranca_automatica():
            self.avaliar_inadimplencia(empresa_id)

    def _sincronizar_sem_falhar(self, empresa_id: int) -> None:
        try:
            self.sincronizar(self.empresa(empresa_id))  # traz a primeira fatura
        except ErroNoGateway:
            log.exception("Assinatura criada, mas a primeira sincronização falhou")

    # -- webhook --------------------------------------------------------------------------------

    def processar_aviso(self, evento: dict[str, Any]) -> dict[str, Any]:
        """Um aviso do Asaas (o token já foi conferido). A resposta vai de volta para ele (sempre 200)."""
        pagamento = evento.get("payment")
        evento_id = str(evento.get("id") or "")[:100]
        # O Asaas pode reenviar o mesmo evento. Ele só é marcado como processado no fim: se algo
        # falhar no meio, o reenvio é aplicado (gravar a fatura é idempotente).
        if evento_id and self._repo.evento_processado(evento_id):
            return {"ok": True, "repetido": True}

        resposta: dict[str, Any] = {"ok": True, "ignorado": True}
        empresa = None
        if isinstance(pagamento, dict) and isinstance(pagamento.get("id"), str) and pagamento.get("subscription"):
            empresa = self._repo.empresa_da_assinatura(str(pagamento["subscription"]))
            if empresa is None:
                log.info("Webhook do Asaas para assinatura desconhecida %s", pagamento["subscription"])

        if empresa is not None and isinstance(pagamento, dict):
            try:
                verdadeiro = self._gateway.buscar_fatura(pagamento["id"])
            except ErroNoGateway as erro:
                # A sincronização aplica depois. Responde 200 para o Asaas não pausar a fila,
                # mas NÃO marca o evento como processado.
                log.warning("Webhook: não foi possível confirmar a fatura %s no Asaas (%s)", pagamento["id"], erro)
                return {"ok": True, "pendente": True}
            if verdadeiro.get("id") != pagamento["id"] or verdadeiro.get("subscription") != empresa.asaas_assinatura_id:
                log.warning("Webhook: a fatura %s não pertence à assinatura da empresa %s", pagamento["id"], empresa.id)
                return {"ok": True, "ignorado": True}
            self.gravar_fatura(empresa.id, verdadeiro)
            resultado = self.avaliar_inadimplencia(empresa.id)
            log.info("Asaas: %s da fatura %s (empresa %s), situação confirmada: %s",
                     evento.get("event"), pagamento["id"], empresa.id, verdadeiro.get("status"))
            resposta = {"ok": True, "empresa": empresa.id, "resultado": resultado}

        if evento_id:
            self._repo.marcar_evento(evento_id, self._relogio())
        return resposta

    # -- planos (plataforma) ---------------------------------------------------------------------

    def criar_plano(self, dados: DadosDoPlano) -> int:
        dados = dados.conferido()
        if self._repo.plano_com_nome(dados.nome):
            raise ErroDeCobranca(f"O plano “{dados.nome}” já existe.")
        return self._repo.inserir_plano(dados)

    def atualizar_plano(self, plano_id: int, dados: DadosDoPlano) -> None:
        """Os limites novos valem na hora para todas as empresas do plano; o preço das assinaturas não muda."""
        self._plano(plano_id)
        try:
            dados = dados.conferido()
        except ErroDeCobranca:
            raise ErroDeCobranca("Informe o nome, o preço e pelo menos um módulo do plano.") from None
        self._repo.atualizar_plano(plano_id, dados)

    # -- assinatura (plataforma) ------------------------------------------------------------------

    def salvar_dados(self, empresa_id: int, plano_id: int | None, documento: str | None, email: str | None,
                     automatica: bool) -> None:
        """Plano, CPF/CNPJ e e-mail de cobrança. Se a assinatura já existe, muda o valor no Asaas."""
        empresa = self.empresa(empresa_id)
        plano = self._repo.plano(plano_id) if plano_id is not None else None
        documento = so_numeros(documento)
        email = (email or "").strip()[:MAX_EMAIL]
        if documento and not documento_valido(documento):
            raise ErroDeCobranca("CPF ou CNPJ inválido.")
        if email and "@" not in email:
            raise ErroDeCobranca("E-mail de cobrança inválido.")
        if empresa.tem_assinatura and plano is None:
            raise ErroDeCobranca("Cancele a cobrança antes de tirar o plano desta empresa.")
        if empresa.asaas_assinatura_id and plano is not None and plano.id != empresa.plano_id:
            try:
                self._gateway.atualizar_assinatura(empresa.asaas_assinatura_id, plano.preco_centavos, f"Plano {plano.nome}")
            except ErroNoGateway as erro:
                raise ErroDeCobranca(f"O Asaas recusou a mudança de plano: {erro}") from None
        self._repo.gravar_dados_de_cobranca(empresa_id, plano, documento, email, automatica)

    def _cliente_no_gateway(self, empresa: EmpresaCobrada, documento: str, email: str) -> str:
        if empresa.asaas_cliente_id:
            return empresa.asaas_cliente_id
        cliente_id = str(self._gateway.criar_cliente(empresa.nome, documento, email, referencia(empresa.id))["id"])
        self._repo.gravar_cliente_no_gateway(empresa.id, cliente_id)
        return cliente_id

    def ativar(self, empresa_id: int, primeiro_vencimento: date | None) -> Plano:
        empresa = self.empresa(empresa_id)
        plano = self._repo.plano(empresa.plano_id) if empresa.plano_id is not None else None
        erro = None
        if empresa.tem_assinatura:
            erro = "a cobrança já está ativa"
        elif plano is None or plano.preco_centavos <= 0:
            erro = "escolha um plano com preço"
        elif not documento_valido(empresa.documento):
            erro = "informe um CPF ou CNPJ válido"
        elif primeiro_vencimento is None or primeiro_vencimento < self._hoje():
            erro = "informe a data do primeiro vencimento (hoje ou depois)"
        if erro or plano is None or primeiro_vencimento is None:
            raise ErroDeCobranca(f"Não foi possível ativar a cobrança: {erro}.")
        try:
            cliente_id = self._cliente_no_gateway(empresa, empresa.documento, empresa.email_cobranca)
            assinatura = self._gateway.criar_assinatura(cliente_id, plano.preco_centavos, primeiro_vencimento.isoformat(),
                                                        f"Plano {plano.nome}", referencia(empresa_id))
        except ErroNoGateway as erro_asaas:
            raise ErroDeCobranca(f"O Asaas recusou: {erro_asaas}") from None
        self._repo.gravar_assinatura(empresa_id, str(assinatura["id"]), automatica=True)
        self._sincronizar_sem_falhar(empresa_id)
        return plano

    def cancelar_no_gateway(self, empresa_id: int) -> EmpresaCobrada:
        """Cancela a assinatura no Asaas (se houver). Erro do Asaas sobe como ErroNoGateway."""
        empresa = self.empresa(empresa_id)
        if empresa.asaas_assinatura_id:
            self._gateway.cancelar_assinatura(empresa.asaas_assinatura_id)
        return empresa

    def cancelar(self, empresa_id: int) -> EmpresaCobrada:
        """Plataforma: para de cobrar (o plano continua escolhido)."""
        empresa = self.cancelar_no_gateway(empresa_id)
        self._repo.gravar_assinatura(empresa_id, None, automatica=False)
        self.avaliar_inadimplencia(empresa_id)
        return empresa

    # -- assinatura pelo próprio cliente ---------------------------------------------------------------

    def assinar(self, empresa_id: int, plano_id: int, documento: str | None, email: str | None, dias_de_teste: int,
                gateway_configurado: bool) -> tuple[Plano, str]:
        """Assina (ou troca de) plano. Devolve o plano e "assinou o" / "trocou para o"."""
        if empresa_id == self._principal:
            raise ErroDeCobranca("A empresa principal da plataforma usa todos os módulos e não assina planos.")
        empresa, plano = self.empresa(empresa_id), self._plano(plano_id)
        documento = so_numeros(documento or empresa.documento)
        email = (email or empresa.email_cobranca or "").strip()[:MAX_EMAIL]
        if not gateway_configurado:
            raise ErroDeCobranca("A assinatura pelo site ainda não está disponível. Fale com o suporte para ativar o seu plano.")
        if not documento_valido(documento):
            raise ErroDeCobranca("Informe um CPF ou CNPJ válido (vai na fatura).")
        if "@" not in email:
            raise ErroDeCobranca("Informe um e-mail válido para receber as faturas.")
        self._repo.gravar_contato(empresa_id, documento, email)
        try:
            if empresa.asaas_assinatura_id:
                # Troca de plano: o Asaas muda o valor das próximas faturas (e das em aberto).
                self._gateway.atualizar_assinatura(empresa.asaas_assinatura_id, plano.preco_centavos, f"Plano {plano.nome}")
            else:
                cliente_id = self._cliente_no_gateway(empresa, documento, email)
                vencimento = self._hoje() + timedelta(days=dias_de_teste)
                assinatura = self._gateway.criar_assinatura(cliente_id, plano.preco_centavos, vencimento.isoformat(),
                                                            f"Plano {plano.nome}", referencia(empresa_id))
                self._repo.gravar_assinatura(empresa_id, str(assinatura["id"]), automatica=True)
        except ErroNoGateway as erro:
            log.warning("Assinatura da empresa %s recusada pelo Asaas: %s", empresa_id, erro)
            raise ErroDeCobranca(f"Não foi possível concluir a assinatura: {erro}") from None
        self._repo.gravar_plano_da_empresa(empresa_id, plano)
        self._sincronizar_sem_falhar(empresa_id)
        acao = "trocou para o" if empresa.plano_id else "assinou o"
        self._avisar(f"💳 “{empresa.nome}” {acao} plano {plano.nome} ({reais(plano.preco_centavos)}/mês).")
        return plano, acao

    def desistir(self, empresa_id: int) -> EmpresaCobrada:
        """O cliente cancela a assinatura: sem plano e sem novas faturas (os dados da loja ficam)."""
        empresa = self.cancelar_no_gateway(empresa_id)
        self._repo.tirar_plano(empresa_id)
        self.avaliar_inadimplencia(empresa_id)
        self._avisar(f"✖️ “{empresa.nome}” cancelou a assinatura.")
        return empresa

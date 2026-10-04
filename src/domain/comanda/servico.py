"""Casos de uso da Comanda: abrir, lançar, cozinha, pagar, ajustar, fechar, cancelar e reabrir.

Cada operação carrega a comanda, confere as regras (entidades) e manda o repositório gravar.
As que mexem em dinheiro rodam numa transação travada: dois caixas ao mesmo tempo não conseguem
pagar a mais, e nada entra na conta entre a conferência e o fechamento.
Permissões (quem pode fazer o quê) ficam fora daqui: são conferidas na porta de entrada.
"""

from dataclasses import dataclass

from ..dinheiro import reais
from .entidades import (
    FORMAS_DE_PAGAMENTO,
    MAX_CLIENTE,
    MAX_MESA,
    MAX_OBSERVACAO,
    Ator,
    Comanda,
    Item,
    NovoPagamento,
    Totais,
    conferir_mudanca_de_situacao,
    numero_da_comanda,
    quantidade_valida,
)
from .erros import ComandaNaoEncontrada, ErroComanda, ItemNaoEncontrado, NumeroEmUso
from .repositorio import RepositorioDeComandas


@dataclass(frozen=True)
class Pedido:
    produto_id: int
    quantidade: int
    observacao: str = ""


def _texto_opcional(texto: str | None, tamanho: int) -> str | None:
    return (texto or "").strip()[:tamanho] or None


class ServicoDeComandas:
    def __init__(self, repositorio: RepositorioDeComandas) -> None:
        self._repo = repositorio

    # -- consulta ---------------------------------------------------------------

    def comanda(self, comanda_id: int) -> Comanda:
        comanda = self._repo.carregar(comanda_id)
        if comanda is None:
            raise ComandaNaoEncontrada("Comanda não encontrada.")
        return comanda

    def _item(self, comanda: Comanda, item_id: int) -> Item:
        item = comanda.item(item_id)
        if item is None:
            raise ItemNaoEncontrado("Item não encontrado.")
        return item

    # -- abrir e lançar ----------------------------------------------------------

    def abrir(self, numero: str | int, mesa: str | None, cliente: str | None, taxa_percentual: float, ator: Ator,
              garcom_id: int | None = None) -> int:
        return self._repo.inserir_comanda(
            numero_da_comanda(numero), _texto_opcional(mesa, MAX_MESA), _texto_opcional(cliente, MAX_CLIENTE),
            taxa_percentual, ator.usuario_id, garcom_id,
        )

    def lancar(self, comanda_id: int, pedidos: list[Pedido], ator: Ator, atendente: int | None = None) -> int:
        """Lança os pedidos (todos ou nenhum). `atendente`: passa a atender a comanda, se ela ainda não tem garçom."""
        if not pedidos:
            raise ErroComanda("Escolha pelo menos um produto.")
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            comanda.garantir_aberta()
            for pedido in pedidos:
                quantidade_valida(pedido.quantidade)
                produto = self._repo.produto_do_cardapio(pedido.produto_id)
                if produto is None:
                    raise ErroComanda("Um dos produtos saiu do cardápio. Confira o pedido.")
                # Produto que não passa pela cozinha (ex.: refrigerante em lata) já sai entregue.
                status = "pendente" if produto.vai_cozinha else "entregue"
                self._repo.inserir_item(comanda_id, produto, pedido.quantidade,
                                        _texto_opcional(pedido.observacao, MAX_OBSERVACAO), status, ator.usuario_id)
            if atendente is not None and comanda.garcom_id is None:
                self._repo.definir_garcom_se_vazio(comanda_id, atendente)
        return len(pedidos)

    def alterar_dados(self, comanda_id: int, mesa: str | None, cliente: str | None, garcom_id: int | None,
                      nomes_dos_garcons: dict[int, str], ator: Ator) -> None:
        """Mesa, cliente e o garçom que atende (a troca de garçom fica no histórico)."""
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            comanda.garantir_aberta()
            self._repo.gravar_dados(comanda_id, _texto_opcional(mesa, MAX_MESA), _texto_opcional(cliente, MAX_CLIENTE),
                                    garcom_id)
            if garcom_id != comanda.garcom_id:
                antes = nomes_dos_garcons.get(comanda.garcom_id or 0, "ninguém") if comanda.garcom_id else "ninguém"
                depois = nomes_dos_garcons.get(garcom_id, "ninguém") if garcom_id else "ninguém"
                self._repo.registrar_historico(comanda_id, "garçom", ator.anotar(f"{antes} → {depois}"), ator.usuario_id)

    # -- andamento dos itens ----------------------------------------------------

    def comanda_do_item_ou_erro(self, item_id: int) -> int:
        comanda_id = self._repo.comanda_do_item(item_id)
        if comanda_id is None:
            raise ItemNaoEncontrado("Item não encontrado.")
        return comanda_id

    def mudar_situacao(self, item_id: int, nova: str) -> None:
        """Cozinha (e o garçom, ao entregar): escolhe a situação do item."""
        item = self._item(self.comanda(self.comanda_do_item_ou_erro(item_id)), item_id)
        conferir_mudanca_de_situacao(item, nova)
        self._repo.mudar_situacao_do_item(item_id, nova)

    def entregar(self, comanda_id: int, item_id: int) -> Item:
        item = self._item(self.comanda(comanda_id), item_id)
        conferir_mudanca_de_situacao(item, "entregue")
        self._repo.mudar_situacao_do_item(item_id, "entregue")
        return item

    def desfazer_entrega(self, comanda_id: int, item_id: int) -> None:
        """Um "Entregue" tocado sem querer: o item volta para a lista de prontos."""
        item = self._item(self.comanda(comanda_id), item_id)
        if item.status != "entregue" or not item.vai_cozinha:
            raise ErroComanda("Este item não pode voltar para pronto.")
        self._repo.mudar_situacao_do_item(item_id, "pronto")

    def marcar_tudo_pronto(self, comanda_id: int) -> int:
        return self._repo.marcar_tudo_pronto(comanda_id)

    def item(self, comanda_id: int, item_id: int) -> Item:
        return self._item(self.comanda(comanda_id), item_id)

    def cancelar_item(self, comanda_id: int, item_id: int, motivo: str, ator: Ator) -> Item:
        """Quem confere se a pessoa pode cancelar depois que a cozinha começou é a porta de entrada."""
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            item = self._item(comanda, item_id)
            motivo = comanda.conferir_cancelamento_do_item(item, motivo)
            self._repo.cancelar_item(item_id, motivo, ator.usuario_id)
            self._repo.registrar_historico(comanda_id, "cancelar item", ator.anotar(f"{item.quantidade}x {item.nome}: {motivo}"),
                                           ator.usuario_id)
        return item

    # -- dinheiro ------------------------------------------------------------------

    def registrar_pagamento(self, comanda_id: int, forma: str, valor: int, ator: Ator) -> NovoPagamento:
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            pagamento = comanda.conferir_pagamento(forma, valor)
            self._repo.inserir_pagamento(comanda_id, pagamento, ator.usuario_id)
            if ator.autorizado_por:
                self._repo.registrar_historico(
                    comanda_id, "pagamento", ator.anotar(f"{FORMAS_DE_PAGAMENTO[forma]} {reais(valor)}"), ator.usuario_id
                )
        return pagamento

    def remover_pagamento(self, comanda_id: int, pagamento_id: int, ator: Ator) -> None:
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            comanda.garantir_aberta()
            removido = self._repo.remover_pagamento(comanda_id, pagamento_id)
            if removido is not None:
                self._repo.registrar_historico(
                    comanda_id, "remover pagamento", ator.anotar(f"{removido.nome_da_forma} {reais(removido.valor_centavos)}"),
                    ator.usuario_id,
                )

    def ajustar(self, comanda_id: int, cobrar_taxa: bool, desconto: int | None, ator: Ator) -> None:
        """Taxa de serviço e desconto. `desconto` None: mantém o atual."""
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            novo_desconto = comanda.desconto_centavos if desconto is None else desconto
            comanda.conferir_ajuste(cobrar_taxa, novo_desconto)
            self._repo.gravar_ajuste(comanda_id, cobrar_taxa, novo_desconto)
            if novo_desconto != comanda.desconto_centavos:
                self._repo.registrar_historico(
                    comanda_id, "desconto", ator.anotar(f"{reais(comanda.desconto_centavos)} → {reais(novo_desconto)}"),
                    ator.usuario_id,
                )
            if cobrar_taxa != comanda.cobrar_taxa:
                self._repo.registrar_historico(
                    comanda_id, "taxa de serviço", ator.anotar("cobrada" if cobrar_taxa else "retirada"), ator.usuario_id
                )

    def fechar(self, comanda_id: int, ator: Ator) -> Totais:
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            totais = comanda.conferir_fechamento()
            # Grava os valores exatos do cupom: os relatórios usam estes, sem recalcular.
            self._repo.gravar_fechamento(comanda_id, totais, ator.usuario_id)
            if ator.autorizado_por:
                self._repo.registrar_historico(comanda_id, "fechar conta", ator.anotar(""), ator.usuario_id)
        return totais

    def cancelar(self, comanda_id: int, motivo: str, ator: Ator) -> Comanda:
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            motivo = comanda.conferir_cancelamento(motivo)
            self._repo.gravar_cancelamento(comanda_id, motivo, ator.usuario_id)
            self._repo.registrar_historico(comanda_id, "cancelar comanda", ator.anotar(motivo), ator.usuario_id)
        return comanda

    def reabrir(self, comanda_id: int, ator: Ator) -> Comanda:
        with self._repo.transacao():
            comanda = self.comanda(comanda_id)
            comanda.conferir_reabertura()
            try:
                self._repo.gravar_reabertura(comanda_id, comanda.numero)
            except NumeroEmUso:
                raise ErroComanda(
                    f"Já existe outra comanda {comanda.numero} aberta. Feche-a antes de reabrir esta."
                ) from None
            self._repo.registrar_historico(
                comanda_id, "reabrir comanda", ator.anotar(f"total era {reais(comanda.total_centavos)}"), ator.usuario_id
            )
        return comanda

"""Tabela de permissões: o que cada tipo de funcionário pode fazer, em cada função.

Cada função (cadastrar TVs, fechar conta, dar desconto...) tem, para cada papel, um nível:
"não", "sim" ou "com autorização" (a pessoa só faz depois que alguém que pode a libera).
O administrador da loja sempre pode tudo. Sem nada configurado, valem os padrões abaixo.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

NAO, SIM, AUTORIZACAO = 0, 1, 2
NIVEIS: dict[int, str] = {NAO: "Não", SIM: "Sim", AUTORIZACAO: "Com autorização"}

# Papéis que usam cada módulo (o administrador da empresa usa todos os módulos assinados).
PAPEIS_DO_MODULO: dict[str, frozenset[str]] = {
    "painel": frozenset({"admin", "editor"}),
    "comanda": frozenset({"admin", "caixa", "garcom", "cozinha"}),
}
# Papéis que aparecem na tela de permissões (o administrador não entra: ele sempre pode).
PAPEIS_CONFIGURAVEIS: dict[str, tuple[str, ...]] = {"painel": ("editor",), "comanda": ("caixa", "garcom", "cozinha")}


@dataclass(frozen=True)
class Funcao:
    modulo: str
    nome: str
    descricao: str
    padrao: Mapping[str, int] = field(default_factory=dict)
    autorizavel: bool = True


FUNCOES: dict[str, Funcao] = {
    # Painel de Propagandas
    "telas": Funcao(
        "painel", "Cadastrar e editar TVs",
        "Criar, renomear, agrupar, trocar o endereço, desconectar e excluir telas.",
    ),
    "conectar_tv": Funcao(
        "painel", "Conectar uma TV", "Ler o QR code que aparece na TV e escolher a tela dela.", {"editor": SIM},
    ),
    "relatorios": Funcao(
        "painel", "Relatórios de exibição", "Quantas vezes cada propaganda passou em cada TV.", {"editor": SIM},
        autorizavel=False,
    ),
    # Comanda
    "fechar_conta": Funcao(
        "comanda", "Fechar conta", "Receber pagamentos, tirar a taxa de serviço e finalizar a conta.", {"caixa": SIM},
    ),
    "desconto": Funcao("comanda", "Dar desconto", "Desconto em reais no fechamento da conta.", {"caixa": SIM}),
    "cancelar": Funcao(
        "comanda", "Cancelar",
        "Cancelar a comanda inteira e itens que a cozinha já começou "
        "(antes disso, quem lançou sempre pode desfazer o engano).",
        {"caixa": SIM},
    ),
    "reabrir": Funcao("comanda", "Reabrir comanda fechada", "Voltar uma conta já fechada para aberta (para corrigir)."),
    "cozinha": Funcao(
        "comanda", "Tela da cozinha", "Ver os pedidos e marcar preparando e pronto.", {"caixa": SIM, "cozinha": SIM},
        autorizavel=False,
    ),
    "vendas": Funcao(
        "comanda", "Vendas e comandas fechadas", "Relatório de vendas, exportação e a lista de contas fechadas.",
        {"caixa": SIM}, autorizavel=False,
    ),
    "cardapio": Funcao("comanda", "Cardápio", "Cadastrar produtos, preços e categorias."),
    "autorizar_painel": Funcao(
        "painel", "Autorizar os outros",
        "Mostrar o QR code que libera quem precisa de autorização (só nas funções em que tem “Sim”).",
        autorizavel=False,
    ),
    "autorizar_comanda": Funcao(
        "comanda", "Autorizar os outros",
        "Mostrar o QR code que libera quem precisa de autorização (só nas funções em que tem “Sim”). "
        "A permissão individual de fechar contas não inclui autorizar.",
        {"caixa": SIM}, autorizavel=False,
    ),
}
# Combinações fixas (sem elas o papel não teria o que fazer).
FIXAS: dict[tuple[str, str], int] = {("cozinha", "cozinha"): SIM}


def modulos_da_pessoa(papel: str, plataforma: bool, modulos_da_loja: Iterable[str]) -> frozenset[str]:
    """Módulos que a pessoa abre: os da loja que combinam com o papel (quem opera a plataforma abre todos)."""
    if plataforma:
        return frozenset(modulos_da_loja)
    return frozenset(m for m in modulos_da_loja if papel in PAPEIS_DO_MODULO.get(m, ()))


@dataclass(frozen=True)
class Pessoa:
    """Quem está usando o sistema, do ponto de vista das permissões."""

    id: int
    papel: str
    modulos: frozenset[str]
    fecha_conta: bool = False   # garçom com a permissão individual de fechar contas
    nome: str = ""

    @property
    def administrador(self) -> bool:
        return self.papel == "admin"


class TabelaDePermissoes:
    """Os níveis de uma loja: os que ela gravou e, no resto, os padrões."""

    def __init__(self, configuradas: Mapping[tuple[str, str], int] | None = None) -> None:
        self._configuradas = dict(configuradas or {})

    def nivel_do_papel(self, funcao: str, papel: str) -> int:
        """O que um papel pode nesta função (sem contar o administrador)."""
        if (funcao, papel) in FIXAS:
            return FIXAS[(funcao, papel)]
        definicao = FUNCOES[funcao]
        if papel not in PAPEIS_CONFIGURAVEIS[definicao.modulo]:
            return NAO
        nivel = self._configuradas.get((funcao, papel), definicao.padrao.get(papel, NAO))
        if nivel == AUTORIZACAO and not definicao.autorizavel:
            return NAO
        return nivel if nivel in NIVEIS else NAO

    def nivel(self, funcao: str, pessoa: Pessoa | None) -> int:
        """O que a pessoa pode nesta função."""
        if pessoa is None or FUNCOES[funcao].modulo not in pessoa.modulos:
            return NAO  # módulo que a loja não tem (ou que o papel não usa): nem o administrador
        if pessoa.administrador:
            return SIM
        if funcao == "fechar_conta" and pessoa.papel == "garcom" and pessoa.fecha_conta:
            return SIM  # permissão dada à pessoa, na lista de usuários
        return self.nivel_do_papel(funcao, pessoa.papel)

    def papeis_com(self, funcao: str, nivel: int) -> list[str]:
        return [p for p in PAPEIS_CONFIGURAVEIS[FUNCOES[funcao].modulo] if self.nivel_do_papel(funcao, p) == nivel]

    def alguem_precisa_de_autorizacao(self, funcao: str) -> bool:
        return bool(self.papeis_com(funcao, AUTORIZACAO))

    def pode_autorizar(self, funcao: str, pessoa: Pessoa | None) -> bool:
        """Pode liberar os outros nesta função: tem "Sim" nela e a permissão "Autorizar os outros"."""
        if pessoa is None or self.nivel(funcao, pessoa) != SIM:
            return False
        return pessoa.administrador or self.nivel("autorizar_" + FUNCOES[funcao].modulo, pessoa) == SIM

    def funcoes_que_pode_autorizar(self, pessoa: Pessoa | None) -> list[str]:
        """Funções em que a pessoa pode autorizar e alguém da loja precisa (o administrador vê todas)."""
        if pessoa is None:
            return []
        return [
            funcao for funcao, definicao in FUNCOES.items()
            if definicao.autorizavel and self.pode_autorizar(funcao, pessoa)
            and (pessoa.administrador or self.alguem_precisa_de_autorizacao(funcao))
        ]

    def mostrar_autorizar(self, pessoa: Pessoa | None) -> bool:
        """O menu mostra "Autorizar" para quem pode autorizar algo que alguém da loja precisa."""
        return any(self.alguem_precisa_de_autorizacao(f) for f in self.funcoes_que_pode_autorizar(pessoa))

    @staticmethod
    def niveis_do_formulario(valores: Mapping[str, str], modulos_da_loja: Iterable[str]) -> dict[tuple[str, str], int]:
        """Os níveis válidos de um formulário {"funcao.papel": "0|1|2"} (o resto é ignorado)."""
        modulos = set(modulos_da_loja)
        niveis: dict[tuple[str, str], int] = {}
        for funcao, definicao in FUNCOES.items():
            if definicao.modulo not in modulos:
                continue
            for papel in PAPEIS_CONFIGURAVEIS[definicao.modulo]:
                valor = valores.get(f"{funcao}.{papel}", "")
                if (funcao, papel) in FIXAS or not valor.isdigit() or int(valor) not in NIVEIS:
                    continue
                if int(valor) == AUTORIZACAO and not definicao.autorizavel:
                    continue
                niveis[(funcao, papel)] = int(valor)
        return niveis

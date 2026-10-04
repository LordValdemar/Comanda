"""O QR code do ponto: muda a cada 2 minutos e a cada uso, assinado com a chave da loja.

O token é "geração-janela-assinatura": a geração sobe a cada uso (quem leu primeiro leva),
a janela é o pedaço de 2 minutos em que foi mostrado. Também tem uma versão curta de
6 letras, para digitar quando a câmera não abre.
"""

import hashlib
import hmac

QR_TROCA_SEGUNDOS = 120      # o QR da loja muda a cada 2 minutos (e a cada uso)
QR_TOLERANCIA_SEGUNDOS = 30  # o QR que acabou de sair da tela ainda vale 30 s (quem estava lendo)
LETRAS_DO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I/L: fácil de digitar
TAMANHO_DO_CODIGO = 6

VALIDO, USADO, INVALIDO = "valido", "usado", "invalido"


def janela_de(instante: float) -> int:
    return int(instante // QR_TROCA_SEGUNDOS)


def ler_token(token: str) -> tuple[int, int, str] | None:
    try:
        geracao, janela, assinatura = token.split("-", 2)
        return int(geracao), int(janela), assinatura
    except ValueError:
        return None


class QrDoPonto:
    def __init__(self, empresa_id: int, segredo: str) -> None:
        self._empresa_id = empresa_id
        self._chave = segredo.encode()

    def _assinatura(self, geracao: int, janela: int) -> str:
        mensagem = f"{self._empresa_id}:{geracao}:{janela}".encode()
        return hmac.new(self._chave, mensagem, hashlib.sha256).hexdigest()[:24]

    def token(self, geracao: int, instante: float) -> str:
        janela = janela_de(instante)
        return f"{geracao}-{janela}-{self._assinatura(geracao, janela)}"

    def codigo(self, geracao: int, janela: int) -> str:
        """A versão curta do QR (muda junto com ele)."""
        mensagem = f"codigo:{self._empresa_id}:{geracao}:{janela}".encode()
        numero = int(hmac.new(self._chave, mensagem, hashlib.sha256).hexdigest(), 16)
        letras = []
        for _ in range(TAMANHO_DO_CODIGO):
            numero, resto = divmod(numero, len(LETRAS_DO_CODIGO))
            letras.append(LETRAS_DO_CODIGO[resto])
        return "".join(letras)

    def codigo_do_token(self, token: str) -> str | None:
        partes = ler_token(token)
        return None if partes is None else self.codigo(partes[0], partes[1])

    def situacao(self, token: str, geracao_atual: int, instante: float) -> str:
        """VALIDO, USADO (alguém já leu este QR) ou INVALIDO (vencido, falso ou de outra loja)."""
        partes = ler_token(token)
        if partes is None:
            return INVALIDO
        geracao, janela, assinatura = partes
        if not hmac.compare_digest(assinatura, self._assinatura(geracao, janela)):
            return INVALIDO
        atual = janela_de(instante)
        recente = janela == atual or (janela == atual - 1 and instante % QR_TROCA_SEGUNDOS < QR_TOLERANCIA_SEGUNDOS)
        if not recente:
            return INVALIDO
        return VALIDO if geracao == geracao_atual else USADO

    def token_do_codigo(self, codigo: str | None, geracao_atual: int, instante: float) -> str | None:
        """O token que corresponde ao código digitado (o atual ou o que acabou de sair da tela)."""
        codigo = "".join(c for c in (codigo or "").upper() if c in LETRAS_DO_CODIGO)
        if len(codigo) != TAMANHO_DO_CODIGO:
            return None
        atual = janela_de(instante)
        for janela in (atual, atual - 1):
            if hmac.compare_digest(codigo, self.codigo(geracao_atual, janela)):
                token = f"{geracao_atual}-{janela}-{self._assinatura(geracao_atual, janela)}"
                return token if self.situacao(token, geracao_atual, instante) == VALIDO else None
        return None

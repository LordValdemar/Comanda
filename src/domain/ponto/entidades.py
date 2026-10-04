"""Quem bate ponto e os registros de entrada e saída."""

from dataclasses import dataclass
from datetime import datetime

from ..erros import ErroDeDominio
from ..horario import Horario

SAIDA = "saída"
SAIDA_SEM_QR = "saída sem QR code"
FIM_DO_HORARIO = "fim do horário"
DESCONECTADO = "desconectado pelo administrador"


class ErroDePonto(ErroDeDominio):
    pass


class ForaDoHorario(ErroDePonto):
    pass


class FaltaLerQr(ErroDePonto):
    def __init__(self) -> None:
        super().__init__("Leia o QR code do ponto, na loja, com a câmera do celular.")


class QrJaUsado(ErroDePonto):
    def __init__(self) -> None:
        super().__init__("Este QR code já foi usado por outra pessoa. Leia o código novo que está na tela da loja.")


class QrVencido(ErroDePonto):
    def __init__(self) -> None:
        super().__init__("Este QR code venceu. Leia de novo o código que está na tela da loja.")


class CodigoErrado(ErroDePonto):
    def __init__(self) -> None:
        super().__init__("Código errado ou vencido. Digite o código que está agora na tela do ponto.")


class MuitasTentativas(ErroDePonto):
    def __init__(self) -> None:
        super().__init__("Muitos códigos errados. Espere alguns minutos ou leia o QR code.")


@dataclass(frozen=True)
class Funcionario:
    id: int
    nome: str
    papel: str
    plataforma: bool = False
    exige_ponto: bool = True     # o administrador pode deixar a pessoa isenta
    horario: Horario = Horario()

    def bate_ponto(self, controle_ligado: bool) -> bool:
        """Administradores nunca batem ponto; os outros, se a loja ligou o controle e a pessoa não é isenta."""
        if self.papel == "admin" or self.plataforma or not self.exige_ponto:
            return False
        return controle_ligado


@dataclass(frozen=True)
class RegistroDePonto:
    id: int
    usuario_id: int | None
    usuario_nome: str          # copiado: o histórico continua se a pessoa for excluída
    entrada: datetime
    saida: datetime | None = None
    motivo_saida: str | None = None
    encerrado_por_nome: str | None = None
    segundos: int = 0          # horas trabalhadas (até agora, se ainda está aberto)

    @property
    def aberto(self) -> bool:
        return self.saida is None

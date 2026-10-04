"""Controle de ponto (sem banco nem Flask)."""

from .entidades import (
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
from .qr import QR_TROCA_SEGUNDOS, QrDoPonto
from .repositorio import RepositorioDePonto
from .servico import MAX_CODIGOS_ERRADOS, ServicoDePonto

__all__ = [
    "MAX_CODIGOS_ERRADOS", "QR_TROCA_SEGUNDOS", "SAIDA_SEM_QR", "CodigoErrado", "ErroDePonto", "FaltaLerQr",
    "ForaDoHorario", "Funcionario", "MuitasTentativas", "QrDoPonto", "QrJaUsado", "QrVencido", "RegistroDePonto",
    "RepositorioDePonto", "ServicoDePonto",
]

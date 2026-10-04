"""Painel de propagandas (sem banco nem Flask)."""

from .exibicao import Exibicao, ler_registro
from .propaganda import (
    DURACAO_PADRAO,
    Destinos,
    ErroDePropaganda,
    Programacao,
    Propaganda,
    ler_data,
    ler_duracao,
    ler_letreiro,
    nova_ordem,
)
from .repositorio import RepositorioDeConexoes, RepositorioDePropagandas, RepositorioDeTelas
from .servico import Playlist, ServicoDePropagandas, TelaDaPlaylist
from .servico_telas import ServicoDeConexao, ServicoDeTelas
from .telas import (
    ErroDeTela,
    MuitosPedidos,
    PedidoDeConexao,
    PedidoVencido,
    Tela,
    normalizar_codigo_de_pedido,
)

__all__ = [
    "DURACAO_PADRAO", "Destinos", "ErroDePropaganda", "ErroDeTela", "Exibicao", "MuitosPedidos", "PedidoDeConexao",
    "PedidoVencido", "Playlist", "Programacao", "Propaganda", "RepositorioDeConexoes", "RepositorioDePropagandas",
    "RepositorioDeTelas", "ServicoDeConexao", "ServicoDePropagandas", "ServicoDeTelas", "Tela", "TelaDaPlaylist",
    "ler_data", "ler_duracao", "ler_letreiro", "ler_registro", "normalizar_codigo_de_pedido", "nova_ordem",
]

"""Cardápio: categorias e produtos (as regras ficam em src/domain/cardapio; aqui, as rotas)."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from src.domain.cardapio import DadosDoProduto, ServicoDeCardapio, agrupar
from src.domain.erros import ErroDeDominio, NaoEncontrado
from src.infrastructure.sqlite import RepositorioDeCardapioSQLite

from . import db, permissoes
from .formatos import entrada_reais

__all__ = ["agrupar", "bp", "produtos_ativos"]

bp = Blueprint("cardapio", __name__, url_prefix="/cardapio")


def servico():
    return ServicoDeCardapio(RepositorioDeCardapioSQLite(db.obter()))


def produtos_ativos(_conexao=None):
    """Produtos à venda, na ordem do cardápio (para a tela de lançar pedidos)."""
    return servico().a_venda()


def _voltar():
    return redirect(url_for("cardapio.lista"))


def _no_cardapio(acao, sucesso=None):
    """Roda a ação: erro de regra vira aviso; categoria ou produto de outra loja (ou inexistente), 404."""
    try:
        resultado = acao(servico())
    except NaoEncontrado:
        abort(404)
    except ErroDeDominio as erro:
        flash(str(erro), "erro")
    else:
        if sucesso:
            flash(sucesso(resultado) if callable(sucesso) else sucesso, "ok")
    return _voltar()


@bp.route("/")
@permissoes.exigir("cardapio")
def lista():
    cardapio = servico()
    return render_template("cardapio.html", categorias=cardapio.categorias(), produtos=cardapio.produtos(),
                           entrada_reais=entrada_reais)


@bp.route("/categorias", methods=["POST"])
@permissoes.exigir("cardapio")
def nova_categoria():
    return _no_cardapio(lambda cardapio: cardapio.criar_categoria(request.form.get("nome", "")),
                        lambda nome: f"Categoria “{nome}” criada.")


@bp.route("/categorias/<int:categoria_id>", methods=["POST"])
@permissoes.exigir("cardapio")
def alterar_categoria(categoria_id):
    acao = request.form.get("acao")
    if acao == "excluir":
        return _no_cardapio(lambda cardapio: cardapio.excluir_categoria(categoria_id),
                            lambda categoria: f"Categoria “{categoria.nome}” excluída.")
    if acao in ("subir", "descer"):
        return _no_cardapio(lambda cardapio: cardapio.mover_categoria(categoria_id, para_cima=acao == "subir"))
    if acao == "renomear":
        return _no_cardapio(lambda cardapio: cardapio.renomear_categoria(categoria_id, request.form.get("nome", "")))
    abort(400)


@bp.route("/produtos", methods=["POST"])
@permissoes.exigir("cardapio")
def novo_produto():
    def criar(cardapio):
        dados = DadosDoProduto.do_formulario(request.form)
        cardapio.criar_produto(dados)
        return dados.nome
    return _no_cardapio(criar, lambda nome: f"“{nome}” adicionado ao cardápio.")


@bp.route("/produtos/<int:produto_id>", methods=["POST"])
@permissoes.exigir("cardapio")
def alterar_produto(produto_id):
    acao = request.form.get("acao")
    if acao == "salvar":
        def salvar(cardapio):
            dados = DadosDoProduto.do_formulario(request.form)
            cardapio.atualizar_produto(produto_id, dados)
            return dados.nome
        return _no_cardapio(salvar, lambda nome: f"“{nome}” atualizado. Itens já lançados mantêm o preço da hora do pedido.")
    if acao == "ativo":
        return _no_cardapio(lambda cardapio: cardapio.alternar_ativo(produto_id),
                            lambda antes: f"“{antes.nome}” {'fora do cardápio' if antes.ativo else 'de volta ao cardápio'}.")
    if acao == "excluir":
        return _no_cardapio(lambda cardapio: cardapio.excluir_produto(produto_id),
                            lambda produto: f"“{produto.nome}” excluído.")
    abort(400)

"""Acesso ao banco SQLite e migrações do esquema."""

import sqlite3

from flask import current_app, g

# Cada item é uma versão do banco. Para mudar o esquema, ADICIONE um novo
# item no fim da lista (nunca altere os anteriores): bancos já instalados
# rodam só as migrações que ainda não têm.
# Valores em dinheiro são guardados em centavos (inteiros) e datas em UTC.
MIGRACOES = [
    # 1 - estrutura inicial
    """
    CREATE TABLE usuarios (
        id            INTEGER PRIMARY KEY,
        usuario       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        senha_hash    TEXT    NOT NULL,
        papel         TEXT    NOT NULL CHECK (papel IN ('admin', 'caixa', 'garcom', 'cozinha')),
        ativo         INTEGER NOT NULL DEFAULT 1,
        token_sessao  TEXT    NOT NULL,
        criado_em     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE configuracoes (
        chave  TEXT PRIMARY KEY,
        valor  TEXT NOT NULL
    );

    CREATE TABLE categorias (
        id       INTEGER PRIMARY KEY,
        nome     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        posicao  INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE produtos (
        id              INTEGER PRIMARY KEY,
        categoria_id    INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
        codigo          TEXT    UNIQUE,               -- atalho opcional para lançar rápido (ex.: "12")
        nome            TEXT    NOT NULL,
        preco_centavos  INTEGER NOT NULL CHECK (preco_centavos >= 0),
        vai_cozinha     INTEGER NOT NULL DEFAULT 1,   -- 0 = sai pronto (bebida em lata, por exemplo)
        ativo           INTEGER NOT NULL DEFAULT 1,
        criado_em       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE comandas (
        id                  INTEGER PRIMARY KEY,
        numero              INTEGER NOT NULL CHECK (numero > 0),   -- número do cartão/ficha
        mesa                TEXT,
        cliente             TEXT,
        status              TEXT    NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'fechada', 'cancelada')),
        cobrar_taxa         INTEGER NOT NULL DEFAULT 1,
        taxa_percentual     REAL    NOT NULL DEFAULT 0,
        desconto_centavos   INTEGER NOT NULL DEFAULT 0 CHECK (desconto_centavos >= 0),
        total_centavos      INTEGER,                               -- gravado ao fechar
        aberta_por          INTEGER REFERENCES usuarios(id),
        aberta_em           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        fechada_por         INTEGER REFERENCES usuarios(id),
        fechada_em          TEXT,
        motivo_cancelamento TEXT
    );
    -- Um mesmo número só pode estar aberto uma vez (o cartão volta a ser usado depois de fechado).
    CREATE UNIQUE INDEX comandas_numero_aberta ON comandas(numero) WHERE status = 'aberta';
    CREATE INDEX comandas_fechada_em ON comandas(fechada_em);

    CREATE TABLE itens (
        id                  INTEGER PRIMARY KEY,
        comanda_id          INTEGER NOT NULL REFERENCES comandas(id) ON DELETE CASCADE,
        produto_id          INTEGER REFERENCES produtos(id) ON DELETE SET NULL,
        nome                TEXT    NOT NULL,          -- cópia: o cardápio pode mudar depois
        preco_centavos      INTEGER NOT NULL,
        quantidade          INTEGER NOT NULL CHECK (quantidade BETWEEN 1 AND 999),
        observacao          TEXT,
        vai_cozinha         INTEGER NOT NULL,
        status              TEXT    NOT NULL CHECK (status IN ('pendente', 'preparando', 'pronto', 'entregue', 'cancelado')),
        lancado_por         INTEGER REFERENCES usuarios(id),
        lancado_em          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        atualizado_em       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        cancelado_por       INTEGER REFERENCES usuarios(id),
        motivo_cancelamento TEXT
    );
    CREATE INDEX itens_comanda ON itens(comanda_id);
    CREATE INDEX itens_status ON itens(status);

    CREATE TABLE pagamentos (
        id                INTEGER PRIMARY KEY,
        comanda_id        INTEGER NOT NULL REFERENCES comandas(id) ON DELETE CASCADE,
        forma             TEXT    NOT NULL CHECK (forma IN ('dinheiro', 'pix', 'debito', 'credito', 'outro')),
        valor_centavos    INTEGER NOT NULL CHECK (valor_centavos > 0),   -- o que abate da conta
        recebido_centavos INTEGER NOT NULL,                              -- dinheiro entregue (troco = recebido - valor)
        registrado_por    INTEGER REFERENCES usuarios(id),
        registrado_em     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX pagamentos_comanda ON pagamentos(comanda_id);

    -- Quem fez o quê (cancelamentos, descontos, reaberturas...).
    CREATE TABLE auditoria (
        id         INTEGER PRIMARY KEY,
        quando     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        comanda_id INTEGER REFERENCES comandas(id) ON DELETE SET NULL,
        acao       TEXT    NOT NULL,
        detalhe    TEXT
    );
    """,
]


def conectar(caminho):
    conexao = sqlite3.connect(caminho, timeout=15)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def migrar(caminho):
    """Aplica as migrações que faltam (cada uma numa transação)."""
    conexao = sqlite3.connect(caminho, timeout=15)
    try:
        conexao.execute("PRAGMA journal_mode = WAL")
        versao = conexao.execute("PRAGMA user_version").fetchone()[0]
        if versao > len(MIGRACOES):
            raise RuntimeError(
                f"O banco é da versão {versao}, mais nova que este programa ({len(MIGRACOES)}). Atualize o programa."
            )
        for numero in range(versao + 1, len(MIGRACOES) + 1):
            conexao.executescript(f"BEGIN;\n{MIGRACOES[numero - 1]}\nPRAGMA user_version = {numero};\nCOMMIT;")
    finally:
        conexao.close()


def obter():
    """Conexão do pedido atual (uma por requisição)."""
    if "db" not in g:
        g.db = conectar(current_app.config["BANCO"])
    return g.db


def fechar(_erro=None):
    conexao = g.pop("db", None)
    if conexao is not None:
        conexao.close()


def ler_config(chave, padrao=""):
    linha = obter().execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return padrao if linha is None else linha["valor"]


def gravar_config(chave, valor):
    conexao = obter()
    with conexao:
        conexao.execute(
            "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, str(valor)),
        )


def auditar(conexao, acao, detalhe="", comanda_id=None, usuario_id=None):
    """Registra uma ação. Chame dentro da mesma transação da mudança."""
    if usuario_id is None and getattr(g, "usuario", None) is not None:
        usuario_id = g.usuario["id"]
    conexao.execute(
        "INSERT INTO auditoria (usuario_id, comanda_id, acao, detalhe) VALUES (?, ?, ?, ?)",
        (usuario_id, comanda_id, acao, detalhe),
    )

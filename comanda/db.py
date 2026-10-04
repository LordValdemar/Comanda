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
    # 2 - verificação em duas etapas (código do aplicativo autenticador)
    """
    ALTER TABLE usuarios ADD COLUMN totp_segredo TEXT;
    ALTER TABLE usuarios ADD COLUMN totp_ultimo INTEGER NOT NULL DEFAULT 0;  -- impede reusar o mesmo código
    """,
    # 3 - o administrador pode autorizar um garçom a fechar contas
    """
    ALTER TABLE usuarios ADD COLUMN fecha_conta INTEGER NOT NULL DEFAULT 0;
    """,
    # 4 - controle de ponto: horário de trabalho por usuário e registros de entrada e saída.
    # O nome do usuário é copiado no registro: o histórico continua se o usuário for excluído.
    """
    ALTER TABLE usuarios ADD COLUMN exige_ponto INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE usuarios ADD COLUMN horario_dias TEXT NOT NULL DEFAULT '0123456';
    ALTER TABLE usuarios ADD COLUMN horario_inicio TEXT;
    ALTER TABLE usuarios ADD COLUMN horario_fim TEXT;

    CREATE TABLE ponto_registros (
        id             INTEGER PRIMARY KEY,
        usuario_id     INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usuario_nome   TEXT    NOT NULL,
        entrada        TEXT    NOT NULL,
        saida          TEXT,
        motivo_saida   TEXT,
        encerrado_por  INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        ip             TEXT
    );
    -- Cada pessoa tem no máximo um ponto aberto.
    CREATE UNIQUE INDEX ponto_um_aberto ON ponto_registros(usuario_id) WHERE saida IS NULL;
    CREATE INDEX ponto_entrada ON ponto_registros(entrada);
    """,
    # 5 - a taxa de serviço exata do cupom fica gravada ao fechar (os relatórios usam ela)
    """
    ALTER TABLE comandas ADD COLUMN taxa_centavos INTEGER;
    """,
    # 6 - autorizações por QR code: quem tem a permissão libera, por alguns minutos, quem precisa
    # de autorização (ex.: o caixa libera o garçom a fechar uma conta). Fica o registro de quem foi.
    """
    CREATE TABLE autorizacoes (
        id             INTEGER PRIMARY KEY,
        codigo         TEXT    NOT NULL UNIQUE,
        funcao         TEXT    NOT NULL,
        autorizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        usado_por      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        criado_em      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        usado_em       TEXT
    );
    CREATE INDEX autorizacoes_usadas ON autorizacoes(usado_em);
    """,
    # 7 - a autorização pode valer uma vez só, por um tempo ou sem prazo (até alguém encerrar).
    """
    ALTER TABLE autorizacoes ADD COLUMN modo TEXT NOT NULL DEFAULT 'minutos';
    ALTER TABLE autorizacoes ADD COLUMN minutos INTEGER NOT NULL DEFAULT 5;
    ALTER TABLE autorizacoes ADD COLUMN ate TEXT;
    ALTER TABLE autorizacoes ADD COLUMN consumida_em TEXT;
    ALTER TABLE autorizacoes ADD COLUMN revogada_em TEXT;
    ALTER TABLE autorizacoes ADD COLUMN encerrada_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;
    CREATE INDEX autorizacoes_liberadas ON autorizacoes(usado_por, funcao);
    """,
    # 8 - o garçom que atende a mesa (aparece na comanda, no cupom e nas contas fechadas).
    """
    ALTER TABLE comandas ADD COLUMN garcom_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;
    UPDATE comandas SET garcom_id = aberta_por WHERE aberta_por IN (SELECT id FROM usuarios WHERE papel = 'garcom');
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


def _com_autorizacao(detalhe):
    """Quem fez com autorização por QR code: o nome de quem autorizou fica no histórico."""
    if not g.get("autorizado_por"):
        return detalhe
    return f"{detalhe} (autorizado por {g.autorizado_por})" if detalhe else f"autorizado por {g.autorizado_por}"


def anotar_autorizacao(conexao, acao, detalhe, comanda_id):
    """Registra no histórico uma ação feita com autorização (as outras não precisam de registro extra)."""
    if g.get("autorizado_por"):
        with conexao:
            auditar(conexao, acao, detalhe, comanda_id)


def auditar(conexao, acao, detalhe="", comanda_id=None, usuario_id=None):
    """Registra uma ação. Chame dentro da mesma transação da mudança."""
    if usuario_id is None and getattr(g, "usuario", None) is not None:
        usuario_id = g.usuario["id"]
    conexao.execute(
        "INSERT INTO auditoria (usuario_id, comanda_id, acao, detalhe) VALUES (?, ?, ?, ?)",
        (usuario_id, comanda_id, acao,
         _com_autorizacao(detalhe)),
    )

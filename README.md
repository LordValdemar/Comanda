# 🧾 Comanda

Comanda eletrônica para bares, restaurantes e lanchonetes. Roda **no servidor do próprio estabelecimento**, sem depender de internet. Os garçons usam o celular no Wi-Fi da casa, a cozinha acompanha numa TV ou tablet e o caixa fecha a conta e imprime o cupom.

Usa a mesma base do **Painel de Propagandas** (Python + Flask + Waitress + SQLite) e pode ficar **no mesmo servidor Linux**. O painel usa a porta 5000 e a Comanda usa a **5001**.

| Endereço | O que é |
|---|---|
| `http://IP-DO-SERVIDOR:5000` | Painel de Propagandas (já instalado) |
| `http://IP-DO-SERVIDOR:5001` | Comanda |

## O que ela faz

- **Comandas por número** (cartão ou ficha), com mesa e nome do cliente opcionais. Quando a comanda fecha, o número fica livre para ser usado de novo.
- **Lançamento pelo celular**: cardápio por categoria, botões − e +, busca, observação por item ("sem cebola") e lançamento rápido por código.
- **Tela da cozinha** que se atualiza sozinha, com aviso sonoro de pedido novo. Um toque no item avança a etapa (aguardando → preparando → pronto). Segurando o item, ele volta uma etapa.
- **Prontos para servir**: o garçom vê na lista o que a cozinha terminou e marca como entregue.
- Itens que **não passam pela cozinha** (refrigerante em lata, água) já entram como entregues.
- **Fechamento**: taxa de serviço (10% por padrão, dá para tirar), desconto, **conta dividida** entre várias formas de pagamento (dinheiro, PIX, débito, crédito), **troco** calculado e **cupom** para impressora térmica de 80 mm. O cupom não é documento fiscal.
- **Conferência**: imprime a parcial da conta antes de fechar.
- **Relatórios** por período: faturamento, ticket médio, taxa de serviço, descontos, vendas por forma de pagamento, produtos mais vendidos, vendas por garçom e itens cancelados (com motivo e quem cancelou). Também exporta uma planilha CSV que abre no Excel.
- **Equipe com papéis**:

  | Papel | Pode |
  |---|---|
  | Garçom | abrir comandas, lançar pedidos, cancelar um item antes de a cozinha começar |
  | Cozinha | só a tela da cozinha |
  | Caixa | tudo do garçom, mais fechar contas, cancelar, ver as fechadas e os relatórios |
  | Administrador | tudo, mais cardápio, equipe, ajustes e reabrir comanda fechada |

- **Histórico de quem fez o quê**: cancelamentos, descontos, pagamentos removidos e reaberturas.
- **Garçom que fecha conta**: em Usuários, o administrador autoriza um garçom a receber pagamentos, tirar a taxa de serviço e finalizar a conta. Desconto e cancelamento continuam com o caixa.
- **Controle de ponto** (opcional): a equipe só usa o sistema depois de registrar a entrada e dentro do próprio horário. A entrada e a saída são registradas lendo, com o celular, um **QR code** que aparece num aparelho fixo do estabelecimento; ele muda a cada 2 minutos e vale para uma pessoa só. O administrador vê quem está trabalhando, **desconecta** qualquer pessoa de todos os aparelhos e baixa o relatório de horas. Funciona sem internet.
- **Backup automático diário**, mais o botão "fazer backup agora" em Ajustes.
- **Segurança**: verificação em duas etapas (código do aplicativo autenticador), **HTTPS na rede local** com o comando `sudo ./deploy/ativar-https.sh`, senhas guardadas de forma que não dá para ler, bloqueio depois de 5 senhas erradas e proteção contra os ataques comuns em sites.

## Instalação no servidor Linux (o mesmo do painel)

Passo a passo completo em **[docs/INSTALACAO.md](docs/INSTALACAO.md)**. Resumo:

```bash
cd ~
git clone https://github.com/LordValdemar/Comanda.git comanda
cd comanda
sudo ./deploy/instalar-linux.sh
```

Depois, abra `http://IP-DO-SERVIDOR:5001` e crie o administrador.

Para ligar o HTTPS (cadeado): `sudo ./deploy/ativar-https.sh`. A Comanda passa para `https://IP-DO-SERVIDOR:5443`, e cada aparelho instala o certificado uma vez, pela página `http://IP-DO-SERVIDOR:5080/certificado`. Detalhes na seção 5 do guia.

## Desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/flask --app comanda run --debug --port 5001
.venv/bin/python -m pytest -q      # testes
.venv/bin/ruff check .             # estilo
```

## Administração pelo terminal

```bash
.venv/bin/python gerenciar.py listar-usuarios
.venv/bin/python gerenciar.py criar-usuario maria --papel caixa
.venv/bin/python gerenciar.py trocar-senha admin       # esqueceu a senha
.venv/bin/python gerenciar.py desativar-2fa admin      # perdeu o celular da verificação em duas etapas
.venv/bin/python gerenciar.py backup
sudo systemctl stop comanda && .venv/bin/python gerenciar.py restaurar dados/backups/backup-....zip && sudo systemctl start comanda
```

## Configuração (`configuracao.env`)

| Variável | Padrão | Para quê |
|---|---|---|
| `PORTA` | `5001` | porta da Comanda (a 5000 é do painel) |
| `FUSO_HORARIO` | `America/Sao_Paulo` | horários dos pedidos e dos relatórios |
| `BACKUP_MANTER` | `14` | quantos backups diários guardar (`0` desliga) |
| `PASTA_DADOS` | `./dados` | onde ficam o banco, os backups e os logs |
| `HOST`, `ATRAS_DE_PROXY`, `COOKIE_SEGURO` | — | ajustados sozinhos pelo `ativar-https.sh`; não mexa |

O nome do estabelecimento, o endereço no cupom e a taxa de serviço são ajustados pelo próprio sistema, no menu **Ajustes**.

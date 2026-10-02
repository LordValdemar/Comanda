# 🐧 Instalando a Comanda no servidor Linux

Este guia usa **o mesmo servidor** em que o Painel de Propagandas já está instalado (Ubuntu Server, Debian ou Raspberry Pi OS). Os dois sistemas rodam lado a lado, cada um com o seu serviço, a sua pasta e a sua porta:

```
                    Servidor da loja (ex.: 192.168.0.10)
               ┌──────────────────────────────────────────┐
  TVs ───────► │  Painel de Propagandas   porta 5000      │
               │  Comanda                 porta 5001      │ ◄─── celulares dos garçons,
               └──────────────────────────────────────────┘      cozinha e caixa
```

> Ainda não tem o servidor? Siga primeiro o guia **SERVIDOR-LINUX.md** do Painel de Propagandas (passos 1 a 7: instalação do Ubuntu, SSH, atualizações e **IP fixo**). Ele vale igual para a Comanda.

---

## 1. Entre no servidor

Do seu computador:

```bash
ssh seu-usuario@192.168.0.10
```

## 2. Baixe a Comanda

```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/LordValdemar/Comanda.git comanda
cd comanda
```

## 3. Instale

```bash
sudo ./deploy/instalar-linux.sh
```

O instalador:

- cria o ambiente do Python e instala as dependências;
- cria o `configuracao.env` (porta **5001**);
- se o firewall (`ufw`) estiver ligado, **libera a porta 5001** para a mesma rede que já acessa o painel na 5000;
- instala o serviço `comanda`, que liga sozinho com o computador e reinicia se travar.

No fim, ele mostra o endereço, por exemplo `http://192.168.0.10:5001/`.

> O Painel de Propagandas **não é alterado**: ele continua na porta 5000, com os mesmos dados.

## 4. Primeiro acesso

1. No celular ou no computador, conectado ao Wi-Fi do estabelecimento, abra `http://192.168.0.10:5001` (use o IP do seu servidor).
2. Crie o **administrador** e informe o nome do estabelecimento.
3. Em **Cardápio**, crie as categorias (Lanches, Bebidas...) e os produtos. Desmarque "vai para a cozinha" no que sai pronto, como refrigerante em lata.
4. Em **Usuários**, cadastre a equipe: garçons, cozinha e caixa.
5. Em **Ajustes**, confira a taxa de serviço e o texto do cupom.

### Dicas por aparelho

| Aparelho | Como usar |
|---|---|
| **Celular do garçom** | Abra o endereço e use "Adicionar à tela inicial" no menu do navegador: vira um ícone, como um app. |
| **Cozinha** (TV, tablet ou monitor) | Entre com o usuário da cozinha e toque em **Ligar som** para ouvir os pedidos novos. A tela não apaga enquanto estiver aberta, se o navegador permitir. |
| **Caixa** | Computador com a impressora térmica de 80 mm configurada como impressora padrão. Na janela de impressão, escolha a impressora térmica, margens "Nenhuma" e desmarque "cabeçalhos e rodapés". |

## 5. Comandos do dia a dia

```bash
systemctl status comanda              # está rodando?
journalctl -u comanda -f              # logs ao vivo (Ctrl + C para sair)
sudo systemctl restart comanda        # reiniciar (ex.: depois de mudar o configuracao.env)
```

Esqueceu a senha do administrador?

```bash
cd ~/comanda
.venv/bin/python gerenciar.py trocar-senha admin
```

## 6. Atualizar para uma versão nova

```bash
cd ~/comanda
git pull
sudo ./deploy/instalar-linux.sh       # reinstala as dependências e reinicia o serviço
```

Os dados (`dados/`) e o `configuracao.env` são mantidos.

## 7. Backup

- Todo dia o sistema grava um backup em `~/comanda/dados/backups/` e guarda os 14 últimos.
- Em **Ajustes → Fazer backup agora e baixar**, você baixa uma cópia para guardar fora do servidor.
- Para voltar um backup:

  ```bash
  cd ~/comanda
  sudo systemctl stop comanda
  .venv/bin/python gerenciar.py restaurar dados/backups/backup-AAAAMMDD-HHMMSS.zip
  sudo systemctl start comanda
  ```

  O banco atual não é apagado: ele vai para `dados/antes-da-restauracao-<data>/`.

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| O celular não abre o endereço | Confira se ele está no **mesmo Wi-Fi** do servidor. Rode `sudo ufw status` e veja se a porta 5001 aparece liberada. Se não: `sudo ufw allow from 192.168.0.0/24 to any port 5001 proto tcp` (ajuste a rede). |
| "Address already in use" nos logs | Outra coisa está usando a porta 5001. Mude `PORTA=` no `configuracao.env`, rode `sudo systemctl restart comanda` e libere a porta nova no firewall. |
| A cozinha mostra "sem conexão com o servidor" | O tablet saiu do Wi-Fi ou o servidor desligou. A tela volta sozinha quando a conexão voltar. |
| O garçom não consegue cancelar um item | Depois que a cozinha começa um item, só o caixa ou o administrador cancela. |

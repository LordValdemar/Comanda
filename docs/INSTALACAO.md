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

## 5. Segurança (recomendado)

### 5.1. Ligue o HTTPS (cadeado)

Sem o HTTPS, as senhas passam pelo Wi-Fi sem criptografia. Para ligar:

```bash
cd ~/comanda
sudo ./deploy/ativar-https.sh
```

O script instala o **Caddy** e cria um certificado próprio do servidor, sem precisar de domínio nem de internet. Ele também ajusta o firewall. No fim, mostra os dois endereços novos:

| Endereço | Para quê |
|---|---|
| `https://192.168.0.10:5443` | a Comanda, agora com cadeado. Use este daqui em diante. |
| `http://192.168.0.10:5080/certificado` | página para instalar o certificado nos aparelhos |

O endereço antigo (`:5001`) deixa de funcionar na rede: a Comanda só atende pelo HTTPS. O Painel de Propagandas não muda.

**Em cada aparelho** (celulares, tablet da cozinha, computador do caixa), uma vez só:

1. Abra `http://IP-DO-SERVIDOR:5080/certificado`.
2. Toque em **Baixar o certificado** e siga as instruções da página para Android, iPhone ou Windows.
3. Abra a Comanda pelo endereço `https://IP-DO-SERVIDOR:5443`. O cadeado aparece sem aviso.
4. Se tinha posto o ícone na tela inicial, apague-o e crie de novo pelo endereço novo.

> O certificado não dá acesso a nada no aparelho, mas o aparelho passa a confiar neste servidor. Por isso, mantenha o servidor protegido (senha forte, chave SSH). Quando um aparelho sair da equipe, remova o certificado dele.

Outros casos:

```bash
sudo ./deploy/ativar-https.sh 192.168.0.20   # o IP do servidor mudou: rode de novo com o IP novo
sudo ./deploy/ativar-https.sh --desfazer     # voltar para http://IP:5001 (sem cadeado)
```

Se desligar e ligar de novo, o certificado é o mesmo: os aparelhos não precisam instalar outra vez.

### 5.2. Ative a verificação em duas etapas

Com ela, além da senha, o login pede um código de 6 dígitos que muda a cada 30 segundos, gerado por um aplicativo no celular. Assim, mesmo quem descobrir a senha não consegue entrar.

1. Instale no celular um aplicativo autenticador: **Google Authenticator**, **Microsoft Authenticator** ou **Authy** (gratuitos).
2. Na Comanda, entre em **Minha conta**.
3. No aplicativo, escolha "adicionar conta" e leia o **QR code** da tela.
4. Digite o código de 6 dígitos que aparecer no aplicativo e toque em **Ativar**.

Recomendado pelo menos para o **administrador** e o **caixa**. Cada pessoa ativa no próprio usuário. Na tela **Usuários**, quem tem a verificação ativada aparece com o selo 🔒 **2 etapas**.

**Perdeu o celular?**
- O administrador abre **Usuários** e toca em **Tirar 2 etapas** na linha da pessoa. Depois a pessoa ativa de novo com o celular novo.
- Se foi o próprio administrador quem perdeu o celular, no servidor:

  ```bash
  cd ~/comanda
  .venv/bin/python gerenciar.py desativar-2fa admin
  ```

> O relógio do celular precisa estar certo (automático). Se o código nunca é aceito, confira a hora do celular.

## 5.3. Controle de ponto (opcional)

Com o ponto ligado, garçons, caixa e cozinha só usam a Comanda depois de **registrar a entrada**, e só dentro do horário de cada um. O administrador não bate ponto.

1. Entre como administrador e abra **Ponto**.
2. Em **Equipe → Horário de trabalho**, defina os dias e o horário de cada pessoa. Marque **"Não exigir ponto"** no usuário do tablet fixo da cozinha.
3. Clique em **Ligar o controle de ponto**.
4. Em **QR code do ponto**, clique em **Abrir a tela do QR code** num aparelho que fica no estabelecimento (TV, tablet ou o computador do caixa) e deixe em tela cheia.
5. Ao chegar e ao sair, cada pessoa aponta a câmera do celular para o QR e toca em **Registrar**.

O QR code muda a cada 2 minutos e vale para uma pessoa só: quando alguém lê, a tela mostra outro na hora. Uma foto do código não serve depois.

> **Câmera dentro da página:** o botão "Abrir a câmera" da Comanda só funciona com o **HTTPS ligado** (seção 5.1); sem o cadeado, o navegador não libera a câmera. Sem HTTPS, use o **app Câmera** do celular: ele lê o QR e abre o link normalmente.

Para tirar alguém do sistema na hora (em todos os aparelhos), use **Desconectar**, em **Ponto** ou em **Usuários**.

## 6. Comandos do dia a dia

```bash
systemctl status comanda              # está rodando?
journalctl -u comanda -f              # logs ao vivo (Ctrl + C para sair)
sudo systemctl restart comanda        # reiniciar (ex.: depois de mudar o configuracao.env)
```

Com o HTTPS ligado, o Caddy tem o próprio serviço:

```bash
systemctl status comanda-https        # o cadeado está funcionando?
journalctl -u comanda-https -n 50     # ver erros do HTTPS
```

Esqueceu a senha do administrador?

```bash
cd ~/comanda
.venv/bin/python gerenciar.py trocar-senha admin
```

## 7. Atualizar para uma versão nova

```bash
cd ~/comanda
git pull
sudo ./deploy/instalar-linux.sh       # reinstala as dependências e reinicia o serviço
```

Os dados (`dados/`), o `configuracao.env` e o HTTPS (se estiver ligado) são mantidos.

## 8. Backup

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
| Aviso “sua conexão não é particular” | O certificado não foi instalado nesse aparelho: abra `http://IP-DO-SERVIDOR:5080/certificado`. No iPhone, falta ligar a chave em **Ajustes → Geral → Sobre → Ajustes de Confiança de Certificados**. |
| O código das 2 etapas não é aceito | Confira se a hora do celular está em automático. Se perdeu o celular, veja a seção 5.2. |
| Com HTTPS, não abre de jeito nenhum | Rode `systemctl status comanda-https` e `sudo ufw status` (as portas 5443 e 5080 têm de estar liberadas). Se o IP do servidor mudou, rode `sudo ./deploy/ativar-https.sh NOVO-IP`. |
| O celular não abre o endereço | Confira se ele está no **mesmo Wi-Fi** do servidor. Rode `sudo ufw status` e veja se a porta 5001 aparece liberada. Se não: `sudo ufw allow from 192.168.0.0/24 to any port 5001 proto tcp` (ajuste a rede). |
| "Address already in use" nos logs | Outra coisa está usando a porta 5001. Mude `PORTA=` no `configuracao.env`, rode `sudo systemctl restart comanda` e libere a porta nova no firewall. |
| A cozinha mostra "sem conexão com o servidor" | O tablet saiu do Wi-Fi ou o servidor desligou. A tela volta sozinha quando a conexão voltar. |
| O garçom não consegue cancelar um item | Depois que a cozinha começa um item, só o caixa ou o administrador cancela. |

#!/usr/bin/env bash
# Liga o HTTPS (cadeado) da Comanda na rede local, com o Caddy.
#
# Dois jeitos:
#  - Com domínio próprio (recomendado): https://comanda.sualoja.com.br, com certificado do
#    Let's Encrypt, que todo aparelho já reconhece. Não precisa instalar nada nos aparelhos.
#    Precisa do domínio na Cloudflare (gratuito) e de uma chave (token) dela.
#  - Sem domínio: https://IP-DO-SERVIDOR:5443, com certificado do próprio servidor. Cada
#    aparelho instala o certificado uma vez, pela página http://IP-DO-SERVIDOR:5080/certificado
#
# Nos dois casos, a porta 5001 deixa de atender a rede (só o Caddy, no próprio servidor, fala
# com a Comanda), e o endereço https://IP:5443 continua funcionando como reserva.
#
# Uso:  sudo ./deploy/ativar-https.sh --dominio comanda.sualoja.com.br   # com domínio próprio
#       sudo ./deploy/ativar-https.sh                 # sem domínio (ou mantém o domínio já configurado)
#       sudo ./deploy/ativar-https.sh 192.168.0.10    # informa o IP (rode de novo se o IP mudar)
#       sudo ./deploy/ativar-https.sh --novo-token    # troca a chave da Cloudflare
#       sudo ./deploy/ativar-https.sh --sem-dominio   # deixa de usar o domínio (fica só o https://IP:5443)
#       sudo ./deploy/ativar-https.sh --desfazer      # volta para http://IP:5001, sem cadeado
set -euo pipefail

PASTA="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$PASTA/configuracao.env"
DADOS_HTTPS="$PASTA/dados/https"
ARQUIVO_DOMINIO="$DADOS_HTTPS/dominio"
ARQUIVO_TOKEN=/etc/comanda/cloudflare.env
SERVICO_HTTPS=/etc/systemd/system/comanda-https.service
CADDY_DOMINIO=/usr/local/bin/caddy-comanda   # Caddy com o módulo da Cloudflare
PORTA_HTTPS=5443
PORTA_HTTP=5080
MARCA="# --- HTTPS na rede local (gerado por deploy/ativar-https.sh) ---"

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com sudo: sudo $0 $*" >&2
  exit 1
fi
if [ ! -f /etc/systemd/system/comanda.service ] || [ ! -f "$CONFIG" ]; then
  echo "Instale a Comanda primeiro: sudo ./deploy/instalar-linux.sh" >&2
  exit 1
fi
# O serviço roda com o dono da pasta de dados (quem instalou a Comanda).
USUARIO="$(stat -c %U "$PASTA/dados")"
PORTA="$(sed -n 's/^PORTA=\([0-9]*\).*/\1/p' "$CONFIG" | tail -1)"
PORTA="${PORTA:-5001}"

# --- Argumentos --------------------------------------------------------------------------
DESFAZER=""; SEM_DOMINIO=""; NOVO_TOKEN=""; DOMINIO=""; IP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --desfazer) DESFAZER=1 ;;
    --sem-dominio) SEM_DOMINIO=1 ;;
    --novo-token) NOVO_TOKEN=1 ;;
    --dominio)
      [ $# -ge 2 ] || { echo "Informe o domínio: --dominio comanda.sualoja.com.br" >&2; exit 1; }
      DOMINIO="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"; shift ;;
    --dominio=*) DOMINIO="$(printf '%s' "${1#--dominio=}" | tr '[:upper:]' '[:lower:]')" ;;
    -*) echo "Opção desconhecida: $1 (veja o começo deste arquivo)" >&2; exit 1 ;;
    *) IP="$1" ;;
  esac
  shift
done

# Tira do configuracao.env as linhas que este script colocou.
limpar_config() {
  local temporario
  temporario="$(mktemp)"
  grep -vxF "$MARCA" "$CONFIG" | grep -vE '^(HOST|ATRAS_DE_PROXY|COOKIE_SEGURO|ENDERECO_COMANDA)=' > "$temporario" || true
  cat "$temporario" > "$CONFIG"   # cat (e não mv): mantém o dono e a permissão 600 do arquivo
  rm -f "$temporario"
}

# Origem (rede) que o firewall já libera para a Comanda ou para o painel.
origem_firewall() {
  ufw status | awk -v p1="$1" -v p2="$2" '($1 == p1 || $1 == p1"/tcp" || $1 == p2 || $1 == p2"/tcp") && $2 == "ALLOW" && $3 != "Anywhere" {print $3; exit}'
}

firewall_ativo() {
  command -v ufw >/dev/null && ufw status | grep -q "Status: active"
}

porta_livre() {
  python3 -c "import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0', int(sys.argv[1])))" "$1" 2>/dev/null
}

# --- Desligar ----------------------------------------------------------------------------
if [ -n "$DESFAZER" ]; then
  echo "==> Desligando o HTTPS"
  systemctl disable --now comanda-https 2>/dev/null || true
  rm -f "$SERVICO_HTTPS"
  systemctl daemon-reload
  limpar_config
  if firewall_ativo; then
    ORIGEM="$(origem_firewall "$PORTA_HTTPS" 5000)"
    if [ -n "$ORIGEM" ]; then
      ufw allow from "$ORIGEM" to any port "$PORTA" proto tcp >/dev/null
      for p in "$PORTA_HTTPS" "$PORTA_HTTP" 443 8443; do
        ufw delete allow from "$ORIGEM" to any port "$p" proto tcp >/dev/null 2>&1 || true
      done
    fi
  fi
  systemctl restart comanda
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "Pronto. A Comanda voltou para http://${IP:-IP-DO-SERVIDOR}:$PORTA/"
  echo "(O certificado e o domínio ficaram guardados em dados/https: rode o script de novo para religar.)"
  exit 0
fi

# --- IP e domínio ------------------------------------------------------------------------
IP="${IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if ! [[ "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "Não consegui descobrir o IP do servidor. Informe: sudo $0 192.168.0.10" >&2
  exit 1
fi
sudo -u "$USUARIO" mkdir -p "$DADOS_HTTPS"
chmod 700 "$DADOS_HTTPS"
if [ -n "$SEM_DOMINIO" ]; then
  rm -f "$ARQUIVO_DOMINIO"
elif [ -z "$DOMINIO" ] && [ -f "$ARQUIVO_DOMINIO" ]; then
  DOMINIO="$(cat "$ARQUIVO_DOMINIO")"   # mantém o domínio configurado antes
fi
if [ -n "$DOMINIO" ] && ! [[ "$DOMINIO" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]]; then
  echo "Domínio inválido: $DOMINIO (exemplo: comanda.sualoja.com.br)" >&2
  exit 1
fi
echo "==> Pasta da Comanda: $PASTA (usuário $USUARIO)"
echo "==> IP do servidor: $IP"
[ -n "$DOMINIO" ] && echo "==> Domínio: $DOMINIO"

# --- Caddy -------------------------------------------------------------------------------
if [ -n "$DOMINIO" ]; then
  # O Caddy do Ubuntu não fala com a Cloudflare: baixa a versão oficial com esse módulo.
  if [ ! -x "$CADDY_DOMINIO" ] || ! "$CADDY_DOMINIO" list-modules 2>/dev/null | grep -q '^dns.providers.cloudflare$'; then
    echo "==> Baixando o Caddy com o módulo da Cloudflare (pode levar 1 ou 2 minutos)"
    case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
      amd64|x86_64) ARQ="amd64" ;;
      arm64|aarch64) ARQ="arm64" ;;
      armhf|armv7l) ARQ="arm&arm=7" ;;
      *) echo "Arquitetura não suportada: $(uname -m)" >&2; exit 1 ;;
    esac
    command -v curl >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -q curl
    TEMPORARIO="$(mktemp)"
    if ! curl -fsSL --retry 3 --retry-delay 5 --max-time 600 -o "$TEMPORARIO" \
        "https://caddyserver.com/api/download?os=linux&arch=$ARQ&p=github.com%2Fcaddy-dns%2Fcloudflare"; then
      rm -f "$TEMPORARIO"
      echo "Não consegui baixar o Caddy. Confira a internet do servidor e tente de novo em alguns minutos." >&2
      exit 1
    fi
    chmod 755 "$TEMPORARIO"
    if ! "$TEMPORARIO" list-modules 2>/dev/null | grep -q '^dns.providers.cloudflare$'; then
      rm -f "$TEMPORARIO"
      echo "O Caddy baixado veio sem o módulo da Cloudflare. Tente de novo em alguns minutos." >&2
      exit 1
    fi
    mv "$TEMPORARIO" "$CADDY_DOMINIO"
  fi
  CADDY="$CADDY_DOMINIO"
else
  if ! command -v caddy >/dev/null; then
    echo "==> Instalando o Caddy"
    apt-get update -q
    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy 2>/dev/null; then
      # Versões antigas do Ubuntu/Debian não têm o Caddy: usa o repositório oficial.
      DEBIAN_FRONTEND=noninteractive apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
      curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
      apt-get update -q
      DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy
    fi
    # O pacote liga um Caddy de exemplo na porta 80. A Comanda usa o seu próprio (comanda-https):
    # o de exemplo é desligado. Um Caddy que já existia antes (ex.: do painel numa VPS) não é tocado.
    systemctl disable --now caddy >/dev/null 2>&1 || true
  fi
  CADDY="$(command -v caddy)"
fi

# --- Chave da Cloudflare e DNS -----------------------------------------------------------
if [ -n "$DOMINIO" ]; then
  if [ -n "$NOVO_TOKEN" ] || [ ! -s "$ARQUIVO_TOKEN" ]; then
    echo
    echo "Cole a chave (token) da Cloudflare e aperte Enter. Ela não aparece na tela enquanto você cola."
    echo "(Como criar a chave: docs/INSTALACAO.md, seção 5.1)"
    read -rs -p "Chave: " TOKEN
    echo
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || { echo "Nenhuma chave informada." >&2; exit 1; }
  else
    TOKEN="$(sed -n 's/^CLOUDFLARE_API_TOKEN=//p' "$ARQUIVO_TOKEN")"
  fi
  # Confere a chave e aponta o nome para o IP interno do servidor.
  CLOUDFLARE_API_TOKEN="$TOKEN" python3 "$PASTA/deploy/https/cloudflare.py" "$DOMINIO" "$IP"
  mkdir -p /etc/comanda
  chmod 700 /etc/comanda
  ( umask 077; printf 'CLOUDFLARE_API_TOKEN=%s\n' "$TOKEN" > "$ARQUIVO_TOKEN" )
  printf '%s\n' "$DOMINIO" > "$ARQUIVO_DOMINIO"
  chown "$USUARIO" "$ARQUIVO_DOMINIO"
fi

# --- Configuração do Caddy ---------------------------------------------------------------
# Para ver se a porta 443 está livre, o próprio HTTPS da Comanda precisa estar parado.
systemctl stop comanda-https 2>/dev/null || true
if [ -n "$DOMINIO" ]; then
  if porta_livre 443; then PORTA_DOMINIO=443; ENDERECO="https://$DOMINIO"
  else PORTA_DOMINIO=8443; ENDERECO="https://$DOMINIO:8443"
    echo "!!  A porta 443 já é usada por outro programa: a Comanda fica em $ENDERECO"
  fi
else
  ENDERECO="https://$IP:$PORTA_HTTPS"
fi

echo "==> Gerando a configuração do HTTPS"
substituir() {
  sed -e "s#__DADOS__#$PASTA/dados#g" -e "s#__IP__#$IP#g" -e "s#__PORTA_HTTPS__#$PORTA_HTTPS#g" \
    -e "s#__PORTA_HTTP__#$PORTA_HTTP#g" -e "s#__PORTA_DOMINIO__#${PORTA_DOMINIO:-}#g" \
    -e "s#__DOMINIO__#$DOMINIO#g" -e "s#__ENDERECO__#$ENDERECO#g" -e "s#__PORTA__#$PORTA#g" "$1"
}
{
  substituir "$PASTA/deploy/https/Caddyfile.modelo"
  [ -n "$DOMINIO" ] && substituir "$PASTA/deploy/https/Caddyfile.dominio.modelo"
  true
} > "$DADOS_HTTPS/Caddyfile"
chown "$USUARIO" "$DADOS_HTTPS/Caddyfile"
if ! SAIDA="$(sudo -u "$USUARIO" env HOME="$DADOS_HTTPS" XDG_DATA_HOME="$DADOS_HTTPS" XDG_CONFIG_HOME="$DADOS_HTTPS" \
    CLOUDFLARE_API_TOKEN="${TOKEN:-}" "$CADDY" validate --config "$DADOS_HTTPS/Caddyfile" --adapter caddyfile 2>&1)"; then
  echo "$SAIDA" | tail -5 >&2
  echo "A configuração do Caddy é inválida (veja acima)." >&2
  exit 1
fi

echo "==> Ajustando a Comanda para funcionar atrás do HTTPS"
limpar_config
{
  echo "$MARCA"
  echo "HOST=127.0.0.1"       # a porta $PORTA só atende o próprio servidor (o Caddy)
  echo "ATRAS_DE_PROXY=1"
  echo "COOKIE_SEGURO=1"      # o login só vale com o cadeado
  echo "ENDERECO_COMANDA=$ENDERECO"
} >> "$CONFIG"

sed -e "s#__PASTA__#$PASTA#g" -e "s#__USUARIO__#$USUARIO#g" -e "s#__CADDY__#$CADDY#g" \
  "$PASTA/deploy/https/comanda-https.service" > "$SERVICO_HTTPS"
systemctl daemon-reload
systemctl enable comanda-https >/dev/null
systemctl restart comanda
systemctl restart comanda-https

if firewall_ativo; then
  ORIGEM="$(origem_firewall "$PORTA" 5000)"
  [ -z "$ORIGEM" ] && ORIGEM="$(origem_firewall "$PORTA_HTTPS" "$PORTA_HTTP")"
  if [ -n "$ORIGEM" ]; then
    PORTAS="$PORTA_HTTPS $PORTA_HTTP ${PORTA_DOMINIO:-}"
    echo "==> Firewall: liberando as portas ${PORTAS% } para $ORIGEM"
    for p in $PORTAS; do ufw allow from "$ORIGEM" to any port "$p" proto tcp >/dev/null; done
    ufw delete allow from "$ORIGEM" to any port "$PORTA" proto tcp >/dev/null 2>&1 || true
  else
    echo "!!  Firewall ligado: libere as portas para a rede local, por exemplo:"
    for p in $PORTA_HTTPS $PORTA_HTTP ${PORTA_DOMINIO:-}; do
      echo "    sudo ufw allow from 192.168.0.0/24 to any port $p proto tcp"
    done
  fi
fi

echo "==> Conferindo"
for _ in $(seq 1 30); do
  if curl -fsk --max-time 3 "https://$IP:$PORTA_HTTPS/saude" >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
if [ -z "${OK:-}" ]; then
  echo "!!  O HTTPS ainda não respondeu. Veja: journalctl -u comanda-https -n 50" >&2
  exit 1
fi

if [ -n "$DOMINIO" ]; then
  echo "==> Pedindo o certificado do Let's Encrypt para $DOMINIO (costuma levar menos de 1 minuto)"
  for _ in $(seq 1 60); do
    # Sem -k: só passa com o certificado de verdade, reconhecido por qualquer aparelho.
    if curl -fsS --max-time 5 --resolve "$DOMINIO:$PORTA_DOMINIO:127.0.0.1" "$ENDERECO/saude" >/dev/null 2>&1; then
      CERTIFICADO_OK=1; break
    fi
    sleep 3
  done
  if [ -z "${CERTIFICADO_OK:-}" ]; then
    echo "!!  O certificado do domínio ainda não saiu. Enquanto isso, a Comanda funciona em https://$IP:$PORTA_HTTPS" >&2
    echo "    Veja o motivo com:  journalctl -u comanda-https -n 50 --no-pager | grep -i error" >&2
    exit 1
  fi
fi

echo
echo "Pronto! O HTTPS está ligado."
echo "  Endereço da Comanda:  $ENDERECO/"
if [ -n "$DOMINIO" ]; then
  echo "  (Cadeado reconhecido por todos os aparelhos: não precisa instalar certificado.)"
  echo "  Reserva, se o nome não abrir: https://$IP:$PORTA_HTTPS/"
  echo
  echo "Se o IP do servidor mudar, rode de novo: sudo $0 NOVO-IP   (o DNS é atualizado sozinho)"
else
  echo "  Instalar o certificado: http://$IP:$PORTA_HTTP/certificado   (uma vez em cada aparelho)"
  echo
  echo "Para não precisar instalar certificado nos aparelhos, use um domínio próprio:"
  echo "    sudo $0 --dominio comanda.sualoja.com.br   (veja docs/INSTALACAO.md, seção 5.1)"
  echo "Se o IP do servidor mudar, rode de novo: sudo $0 NOVO-IP"
fi
echo "Para voltar ao endereço sem cadeado:    sudo $0 --desfazer"

#!/usr/bin/env bash
# Liga o HTTPS (cadeado) da Comanda na rede local, com o Caddy.
#
# Depois disso a Comanda passa a ser aberta em https://IP-DO-SERVIDOR:5443 e a porta 5001
# deixa de atender a rede (só o Caddy, no próprio servidor, fala com ela).
# Cada aparelho instala o certificado uma vez, pela página http://IP-DO-SERVIDOR:5080/certificado
#
# Uso:  sudo ./deploy/ativar-https.sh                 # usa o IP atual do servidor
#       sudo ./deploy/ativar-https.sh 192.168.0.10    # informa o IP (rode de novo se o IP mudar)
#       sudo ./deploy/ativar-https.sh --desfazer      # volta para http://IP:5001
set -euo pipefail

PASTA="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$PASTA/configuracao.env"
SERVICO_HTTPS=/etc/systemd/system/comanda-https.service
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

# Tira do configuracao.env as linhas que este script colocou.
limpar_config() {
  local temporario
  temporario="$(mktemp)"
  grep -vxF "$MARCA" "$CONFIG" | grep -vE '^(HOST|ATRAS_DE_PROXY|COOKIE_SEGURO)=' > "$temporario" || true
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

if [ "${1:-}" = "--desfazer" ]; then
  echo "==> Desligando o HTTPS"
  systemctl disable --now comanda-https 2>/dev/null || true
  rm -f "$SERVICO_HTTPS"
  systemctl daemon-reload
  limpar_config
  if firewall_ativo; then
    ORIGEM="$(origem_firewall "$PORTA_HTTPS" 5000)"
    if [ -n "$ORIGEM" ]; then
      ufw allow from "$ORIGEM" to any port "$PORTA" proto tcp >/dev/null
      ufw delete allow from "$ORIGEM" to any port "$PORTA_HTTPS" proto tcp >/dev/null 2>&1 || true
      ufw delete allow from "$ORIGEM" to any port "$PORTA_HTTP" proto tcp >/dev/null 2>&1 || true
    fi
  fi
  systemctl restart comanda
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "Pronto. A Comanda voltou para http://${IP:-IP-DO-SERVIDOR}:$PORTA/"
  echo "(O certificado ficou guardado em dados/https: se ligar de novo, os aparelhos não precisam instalar outra vez.)"
  exit 0
fi

IP="${1:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
if ! [[ "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "Não consegui descobrir o IP do servidor. Informe: sudo $0 192.168.0.10" >&2
  exit 1
fi
echo "==> Pasta da Comanda: $PASTA (usuário $USUARIO)"
echo "==> IP do servidor: $IP"

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

echo "==> Gerando a configuração do HTTPS"
sudo -u "$USUARIO" mkdir -p "$PASTA/dados/https"
chmod 700 "$PASTA/dados/https"
sed -e "s#__DADOS__#$PASTA/dados#g" -e "s#__IP__#$IP#g" -e "s#__PORTA_HTTPS__#$PORTA_HTTPS#g" \
  -e "s#__PORTA_HTTP__#$PORTA_HTTP#g" -e "s#__PORTA__#$PORTA#g" \
  "$PASTA/deploy/https/Caddyfile.modelo" > "$PASTA/dados/https/Caddyfile"
chown "$USUARIO" "$PASTA/dados/https/Caddyfile"
if ! SAIDA="$(sudo -u "$USUARIO" env HOME="$PASTA/dados/https" XDG_DATA_HOME="$PASTA/dados/https" \
    XDG_CONFIG_HOME="$PASTA/dados/https" caddy validate --config "$PASTA/dados/https/Caddyfile" --adapter caddyfile 2>&1)"; then
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
} >> "$CONFIG"

sed -e "s#__PASTA__#$PASTA#g" -e "s#__USUARIO__#$USUARIO#g" \
  "$PASTA/deploy/https/comanda-https.service" > "$SERVICO_HTTPS"
systemctl daemon-reload
systemctl enable comanda-https >/dev/null
systemctl restart comanda
systemctl restart comanda-https

if firewall_ativo; then
  ORIGEM="$(origem_firewall "$PORTA" 5000)"
  if [ -n "$ORIGEM" ]; then
    echo "==> Firewall: liberando as portas $PORTA_HTTPS e $PORTA_HTTP para $ORIGEM"
    ufw allow from "$ORIGEM" to any port "$PORTA_HTTPS" proto tcp >/dev/null
    ufw allow from "$ORIGEM" to any port "$PORTA_HTTP" proto tcp >/dev/null
    ufw delete allow from "$ORIGEM" to any port "$PORTA" proto tcp >/dev/null 2>&1 || true
  else
    echo "!!  Firewall ligado: libere as portas para a rede local, por exemplo:"
    echo "    sudo ufw allow from 192.168.0.0/24 to any port $PORTA_HTTPS proto tcp"
    echo "    sudo ufw allow from 192.168.0.0/24 to any port $PORTA_HTTP proto tcp"
  fi
fi

echo "==> Conferindo"
for _ in $(seq 1 30); do
  if curl -fsk --max-time 3 "https://$IP:$PORTA_HTTPS/saude" >/dev/null 2>&1; then
    OK=1
    break
  fi
  sleep 1
done
if [ -z "${OK:-}" ]; then
  echo "!!  O HTTPS ainda não respondeu. Veja: journalctl -u comanda-https -n 50" >&2
  exit 1
fi

echo
echo "Pronto! O HTTPS está ligado."
echo "  Novo endereço da Comanda:  https://$IP:$PORTA_HTTPS/"
echo "  Instalar o certificado:    http://$IP:$PORTA_HTTP/certificado   (uma vez em cada aparelho)"
echo
echo "Se o IP do servidor mudar, rode de novo: sudo $0 NOVO-IP"
echo "Para voltar ao endereço sem cadeado:    sudo $0 --desfazer"

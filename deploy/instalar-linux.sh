#!/usr/bin/env bash
# Instala a Comanda como serviço (Ubuntu Server / Debian / Raspberry Pi OS).
# Pode ser o mesmo servidor do Painel de Propagandas: a Comanda usa a porta 5001.
# Uso:  sudo ./deploy/instalar-linux.sh
set -euo pipefail

PASTA="$(cd "$(dirname "$0")/.." && pwd)"
USUARIO="${SUDO_USER:-$(whoami)}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com sudo: sudo $0" >&2
  exit 1
fi

echo "==> Pasta do programa: $PASTA"
echo "==> Usuário do serviço: $USUARIO"

command -v python3 >/dev/null || { echo "Instale o Python 3: sudo apt install -y python3" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || { echo "É preciso Python 3.10 ou mais novo (use Ubuntu 22.04+, Debian 12+ ou Raspberry Pi OS 12+)." >&2; exit 1; }

# O Ubuntu Server e o Debian não trazem o módulo venv completo (falta o ensurepip).
if ! python3 -c 'import ensurepip, venv' 2>/dev/null; then
  if command -v apt-get >/dev/null; then
    echo "==> Instalando o python3-venv (necessário para o ambiente do Python)"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv
  else
    echo "Instale o módulo venv do Python 3 (pacote python3-venv ou equivalente) e rode de novo." >&2
    exit 1
  fi
fi

# Um ambiente criado pela metade (sem o pip) é apagado e criado de novo.
if [ ! -x "$PASTA/.venv/bin/pip" ]; then
  [ -d "$PASTA/.venv" ] && echo "==> Ambiente virtual incompleto encontrado: recriando" && rm -rf "$PASTA/.venv"
  echo "==> Criando ambiente virtual"
  sudo -u "$USUARIO" python3 -m venv "$PASTA/.venv"
fi
echo "==> Instalando dependências"
sudo -u "$USUARIO" "$PASTA/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$USUARIO" "$PASTA/.venv/bin/pip" install --quiet -r "$PASTA/requirements.txt"
sudo -u "$USUARIO" mkdir -p "$PASTA/dados"

if [ ! -f "$PASTA/configuracao.env" ]; then
  echo "==> Criando o arquivo de configuração (configuracao.env)"
  sudo -u "$USUARIO" cp "$PASTA/configuracao.env.exemplo" "$PASTA/configuracao.env"
fi
chmod 600 "$PASTA/configuracao.env"
PORTA="$(sed -n 's/^PORTA=\([0-9]*\).*/\1/p' "$PASTA/configuracao.env" | tail -1)"
PORTA="${PORTA:-5001}"
# Com o HTTPS ligado (deploy/ativar-https.sh), a Comanda só atende o próprio servidor.
HTTPS_LIGADO=""
grep -q '^HOST=127.0.0.1' "$PASTA/configuracao.env" && [ -f /etc/systemd/system/comanda-https.service ] && HTTPS_LIGADO=1

# Firewall: se o ufw estiver ligado (o guia do Painel de Propagandas liga), libera a porta
# da Comanda para a mesma rede que já acessa o painel na porta 5000.
if [ -z "$HTTPS_LIGADO" ] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ORIGEM="$(ufw status | awk '$1 ~ /^5000(\/tcp)?$/ && $2 == "ALLOW" {print $3; exit}')"
  if [ -n "$ORIGEM" ] && [ "$ORIGEM" != "Anywhere" ]; then
    echo "==> Firewall: liberando a porta $PORTA para $ORIGEM"
    ufw allow from "$ORIGEM" to any port "$PORTA" proto tcp >/dev/null
  else
    echo "!!  Firewall ligado: libere a porta $PORTA para a rede local, por exemplo:"
    echo "    sudo ufw allow from 192.168.0.0/24 to any port $PORTA proto tcp"
  fi
fi

echo "==> Instalando o serviço"
sed -e "s#__PASTA__#$PASTA#g" -e "s#__USUARIO__#$USUARIO#g" \
  "$PASTA/deploy/comanda.service" > /etc/systemd/system/comanda.service
systemctl daemon-reload
systemctl enable comanda >/dev/null
systemctl restart comanda

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Pronto! A Comanda inicia sozinha quando o computador ligar."
if [ -n "$HTTPS_LIGADO" ]; then
  echo "  Endereço:     https://${IP:-localhost}:5443/   (HTTPS ligado)"
else
  echo "  Endereço:     http://${IP:-localhost}:$PORTA/   (abra no celular, no Wi-Fi do estabelecimento)"
  echo "  Para ligar o HTTPS (cadeado): sudo ./deploy/ativar-https.sh"
fi
echo "  Configuração: $PASTA/configuracao.env (depois de editar: sudo systemctl restart comanda)"
echo
echo "Comandos úteis:"
echo "  systemctl status comanda          # ver se está rodando"
echo "  journalctl -u comanda -f          # acompanhar os logs"
echo "  sudo systemctl restart comanda"

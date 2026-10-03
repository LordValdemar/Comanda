"""deploy/https/cloudflare.py contra uma Cloudflare de mentira (servidor HTTP local)."""

import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

CAMINHO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "https", "cloudflare.py")
TOKEN_BOM = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-Ab"  # mesmo formato de uma chave real


def carregar_modulo():
    especificacao = importlib.util.spec_from_file_location("cloudflare", CAMINHO)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


class CloudflareFalsa(BaseHTTPRequestHandler):
    zonas = {}       # nome -> {"id", "name", "status"}
    registros = {}   # id -> registro
    chamadas = []

    def log_message(self, *args):
        pass

    def responder(self, codigo, corpo):
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def tratar(self):
        url = urlparse(self.path)
        consulta = {k: v[0] for k, v in parse_qs(url.query).items()}
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = json.loads(self.rfile.read(tamanho)) if tamanho else None
        CloudflareFalsa.chamadas.append((self.command, url.path, corpo))
        if self.headers.get("Authorization") != f"Bearer {TOKEN_BOM}":
            return self.responder(403, {"success": False, "errors": [{"message": "Invalid API Token"}]})
        partes = url.path.strip("/").split("/")
        if url.path == "/user/tokens/verify":
            return self.responder(200, {"success": True, "result": {"status": "active"}})
        if url.path == "/zones":
            zona = CloudflareFalsa.zonas.get(consulta.get("name"))
            return self.responder(200, {"success": True, "result": [zona] if zona else []})
        if len(partes) >= 3 and partes[0] == "zones" and partes[2] == "dns_records":
            if self.command == "GET":
                achados = [r for r in CloudflareFalsa.registros.values()
                           if r["name"] == consulta.get("name") and r["type"] == consulta.get("type")]
                return self.responder(200, {"success": True, "result": achados})
            if self.command == "POST":
                registro = dict(corpo, id=f"r{len(CloudflareFalsa.registros) + 1}")
                CloudflareFalsa.registros[registro["id"]] = registro
                return self.responder(200, {"success": True, "result": registro})
            if self.command == "PUT":
                CloudflareFalsa.registros[partes[3]] = dict(corpo, id=partes[3])
                return self.responder(200, {"success": True, "result": CloudflareFalsa.registros[partes[3]]})
        return self.responder(404, {"success": False, "errors": [{"message": "not found"}]})

    do_GET = do_POST = do_PUT = tratar


@pytest.fixture
def cloudflare(monkeypatch):
    CloudflareFalsa.zonas = {"comercialgustavo.com.br": {"id": "z1", "name": "comercialgustavo.com.br", "status": "active"}}
    CloudflareFalsa.registros = {}
    CloudflareFalsa.chamadas = []
    servidor = HTTPServer(("127.0.0.1", 0), CloudflareFalsa)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN_BOM)
    modulo = carregar_modulo()
    monkeypatch.setattr(modulo, "API", f"http://127.0.0.1:{servidor.server_port}")
    yield modulo
    servidor.shutdown()


def test_cria_e_depois_atualiza_o_nome(cloudflare):
    cloudflare.apontar("comanda.comercialgustavo.com.br", "192.168.3.119")
    (registro,) = CloudflareFalsa.registros.values()
    assert registro["name"] == "comanda.comercialgustavo.com.br"
    assert registro["content"] == "192.168.3.119"
    assert registro["proxied"] is False  # IP interno: a Cloudflare não pode ficar no meio
    # O IP do servidor mudou: rodar de novo atualiza o mesmo registro, sem duplicar.
    cloudflare.apontar("comanda.comercialgustavo.com.br", "192.168.3.200")
    (registro,) = CloudflareFalsa.registros.values()
    assert registro["content"] == "192.168.3.200"


def test_acha_a_zona_subindo_pelo_nome(cloudflare):
    assert cloudflare.achar_zona("comanda.comercialgustavo.com.br")["id"] == "z1"
    assert cloudflare.achar_zona("comanda.outrodominio.com.br") is None


def test_chave_errada(cloudflare, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "errada")
    with pytest.raises(cloudflare.ErroCloudflare, match="Invalid API Token"):
        cloudflare.apontar("comanda.comercialgustavo.com.br", "192.168.3.119")
    assert CloudflareFalsa.registros == {}


def test_dominio_fora_da_conta(cloudflare):
    with pytest.raises(cloudflare.ErroCloudflare, match="não está nesta conta"):
        cloudflare.apontar("comanda.outrodominio.com.br", "192.168.3.119")

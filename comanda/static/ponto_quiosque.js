// Tela do QR code do ponto: pergunta ao servidor a cada 2 segundos e troca o código quando
// ele muda (a cada 2 minutos, ou logo depois que alguém usou o código atual).
"use strict";

(function () {
  const api = document.body.dataset.api;
  const qr = document.getElementById("qr");
  const aviso = document.getElementById("aviso");
  const relogio = document.getElementById("relogio");
  const AVISO_PADRAO = "Cada código vale para uma pessoa. Depois de ler, aguarde o próximo.";
  let versao = "";
  let espera = null;
  let fimDoAvisoUsado = 0;

  function geracao(v) { return v ? v.split("-")[0] : ""; }

  async function atualizar() {
    clearTimeout(espera);
    try {
      const resposta = await fetch(api + "?versao=" + encodeURIComponent(versao), { cache: "no-store" });
      if (!resposta.ok) throw new Error("HTTP " + resposta.status);
      const dados = await resposta.json();
      if (!dados.ativo) {
        qr.removeAttribute("src");
        versao = "";
        aviso.textContent = "O controle de ponto está desligado.";
        aviso.className = "aviso erro";
      } else {
        if (dados.qr) {
          // Mudou a geração (não só o horário): alguém acabou de usar o código.
          if (versao && geracao(dados.versao) !== geracao(versao)) fimDoAvisoUsado = Date.now() + 5000;
          qr.src = dados.qr;
          versao = dados.versao;
        }
        if (Date.now() < fimDoAvisoUsado) {
          aviso.textContent = "✓ Código usado. Este é o novo código.";
          aviso.className = "aviso ok";
        } else {
          aviso.textContent = AVISO_PADRAO;
          aviso.className = "aviso";
        }
      }
      espera = setTimeout(atualizar, 2000);
    } catch (erro) {
      aviso.textContent = "Sem conexão com o servidor. Tentando de novo…";
      aviso.className = "aviso erro";
      espera = setTimeout(atualizar, 5000);
    }
  }

  function tique() {
    relogio.textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  setInterval(tique, 1000);
  tique();
  atualizar();
  // Tela ligada o dia todo: recarrega a página uma vez por dia para receber atualizações.
  setTimeout(function () { location.reload(); }, 24 * 60 * 60 * 1000);
})();

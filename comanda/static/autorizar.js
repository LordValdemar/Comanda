// Página "Autorizar": conta o tempo do QR code e avisa quando ele é lido.
"use strict";

(function () {
  const caixa = document.getElementById("autorizacao");
  if (!caixa) return;
  const tempo = document.getElementById("autorizacao-tempo");
  const estado = document.getElementById("autorizacao-estado");
  const usado = document.getElementById("autorizacao-usado");
  const imagem = caixa.querySelector("img");
  const fim = Date.now() + Number(caixa.dataset.validade) * 1000;
  let terminou = false;

  function relogio() {
    if (terminou) return;
    const resta = Math.max(0, Math.round((fim - Date.now()) / 1000));
    tempo.textContent = Math.floor(resta / 60) + ":" + String(resta % 60).padStart(2, "0");
    if (resta === 0) {
      terminou = true;
      estado.textContent = "Este código venceu. Toque em “Novo código”.";
      imagem.classList.add("vencido");
      return;
    }
    setTimeout(relogio, 1000);
  }

  async function conferir() {
    if (terminou) return;
    try {
      const resposta = await fetch(caixa.dataset.situacao, { headers: { Accept: "application/json" } });
      const dados = await resposta.json();
      if (dados.situacao === "usado") {
        terminou = true;
        document.getElementById("autorizacao-quem").textContent = dados.por;
        usado.hidden = false;
        estado.hidden = true;
        imagem.classList.add("vencido");
        return;
      }
      if (dados.situacao === "trocado") {
        terminou = true;
        estado.textContent = "Você abriu outro código; este não vale mais.";
        imagem.classList.add("vencido");
        return;
      }
    } catch (erro) { /* sem rede: tenta de novo */ }
    setTimeout(conferir, 2500);
  }

  relogio();
  conferir();
})();

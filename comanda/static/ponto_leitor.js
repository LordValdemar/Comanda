// Leitor de QR code do ponto: abre a câmera traseira do celular e, ao achar o QR do ponto,
// vai para o endereço dele. Usa o leitor do próprio navegador (BarcodeDetector) quando existe
// e o jsQR nos outros (ex.: Safari do iPhone).
"use strict";

(function () {
  const botao = document.getElementById("abrir-camera");
  if (!botao) return;
  const area = document.getElementById("leitor");
  const video = document.getElementById("leitor-video");
  const aviso = document.getElementById("leitor-aviso");
  const fechar = document.getElementById("fechar-camera");
  const tela = document.createElement("canvas");
  const contexto = tela.getContext("2d", { willReadFrequently: true });
  let fluxo = null;
  let detector = null;
  let lendo = false;

  if ("BarcodeDetector" in window) {
    try { detector = new BarcodeDetector({ formats: ["qr_code"] }); } catch (erro) { detector = null; }
  }

  function mostrar(texto, erro) {
    aviso.textContent = texto;
    aviso.classList.toggle("erro", Boolean(erro));
  }

  function parar() {
    lendo = false;
    if (fluxo) fluxo.getTracks().forEach(function (t) { t.stop(); });
    fluxo = null;
    video.srcObject = null;
    area.hidden = true;
    botao.hidden = false;
  }

  // Só aceita QR deste site com o caminho esperado (data-prefixo do botão; o padrão é o do ponto):
  // um QR qualquer não leva o celular para outro lugar.
  const prefixo = botao.dataset.prefixo || "/ponto/qr/";
  const alvo = botao.dataset.alvo || "a tela do ponto";
  function enderecoDoPonto(texto) {
    try {
      const url = new URL(texto);
      if (url.origin === location.origin && url.pathname.indexOf(prefixo) === 0) return url.href;
    } catch (erro) { /* não é um endereço */ }
    return null;
  }

  async function lerQuadro() {
    if (!lendo) return;
    if (video.readyState >= 2 && video.videoWidth) {
      let texto = null;
      try {
        if (detector) {
          const achados = await detector.detect(video);
          if (achados.length) texto = achados[0].rawValue;
        } else if (window.jsQR) {
          const largura = Math.min(video.videoWidth, 640);
          const altura = Math.round(video.videoHeight * largura / video.videoWidth);
          tela.width = largura;
          tela.height = altura;
          contexto.drawImage(video, 0, 0, largura, altura);
          const achado = jsQR(contexto.getImageData(0, 0, largura, altura).data, largura, altura, { inversionAttempts: "dontInvert" });
          if (achado) texto = achado.data;
        }
      } catch (erro) { /* quadro ruim: tenta o próximo */ }
      if (texto) {
        const destino = enderecoDoPonto(texto);
        if (destino) {
          mostrar("QR code lido! Abrindo…");
          parar();
          location.href = destino;
          return;
        }
        mostrar("Este não é o QR code esperado. Aponte para " + alvo + ".", true);
      }
    }
    setTimeout(lerQuadro, 200);
  }

  botao.addEventListener("click", async function () {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      area.hidden = false;
      // Na rede local sem cadeado (http://), o navegador não deixa abrir a câmera.
      mostrar(location.protocol === "https:"
        ? "Este navegador não abre a câmera. Use o app Câmera do celular e aponte para o QR code."
        : "Sem o cadeado (HTTPS) o navegador não abre a câmera aqui. Use o app Câmera do celular e aponte para o QR code.", true);
      return;
    }
    botao.hidden = true;
    area.hidden = false;
    mostrar("Aponte para " + (botao.dataset.alvo ? alvo : "o QR code na tela do ponto") + ".");
    try {
      fluxo = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      video.srcObject = fluxo;
      await video.play();
      lendo = true;
      lerQuadro();
    } catch (erro) {
      parar();
      area.hidden = false;
      mostrar("Não foi possível abrir a câmera. Permita o acesso à câmera para este site (nos ajustes do navegador) " +
              "ou use o app Câmera do celular.", true);
    }
  });

  fechar.addEventListener("click", parar);
  window.addEventListener("pagehide", parar);
})();

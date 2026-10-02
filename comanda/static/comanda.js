// Pequenas ajudas nas telas. Tudo funciona sem JavaScript; aqui só fica mais rápido de usar.
(function () {
  "use strict";

  // Confirmação (data-confirmar) e pedido de motivo (data-pedir-motivo) antes de enviar.
  // Fica no documento inteiro: vale também para as partes da tela que se atualizam sozinhas.
  document.addEventListener("submit", function (evento) {
    var form = evento.target;
    if (form.dataset.confirmar && !confirm(form.dataset.confirmar)) { evento.preventDefault(); return; }
    if (form.dataset.pedirMotivo) {
      var motivo = prompt(form.dataset.pedirMotivo, "");
      if (!motivo || !motivo.trim()) { evento.preventDefault(); return; }
      form.querySelector("input[name=motivo]").value = motivo.trim();
    }
  });

  document.querySelectorAll("select[data-enviar-ao-mudar]").forEach(function (campo) {
    campo.addEventListener("change", function () { campo.form.submit(); });
  });

  // Lançamento de pedido: botões − e +, busca no cardápio e contador no botão de enviar.
  var formPedido = document.getElementById("form-pedido");
  if (formPedido) {
    var enviar = document.getElementById("enviar-pedido");
    var atualizarContador = function () {
      var total = 0;
      formPedido.querySelectorAll(".produto-lancar input[type=number]").forEach(function (campo) {
        var n = parseInt(campo.value, 10);
        if (n > 0) total += n;
        campo.closest(".produto-lancar").classList.toggle("escolhido", n > 0);
      });
      enviar.textContent = total ? "Enviar pedido (" + total + ")" : "Enviar pedido";
    };
    formPedido.addEventListener("click", function (evento) {
      var botao = evento.target.closest(".mais, .menos");
      if (!botao) return;
      var campo = botao.parentNode.querySelector("input");
      var n = (parseInt(campo.value, 10) || 0) + (botao.classList.contains("mais") ? 1 : -1);
      campo.value = Math.max(0, Math.min(999, n));
      atualizarContador();
    });
    formPedido.addEventListener("input", atualizarContador);
    formPedido.addEventListener("submit", function () {
      enviar.disabled = true;  // evita lançar o mesmo pedido duas vezes com toque duplo
      enviar.textContent = "Enviando...";
    });

    var filtro = document.getElementById("filtro-produtos");
    var semAcento = function (texto) { return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
    filtro.addEventListener("input", function () {
      var busca = semAcento(filtro.value.trim());
      document.querySelectorAll(".categoria-produtos").forEach(function (categoria) {
        var algum = false;
        categoria.querySelectorAll(".produto-lancar").forEach(function (produto) {
          var mostra = !busca || semAcento(produto.dataset.nome).indexOf(busca) !== -1;
          produto.hidden = !mostra;
          algum = algum || mostra;
        });
        categoria.hidden = !algum;
      });
    });
    // Enter na busca não envia o pedido.
    filtro.addEventListener("keydown", function (evento) { if (evento.key === "Enter") evento.preventDefault(); });
  }

  // Partes da tela que mudam sozinhas (data-atualizar): comandas abertas, prontos para servir,
  // itens da comanda. Busca a própria página de novo e troca só essas partes, sem atrapalhar
  // quem está digitando em outro lugar da tela.
  var regioes = document.querySelectorAll("[data-atualizar]");
  if (regioes.length) {
    var prontosAntes = document.querySelectorAll("[data-pronto]").length;
    var audio = null;
    // Som e vibração só funcionam depois de um toque na tela (regra dos navegadores).
    document.addEventListener("click", function () {
      if (!audio && (window.AudioContext || window.webkitAudioContext)) audio = new (window.AudioContext || window.webkitAudioContext)();
    }, { once: true });
    var avisarPronto = function () {
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      if (!audio) return;
      var osc = audio.createOscillator();
      var volume = audio.createGain();
      osc.frequency.value = 660;
      volume.gain.value = 0.25;
      osc.connect(volume);
      volume.connect(audio.destination);
      osc.start();
      osc.stop(audio.currentTime + 0.2);
    };
    var atualizarRegioes = function () {
      if (document.visibilityState !== "visible") return;
      // Sem os parâmetros da busca: só as partes da tela interessam (e a busca poderia redirecionar).
      fetch(location.pathname, { credentials: "same-origin", headers: { "X-Atualizacao": "1" } })
        .then(function (resposta) {
          // Sessão expirada ou comanda fechada por outra pessoa: recarrega a página inteira.
          if (resposta.redirected || !resposta.ok) { location.reload(); throw new Error("recarregar"); }
          return resposta.text();
        })
        .then(function (html) {
          var nova = new DOMParser().parseFromString(html, "text/html");
          regioes.forEach(function (regiao) {
            var substituta = nova.getElementById(regiao.id);
            // Não troca a parte em que a pessoa está mexendo agora.
            if (!substituta || regiao.contains(document.activeElement)) return;
            if (regiao.innerHTML !== substituta.innerHTML) regiao.innerHTML = substituta.innerHTML;
          });
          var prontosAgora = document.querySelectorAll("[data-pronto]").length;
          if (prontosAgora > prontosAntes) avisarPronto();
          prontosAntes = prontosAgora;
        })
        .catch(function () {});
    };
    setInterval(atualizarRegioes, 5000);
    document.addEventListener("visibilitychange", atualizarRegioes);
  }

  // Cupom: botão de imprimir e impressão automática depois de fechar a conta.
  var imprimir = document.getElementById("imprimir");
  if (imprimir) {
    imprimir.addEventListener("click", function () { window.print(); });
    if (document.body.hasAttribute("data-imprimir")) window.addEventListener("load", function () { window.print(); });
  }
})();

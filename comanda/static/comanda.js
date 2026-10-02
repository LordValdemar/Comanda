// Pequenas ajudas nas telas. Tudo funciona sem JavaScript; aqui só fica mais rápido de usar.
(function () {
  "use strict";

  // Confirmação antes de enviar formulários marcados com data-confirmar.
  document.querySelectorAll("form[data-confirmar]").forEach(function (form) {
    form.addEventListener("submit", function (evento) {
      if (!confirm(form.dataset.confirmar)) evento.preventDefault();
    });
  });

  // Pede o motivo (cancelamento de item) e o coloca no campo escondido.
  document.querySelectorAll("form[data-pedir-motivo]").forEach(function (form) {
    form.addEventListener("submit", function (evento) {
      var motivo = prompt(form.dataset.pedirMotivo, "");
      if (!motivo || !motivo.trim()) { evento.preventDefault(); return; }
      form.querySelector("input[name=motivo]").value = motivo.trim();
    });
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

  // Listas que mudam sozinhas (comandas abertas): recarrega se ninguém estiver digitando.
  var segundos = parseInt(document.body.dataset.recarregar, 10);
  if (segundos > 0) {
    var mexeu = false;
    document.addEventListener("input", function () { mexeu = true; });
    setInterval(function () {
      var ativo = document.activeElement;
      var digitando = ativo && (ativo.tagName === "INPUT" || ativo.tagName === "SELECT");
      if (!mexeu && !digitando && document.visibilityState === "visible") location.reload();
    }, segundos * 1000);
  }

  // Cupom: botão de imprimir e impressão automática depois de fechar a conta.
  var imprimir = document.getElementById("imprimir");
  if (imprimir) {
    imprimir.addEventListener("click", function () { window.print(); });
    if (document.body.hasAttribute("data-imprimir")) window.addEventListener("load", function () { window.print(); });
  }
})();

// Tela da cozinha: busca os pedidos a cada poucos segundos e avisa com som quando chega item novo.
(function () {
  "use strict";

  var INTERVALO = 4000;
  var corpo = document.body;
  var api = corpo.dataset.api;
  var csrf = corpo.dataset.csrf;
  var lista = document.getElementById("pedidos");
  var estado = document.getElementById("estado-conexao");
  var botaoSom = document.getElementById("som");
  var NOMES = { pendente: "aguardando", preparando: "preparando", pronto: "pronto" };

  var conhecidos = null;  // ids já vistos (null = primeira carga, sem apito)
  var somLigado = false;
  var audio = null;

  // O navegador só deixa tocar som depois de um toque na tela: por isso o botão.
  botaoSom.addEventListener("click", function () {
    somLigado = !somLigado;
    if (somLigado && !audio) audio = new (window.AudioContext || window.webkitAudioContext)();
    botaoSom.textContent = somLigado ? "🔔 Som ligado" : "🔕 Ligar som";
    if (somLigado) apitar();
    manterTelaLigada();
  });

  function apitar() {
    if (!somLigado || !audio) return;
    [0, 0.25].forEach(function (atraso) {
      var osc = audio.createOscillator();
      var volume = audio.createGain();
      osc.frequency.value = 880;
      volume.gain.value = 0.3;
      osc.connect(volume);
      volume.connect(audio.destination);
      osc.start(audio.currentTime + atraso);
      osc.stop(audio.currentTime + atraso + 0.15);
    });
  }

  function manterTelaLigada() {
    if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(function () {});
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && somLigado) manterTelaLigada();
  });

  function elemento(tag, classe, texto) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texto !== undefined) el.textContent = texto;  // textContent: nada digitado vira HTML
    return el;
  }

  function desenhar(comandas) {
    lista.textContent = "";
    if (!comandas.length) {
      lista.appendChild(elemento("p", "vazio", "Nenhum pedido na fila. 👌"));
      return;
    }
    comandas.forEach(function (comanda) {
      var cartao = elemento("div", "pedido" + (comanda.tudo_pronto ? " tudo-pronto" : "") + (comanda.minutos >= 20 ? " atrasado" : ""));
      var topo = elemento("div", "pedido-topo");
      topo.appendChild(elemento("b", "", "Comanda " + comanda.numero + (comanda.mesa ? " · Mesa " + comanda.mesa : "")));
      topo.appendChild(elemento("span", "", comanda.minutos + " min"));
      cartao.appendChild(topo);
      comanda.itens.forEach(function (item) {
        var botao = elemento("button", "item-cozinha estado-" + item.status);
        botao.type = "button";
        botao.dataset.id = item.id;
        var linha = elemento("span", "item-nome", item.quantidade + "× " + item.nome);
        botao.appendChild(linha);
        if (item.observacao) botao.appendChild(elemento("span", "item-obs", "📝 " + item.observacao));
        botao.appendChild(elemento("span", "item-meta", NOMES[item.status] + " · " + item.hora + (item.garcom ? " · " + item.garcom : "")));
        cartao.appendChild(botao);
      });
      lista.appendChild(cartao);
    });
  }

  function atualizar() {
    fetch(api, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (resposta) {
        if (resposta.status === 401) { location.reload(); throw new Error("sessão expirada"); }
        if (!resposta.ok) throw new Error("HTTP " + resposta.status);
        return resposta.json();
      })
      .then(function (dados) {
        var ids = {};
        var novo = false;
        dados.comandas.forEach(function (c) {
          c.itens.forEach(function (i) {
            ids[i.id] = true;
            if (conhecidos && !conhecidos[i.id]) novo = true;
          });
        });
        if (novo) apitar();
        conhecidos = ids;
        desenhar(dados.comandas);
        estado.textContent = "conectado";
        estado.className = "status online";
      })
      .catch(function () {
        estado.textContent = "sem conexão com o servidor";
        estado.className = "status offline";
      });
  }

  function mudar(id, direcao) {
    var corpoPedido = new URLSearchParams({ direcao: direcao });
    fetch(api + "/itens/" + id, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf, "Content-Type": "application/x-www-form-urlencoded" },
      body: corpoPedido,
    }).then(atualizar, atualizar);
  }

  // Toque avança; toque longo (ou botão direito) volta um passo.
  var segurando = null;
  var voltou = false;
  lista.addEventListener("pointerdown", function (evento) {
    var botao = evento.target.closest(".item-cozinha");
    if (!botao) return;
    voltou = false;
    segurando = setTimeout(function () {
      if (!voltou) { voltou = true; mudar(botao.dataset.id, "voltar"); }
    }, 700);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach(function (nome) {
    lista.addEventListener(nome, function () { clearTimeout(segurando); });
  });
  lista.addEventListener("click", function (evento) {
    var botao = evento.target.closest(".item-cozinha");
    if (!botao || voltou) return;
    botao.disabled = true;
    mudar(botao.dataset.id, "avancar");
  });
  lista.addEventListener("contextmenu", function (evento) {
    var botao = evento.target.closest(".item-cozinha");
    if (!botao) return;
    evento.preventDefault();
    clearTimeout(segurando);
    if (!voltou) { voltou = true; mudar(botao.dataset.id, "voltar"); }
  });

  atualizar();
  setInterval(atualizar, INTERVALO);
})();

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
  var recentes = document.getElementById("recentes");
  var recentesLista = document.getElementById("recentes-lista");
  var recentesTotal = document.getElementById("recentes-total");
  var aviso = document.getElementById("aviso-desfazer");
  var avisoTexto = document.getElementById("aviso-desfazer-texto");
  var botaoDesfazer = document.getElementById("botao-desfazer");

  // Botões de cada item, na ordem do preparo.
  var SITUACOES = [
    ["pendente", "Aguardando"],
    ["preparando", "Preparando"],
    ["pronto", "Pronto"],
    ["entregue", "Entregue"],
  ];
  var NOMES = {};
  SITUACOES.forEach(function (s) { NOMES[s[0]] = s[1]; });

  var conhecidos = null;   // ids já vistos (null = primeira carga, sem apito)
  var somLigado = false;
  var audio = null;
  var ultimaMudanca = null; // para o botão "Desfazer"
  var timerAviso = null;
  var ocupado = false;      // evita redesenhar enquanto um toque está sendo enviado

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

  function botoesDeSituacao(item) {
    var grupo = elemento("div", "botoes-estado");
    SITUACOES.forEach(function (s) {
      var botao = elemento("button", "botao-estado estado-" + s[0] + (item.status === s[0] ? " ativo" : ""), s[1]);
      botao.type = "button";
      botao.dataset.id = item.id;
      botao.dataset.status = s[0];
      botao.dataset.anterior = item.status;
      botao.dataset.nome = item.quantidade + "× " + item.nome;
      if (item.status === s[0]) botao.setAttribute("aria-pressed", "true");
      grupo.appendChild(botao);
    });
    return grupo;
  }

  function desenhar(dados) {
    lista.textContent = "";
    if (!dados.comandas.length) {
      lista.appendChild(elemento("p", "vazio", "Nenhum pedido na fila. 👌"));
    }
    dados.comandas.forEach(function (comanda) {
      var cartao = elemento("div", "pedido" + (comanda.tudo_pronto ? " tudo-pronto" : "") + (comanda.minutos >= 20 ? " atrasado" : ""));
      var topo = elemento("div", "pedido-topo");
      topo.appendChild(elemento("b", "", "Comanda " + comanda.numero + (comanda.mesa ? " · Mesa " + comanda.mesa : "")));
      topo.appendChild(elemento("span", "", comanda.minutos + " min"));
      cartao.appendChild(topo);
      comanda.itens.forEach(function (item) {
        var bloco = elemento("div", "item-cozinha estado-" + item.status);
        bloco.appendChild(elemento("span", "item-nome", item.quantidade + "× " + item.nome));
        if (item.observacao) bloco.appendChild(elemento("span", "item-obs", "📝 " + item.observacao));
        bloco.appendChild(elemento("span", "item-meta", "pedido às " + item.hora + (item.garcom ? " · " + item.garcom : "")));
        bloco.appendChild(botoesDeSituacao(item));
        cartao.appendChild(bloco);
      });
      if (!comanda.tudo_pronto && comanda.itens.length > 1) {
        var tudo = elemento("button", "tudo-pronto-botao", "✔ Tudo pronto");
        tudo.type = "button";
        tudo.dataset.comanda = comanda.comanda_id;
        cartao.appendChild(tudo);
      }
      lista.appendChild(cartao);
    });

    // Entregues há pouco: dá para trazer de volta se foi engano.
    recentesLista.textContent = "";
    recentes.hidden = !dados.recentes.length;
    recentesTotal.textContent = dados.recentes.length;
    dados.recentes.forEach(function (item) {
      var linha = elemento("div", "recente");
      linha.appendChild(elemento("span", "", item.quantidade + "× " + item.nome + " · comanda " + item.numero +
        (item.mesa ? " · mesa " + item.mesa : "") + " · entregue às " + item.hora));
      var voltar = elemento("button", "botao-estado estado-pronto", "Voltar para Pronto");
      voltar.type = "button";
      voltar.dataset.id = item.id;
      voltar.dataset.status = "pronto";
      voltar.dataset.anterior = "entregue";
      voltar.dataset.nome = item.quantidade + "× " + item.nome;
      linha.appendChild(voltar);
      recentesLista.appendChild(linha);
    });
  }

  function atualizar() {
    return fetch(api, { credentials: "same-origin", headers: { Accept: "application/json" } })
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
            if (conhecidos && !conhecidos[i.id] && i.status === "pendente") novo = true;
          });
        });
        if (novo) apitar();
        conhecidos = ids;
        if (!ocupado) desenhar(dados);
        estado.textContent = "conectado";
        estado.className = "status online";
      })
      .catch(function () {
        estado.textContent = "sem conexão com o servidor";
        estado.className = "status offline";
      });
  }

  function enviar(url, corpoPedido) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf, "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(corpoPedido || {}),
    }).then(function (resposta) {
      if (!resposta.ok) throw new Error("HTTP " + resposta.status);
      return resposta;
    });
  }

  function mudar(id, status) {
    return enviar(api + "/itens/" + id, { status: status });
  }

  function mostrarDesfazer(texto, mudanca) {
    ultimaMudanca = mudanca;
    avisoTexto.textContent = texto;
    aviso.hidden = false;
    clearTimeout(timerAviso);
    timerAviso = setTimeout(function () { aviso.hidden = true; ultimaMudanca = null; }, 10000);
  }

  document.addEventListener("click", function (evento) {
    var botao = evento.target.closest(".botao-estado");
    if (botao) {
      var id = botao.dataset.id;
      var anterior = botao.dataset.anterior;
      var status = botao.dataset.status;
      if (status === anterior) return;
      ocupado = true;
      // Mostra na hora o que foi tocado; a confirmação do servidor vem logo em seguida.
      botao.parentNode.querySelectorAll(".botao-estado").forEach(function (b) { b.classList.remove("ativo"); });
      botao.classList.add("ativo");
      mudar(id, status)
        .then(function () {
          mostrarDesfazer(botao.dataset.nome + " → " + NOMES[status], { id: id, status: anterior });
        })
        .catch(function () { alert("Não consegui salvar. Confira a conexão e tente de novo."); })
        .then(function () { ocupado = false; return atualizar(); });
      return;
    }
    var tudo = evento.target.closest(".tudo-pronto-botao");
    if (tudo) {
      tudo.disabled = true;
      ocupado = true;
      enviar(api + "/comandas/" + tudo.dataset.comanda + "/pronto")
        .catch(function () { alert("Não consegui salvar. Confira a conexão e tente de novo."); })
        .then(function () { ocupado = false; return atualizar(); });
    }
  });

  botaoDesfazer.addEventListener("click", function () {
    if (!ultimaMudanca) return;
    var mudanca = ultimaMudanca;
    ultimaMudanca = null;
    aviso.hidden = true;
    mudar(mudanca.id, mudanca.status).then(atualizar, atualizar);
  });

  atualizar();
  setInterval(atualizar, INTERVALO);
})();

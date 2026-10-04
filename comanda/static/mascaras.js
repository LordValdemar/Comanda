// Formata os campos enquanto a pessoa digita: telefone, CPF/CNPJ, CEP e dinheiro.
// Marque o campo com data-mascara="telefone|documento|cep|dinheiro". O servidor confere de novo
// tudo o que chega (a máscara é só para facilitar a digitação).
"use strict";

(function () {
  function digitos(texto) { return (texto || "").replace(/\D/g, ""); }

  // Encaixa os números no modelo ("000.000.000-00"), até onde já foi digitado.
  function encaixar(numeros, modelo) {
    let saida = "";
    let i = 0;
    for (const letra of modelo) {
      if (i >= numeros.length) break;
      if (letra === "0") { saida += numeros[i]; i += 1; } else { saida += letra; }
    }
    return saida;
  }

  const MASCARAS = {
    telefone: function (v) {
      const d = digitos(v).slice(0, 11);
      return encaixar(d, d.length > 10 ? "(00) 00000-0000" : "(00) 0000-0000");
    },
    documento: function (v) {
      const d = digitos(v).slice(0, 14);
      return encaixar(d, d.length > 11 ? "00.000.000/0000-00" : "000.000.000-00");
    },
    cep: function (v) { return encaixar(digitos(v).slice(0, 8), "00000-000"); },
    // Como no app do banco: os números entram pelos centavos (2, 20, 200, 2000 → 0,02 · 0,20 · 2,00 · 20,00).
    dinheiro: function (v) {
      const d = digitos(v).replace(/^0+/, "").slice(0, 11);
      if (!d) return "";
      const completo = d.padStart(3, "0");
      const inteiro = completo.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      return inteiro + "," + completo.slice(-2);
    },
  };

  function aplicar(campo) {
    const mascara = MASCARAS[campo.dataset.mascara];
    if (!mascara) return;
    const formatado = mascara(campo.value);
    if (formatado !== campo.value) {
      campo.value = formatado;
      try { campo.setSelectionRange(formatado.length, formatado.length); } catch (erro) { /* campo sem cursor */ }
    }
  }

  document.addEventListener("input", function (evento) {
    if (evento.target.matches && evento.target.matches("input[data-mascara]")) aplicar(evento.target);
  });

  // Campo de dinheiro que veio preenchido (ex.: o que falta pagar): a primeira tecla substitui o valor
  // em vez de somar a ele, mesmo digitando rápido (81,40 + "50" vira 0,50, e não 8.140,50).
  document.querySelectorAll('input[data-mascara="dinheiro"]').forEach(function (campo) {
    if (campo.value) campo.dataset.preenchido = "1";
  });
  document.addEventListener("beforeinput", function (evento) {
    const campo = evento.target;
    if (!campo.matches || !campo.matches('input[data-mascara="dinheiro"]') || campo.dataset.preenchido !== "1") return;
    delete campo.dataset.preenchido;
    if ((evento.inputType || "").indexOf("insert") === 0) campo.value = "";
  });
  document.addEventListener("focusin", function (evento) {
    const campo = evento.target;
    if (campo.matches && campo.matches('input[data-mascara="dinheiro"]') && campo.value) {
      setTimeout(function () { try { campo.select(); } catch (erro) { /* sem seleção */ } }, 0);
    }
  });

  // Valores que já vêm preenchidos (telefone, CPF/CNPJ e CEP) ficam no formato logo ao abrir a página.
  document.querySelectorAll("input[data-mascara]").forEach(function (campo) {
    if (campo.value && campo.dataset.mascara !== "dinheiro") aplicar(campo);
  });
})();

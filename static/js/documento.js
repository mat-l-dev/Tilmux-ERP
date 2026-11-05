/* Documentos con líneas: alta de fila, cálculo y vista previa del asiento. */
(function () {
  const tabla = document.querySelector("[data-lineas]");
  if (!tabla) return;

  const tasa = 0.18;
  const fmt = (n) =>
    n.toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const num = (valor) => {
    const limpio = String(valor).replace(/\s/g, "").replace(",", ".");
    const n = Number.parseFloat(limpio);
    return Number.isFinite(n) ? n : 0;
  };

  const conIgv = () => {
    const control = document.querySelector("#id_con_igv");
    return control ? control.checked : true;
  };

  function calcular(cantidad, precio) {
    const bruto = Math.round(cantidad * precio * 100);
    if (conIgv()) {
      const base = Math.round(bruto / (1 + tasa));
      return { base: base / 100, igv: (bruto - base) / 100, total: bruto / 100 };
    }
    const base = bruto;
    const igv = Math.round(base * tasa);
    return { base: base / 100, igv: igv / 100, total: (base + igv) / 100 };
  }

  function pintar(fila) {
    const cantidad = num(fila.querySelector(".js-cantidad").value);
    const precio = num(fila.querySelector(".js-precio").value);
    const r = calcular(cantidad, precio);
    fila.querySelector(".js-base").textContent = fmt(r.base);
    fila.querySelector(".js-igv").textContent = fmt(r.igv);
    fila.querySelector(".js-total").textContent = fmt(r.total);
    fila.dataset.base = r.base;
    fila.dataset.igv = r.igv;
    fila.dataset.total = r.total;
  }

  function totales() {
    let base = 0, igv = 0, total = 0;
    tabla.querySelectorAll("tbody tr").forEach((fila) => {
      base += Number(fila.dataset.base || 0);
      igv += Number(fila.dataset.igv || 0);
      total += Number(fila.dataset.total || 0);
    });
    document.querySelectorAll("[data-total-base]").forEach((e) => (e.textContent = fmt(base)));
    document.querySelectorAll("[data-total-igv]").forEach((e) => (e.textContent = fmt(igv)));
    document.querySelectorAll("[data-total-total]").forEach((e) => (e.textContent = fmt(total)));
    document.querySelectorAll("[data-total-cobrar]").forEach((e) => (e.textContent = fmt(total)));
  }

  function recalcularTodo() {
    tabla.querySelectorAll("tbody tr").forEach(pintar);
    totales();
  }

  tabla.addEventListener("input", (event) => {
    if (event.target.matches(".js-cantidad, .js-precio")) {
      const fila = event.target.closest("tr");
      pintar(fila);
      totales();
    }
  });

  const igvControl = document.querySelector("#id_con_igv");
  if (igvControl) igvControl.addEventListener("change", recalcularTodo);

  const agregar = document.querySelector("[data-agregar-linea]");
  if (agregar) {
    agregar.addEventListener("click", () => {
      const cuerpo = tabla.querySelector("tbody");
      const ultima = cuerpo.querySelector("tr:last-child");
      const nueva = ultima.cloneNode(true);
      nueva.querySelectorAll("input").forEach((i) => (i.value = ""));
      nueva.querySelectorAll("select").forEach((s) => (s.value = ""));
      nueva.dataset.base = 0;
      nueva.dataset.igv = 0;
      nueva.dataset.total = 0;
      nueva.querySelector(".js-base").textContent = "0,00";
      nueva.querySelector(".js-igv").textContent = "0,00";
      nueva.querySelector(".js-total").textContent = "0,00";
      cuerpo.appendChild(nueva);
      totales();
    });
  }

  tabla.addEventListener("click", (event) => {
    const boton = event.target.closest("[data-quitar-linea]");
    if (!boton) return;
    const cuerpo = tabla.querySelector("tbody");
    if (cuerpo.querySelectorAll("tr").length === 1) return;
    boton.closest("tr").remove();
    totales();
  });

  recalcularTodo();
})();

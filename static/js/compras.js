/* Cálculo de compras: líneas sin IGV más costos de internamiento. */
(function () {
  const tabla = document.querySelector("[data-lineas-compra]");
  if (!tabla) return;

  const tasa = 0.18;
  const fmt = (n) =>
    n.toLocaleString("es-PE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num = (v) => {
    const n = Number.parseFloat(String(v).replace(",", "."));
    return Number.isFinite(n) ? n : 0;
  };
  const conIgv = () => {
    const control = document.querySelector("#id_con_igv");
    return control ? control.checked : false;
  };

  function totales() {
    let base = 0, igv = 0;
    tabla.querySelectorAll("tbody tr").forEach((tr) => {
      const cantidad = num(tr.querySelector(".js-cantidad")?.value);
      const precio = num(tr.querySelector(".js-precio")?.value);
      const bruto = Math.round(cantidad * precio * 100);
      let b, i;
      if (conIgv()) {
        const baseCalc = Math.round(bruto / (1 + tasa));
        b = baseCalc / 100;
        i = (bruto - baseCalc) / 100;
      } else {
        b = bruto / 100;
        i = Math.round(bruto * tasa) / 100;
      }
      if (tr.querySelector(".js-base")) tr.querySelector(".js-base").textContent = fmt(b);
      if (tr.querySelector(".js-igv")) tr.querySelector(".js-igv").textContent = fmt(i);
      base += b;
      igv += i;
    });
    document.querySelectorAll("[data-costo-base]").forEach((input) => {
      base += num(input.value);
    });
    document.querySelectorAll("[data-costo-igv]").forEach((input) => {
      igv += num(input.value);
    });
    const total = base + igv;
    document.querySelectorAll("[data-total-base]").forEach((e) => (e.textContent = fmt(base)));
    document.querySelectorAll("[data-total-igv]").forEach((e) => (e.textContent = fmt(igv)));
    document.querySelectorAll("[data-total-total]").forEach((e) => (e.textContent = fmt(total)));
    const tipo = document.querySelector("[data-tipo-compra]");
    const conCredito = tipo && tipo.value === "FACTURA";
    document.querySelectorAll("[data-asiento-inventario]").forEach((e) => (e.textContent = fmt(conCredito ? base : total)));
    document.querySelectorAll("[data-asiento-igv]").forEach((e) => (e.textContent = fmt(conCredito ? igv : 0)));
  }

  document.addEventListener("input", (event) => {
    if (event.target.matches(".js-cantidad, .js-precio, [data-costo-base], [data-costo-igv]")) {
      totales();
    }
  });

  const igvControl = document.querySelector("#id_con_igv");
  if (igvControl) igvControl.addEventListener("change", totales);
  const tipoCompra = document.querySelector("[data-tipo-compra]");
  if (tipoCompra) tipoCompra.addEventListener("change", totales);

  totales();
})();

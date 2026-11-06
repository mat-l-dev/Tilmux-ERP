# Auditoría contable y de datos — TILMUX S.A.C.

**Fase 0 — solo lectura.** Este documento es el entregable de auditoría previo a cualquier corrección. No se modificó ningún dato, asiento, compra, venta, capa de inventario ni movimiento de tesorería.

**Fase 1 — correcciones aplicadas el 2026-11-05** en la rama `fix/auditoria-p0`. Cada cambio dejó historial en `HistorialDocumento`; no se borró ningún asiento, línea, compra, venta, capa ni movimiento. La sección 1 resume el estado verificado después de la corrección y conserva el diagnóstico original de la Fase 0.

| Dato | Valor |
|---|---|
| Empresa | TILMUX S.A.C. |
| RUC | 20615841961 |
| Régimen | RER |
| Fecha de auditoría | 2026-11-05 |
| Corte de datos | 2026-11-30 |
| Base de datos | PostgreSQL (Supabase) |
| Periodos contables | 2026-09, 2026-10 y 2026-11 en estado `ABIERTO` |
| Último commit auditado | `b1b5086 Corregir lotes por fecha y mantener SKU 1 como producto principal` |

---

## 1. Resumen ejecutivo

### Estado actual verificado (después de la Fase 1)

| Concepto | Valor verificado |
|---|---:|
| `4212` Emitidas | **S/ 0.00** |
| `1061` Depósitos de ahorro | **D S/ 901.60** |
| `40111` IGV | **C S/ 22.05** |
| `40171` Renta RER | **C S/ 17.95** |
| Balanza (confirmados) | **D = H = S/ 10,665.51** |
| Resultado neto | **S/ 197.91** |
| Total activo | **S/ 2,576.91** |
| Total pasivo | **S/ 579.00** |
| Patrimonio + resultado | **S/ 1,997.91** |
| Descuadre | **S/ 0.00** |
| Casilla 120 (set/oct/nov) | **78.00 / 53.00 / 0.00** |
| Registro de compras set–nov | **S/ 1,635.44** |
| IGV de octubre pendiente | **S/ 105.10** (sin pagar) |

La balanza bajó de S/ 10,683.51 a **S/ 10,665.51** porque el asiento 37 quedó anulado: se retiraron S/ 18.00 del debe y S/ 18.00 del haber, no S/ 36.00. Sigue cuadrando.

Correcciones aplicadas:

1. **Asiento 37 anulado** (pago FV20 duplicado del 31/10; el pago real es el asiento 33) con motivo e historial. Líneas conservadas.
2. **Asiento 38 reclasificado**: la provisión de S/ 10 del 03/10 se acreditaba a `1061`; ahora se acredita a `4212`. El pago real de esos S/ 10 es el asiento 32, que se conserva.
3. **Asiento 33 corregido**: fecha y periodo pasan de 2026-11-04 / noviembre a **2026-10-31 / octubre**, que es la fecha real del débito bancario.
4. **Gasto 9 corregido**: `FV20-14904766` → **`FV20-01490476`**, según el XML del proveedor.
5. **Provisiones identificadas**: gastos 3 (→ 9), 12 y 13 (→ 11) marcados con `provision=True`, `gasto_origen` y `estado=PROVISION`; excluidos del registro de compras y del PDT 621.
6. **Periodo económico**: gasto 9 con `fecha_devengado=2026-09-30` y gasto 11 con `2026-10-31`. La fecha del documento no cambia; el 621 usa la fecha devengada.
7. **Glosas** de los asientos 36, 39 y 41 actualizadas al número real de FV20 y a la naturaleza de provisión.
8. **Código**: pago de IGV con asiento y tesorería, correlativo de series atómico, alta de compras/ventas atómica, glosas vinculadas al corregir una compra y clasificación correcta de saldos deudores del elemento 4 en los EEFF.

Pendientes inmediatos:

- **Débito BCP del 04/11 por S/ 10.00** (`ENVIO.ESTADO.CTA`) visible en el banco pero ausente de `MovimientoTesoreria`. Si se registra como gasto, el resultado baja de S/ 197.91 a **S/ 187.91** y `1061` queda en **D S/ 891.60**. Requiere confirmación del usuario.
- **IGV de octubre (S/ 105.10)**: el flujo de pago ya existe, pero no se registró ningún pago.
- **SIRE**: falta el archivo RVIE/RCE real para probar el importador.

### Diagnóstico original (Fase 0, antes de corregir)

La contabilidad **cuadraba formalmente**: el total del debe era igual al total del haber por **S/ 10,683.51**. Sin embargo, esa igualdad no garantizaba que los saldos fueran correctos. La auditoría encontró un **descuadre económico de S/ 28.00** escondido en la cuenta `4212`, que el estado de situación financiera presentaba como si fuera un activo ("crédito fiscal por recuperar").

### Hallazgos principales de la Fase 0

| # | Hallazgo | Impacto | Prioridad |
|---|---|---|---|
| 1 | El asiento **37** duplica el pago real de FV20 del 31/10 (asiento **33**), y el asiento **38** registra una provisión de S/ 10 contra banco (`1061`) en vez de contra `4212`. El asiento **32** es el pago real del 03/10 y es correcto. | `4212` quedaba con saldo deudor de **S/ 28.00**; `1061` quedaba **S/ 28.00** por debajo de BBVA + BCP. | P0 |
| 2 | Los gastos provisionales **3, 12 y 13** (`OTRO`, "incluido en FV20/FV15") conviven con las facturas finales **9 y 11** en el registro de compras. | El registro de compras suma **S/ 1,681.44** en setiembre–noviembre, pero los documentos finales suman **S/ 1,635.44**: **S/ 46.00** de duplicidad. | P0 |
| 3 | Las facturas **FV20-01490476** y **FV15-01525308** están asignadas a octubre y noviembre, aunque su gasto corresponde a setiembre y octubre. El número de FV20 estaba digitado como `FV20-14904766`. | El casillero 120 del PDT 621 queda repartido en los meses equivocados (el total no cambia). | P0 |
| 4 | No existe flujo para pagar el IGV. La regla `IGV_MENSUAL` existe, pero no hay servicio, validación, UI ni prueba. | El IGV de octubre (**S/ 105.10**) no puede registrarse como pagado; hoy sigue pendiente. | P0 |
| 5 | `_numero_siguiente` lee `Serie.ultimo_numero` pero nunca lo actualiza. | Riesgo de números duplicados o concurrentes en ventas futuras. Las facturas E001 ya aceptadas por SUNAT no se tocan. | P0 |
| 6 | El modelo `Gasto` no distingue provisión de pago, ni vincula provisión con factura final, ni guarda el asiento/movimiento de pago. | Duplicidad y pérdida de trazabilidad; permitió el asiento 37 y la mala clasificación del 38. | P0 |
| 7 | `reportes/eeff.py` clasificaba cualquier saldo deudor de una cuenta del elemento 4 como activo. | El saldo deudor de `4212` se presentaba como "crédito fiscal" y ocultaba el descuadre. | P1 |
| 8 | `compras.views.corregir` actualiza la compra pero no las glosas del asiento ni del movimiento de tesorería. | Asientos 26/28 y movimientos 27/29 dicen "Compra" y "Pago compra Pendiente". | P1 |
| 9 | Las vistas de alta/edición de compras y ventas no son atómicas. | Un error a mitad de grabación puede dejar una cabecera sin líneas. | P1 |
| 10 | La nota de crédito reingresa stock al costo de la venta, no al costo de las capas originales. | Distorsión de costo si se emite una NC (no hay NC en los datos actuales). | P1 |
| 11 | El importador de Excel tiene mapeos fijos (`"Standard"` → `TIL-000002`, filas 3 y 9 de SUNAT). | En una instalación nueva puede recrear datos antiguos o asignar el producto equivocado. | P2 |
| 12 | El lector SIRE es heurístico y no se probó con un archivo real de SUNAT. | No se puede afirmar que el RVIE/RCE real se importe correctamente. | P2 |

### Cifras de control

| Concepto | Importe |
|---|---:|
| Ventas netas | S/ 1,196.62 |
| IGV de ventas | S/ 215.38 |
| Compras netas (4 facturas) | S/ 1,074.07 |
| IGV de compras | S/ 193.33 |
| Total compras | S/ 1,267.40 |
| Costo de ventas | S/ 612.72 |
| Gastos operativos | S/ 368.04 |
| Renta RER devengada | S/ 17.95 |
| **Resultado neto** | **S/ 197.91** |
| Total activo | S/ 2,576.91 |
| Total pasivo | S/ 579.00 |
| Patrimonio | S/ 1,997.91 |
| Descuadre contable | S/ 0.00 |

---

## 2. Metodología y limitaciones

### Método

1. Lectura completa del código de `catalogo`, `compras`, `ventas`, `inventario`, `contabilidad`, `tesoreria`, `reportes`, `core` y `tests`.
2. Consultas de solo lectura contra la base real: productos, capas, movimientos, consumos, compras, ventas, gastos, asientos, balanza, periodos, tesorería, PDT 621 y estados financieros.
3. Reconciliación contra el libro de tesorería y los débitos bancarios registrados.
4. Lectura del Excel `Archivos/TILMUX – Contabilidad 2026.xlsx` como fuente secundaria.
5. Verificación de invariantes: capas consumidas, movimientos sin origen, consumos cruzados, duplicados de comprobantes y asientos huérfanos.

### Limitaciones

- La Fase 0 no disponía de XML ni PDF. En la Fase 1 se verificaron los seis XML adjuntos del proveedor; los importes y fechas coinciden con el ERP salvo el número de FV20.
- No se consultó SUNAT ni se envió ningún comprobante.
- El archivo RVIE/RCE real para probar SIRE aún no fue entregado; el usuario indicó que lo adjuntará.
- La suite completa se ejecutó contra Supabase con `--keepdb`: **73 pruebas OK** (1008 s). La suite específica de la Fase 1 (`tests.test_auditoria_p0`) pasó **11 de 11** con `--keepdb`; la CI la ejecuta contra PostgreSQL local (`manage.py test tests -v 2`).
- `ruff check .` falla con **106 E501** en archivos de migración generados. El código de aplicación sí pasa `ruff check . --exclude migrations`. La CI no ejecuta ruff.

---

## 3. Decisiones del usuario

Estas respuestas cierran las ambigüedades que no se podían inferir de los documentos:

| Tema | Decisión |
|---|---|
| Periodo de FV20-01490476 / FV15-01525308 | **FV20 = setiembre; FV15 = octubre.** Coincide con los débitos bancarios del 30/09, 03/10 y 31/10. |
| Facturas E001-1 y E001-2 | **Ambas ya fueron aceptadas por SUNAT.** No se modifica serie, número, fecha ni importe. Cualquier corrección debe ser por nota de crédito. |
| TIL-000001 (Starlink Mini Kit) | **Mantener activo.** El stock 0 es temporal; sigue siendo el SKU principal. |
| IGV de octubre (S/ 105.10) | **Aún no se paga.** Coincide con los libros: no hay pago registrado. Queda como obligación pendiente. |
| TIL-000002 (Monitor Gamer) | **Mantener inactivo.** Conserva el catálogo histórico sin afectar stock ni contabilidad. |
| Archivo SIRE | **El usuario adjuntará un RVIE/RCE real** para probar el importador. |

---

## 4. Inventario y costo de ventas

### Productos

| SKU | Producto | Activo | Stock | Valor | Capas | Compras | Ventas |
|---|---|---:|---:|---:|---:|---:|---:|
| TIL-000001 | Starlink Mini Kit | Sí | 0 | S/ 0.00 | 2 (consumidas) | 2 | 2 |
| TIL-000002 | Monitor Gamer Samsung 25" 240Hz | No | 0 | S/ 0.00 | 0 | 0 | 0 |
| TIL-000003 | Starlink Mini X | Sí | 2 | S/ 461.35 | 2 | 2 | 0 |

### Capas PEPS

| Capa | Fecha | SKU | Inicial | Restante | Costo unitario | Origen |
|---:|---|---|---:|---:|---:|---|
| 16 | 2026-09-18 | TIL-000001 | 1 | 0 | S/ 274.58 | COMPRA:15 |
| 17 | 2026-09-18 | TIL-000001 | 1 | 0 | S/ 338.14 | COMPRA:16 |
| 18 | 2026-11-02 | TIL-000003 | 1 | 1 | S/ 239.15 | COMPRA:17 |
| 19 | 2026-11-02 | TIL-000003 | 1 | 1 | S/ 222.20 | COMPRA:18 |

### Verificaciones

- Las capas 16 y 17 fueron consumidas íntegramente por las ventas 10 y 11, cada una con su costo correcto.
- Las capas 18 y 19 permanecen íntegras en TIL-000003; el valor de inventario es **S/ 461.35**.
- No hay capas huérfanas, consumos cruzados entre productos ni movimientos de salida cuya suma de consumos no coincida.
- No hay notas de crédito ni notas de débito registradas.
- **Riesgo de código:** `emitir_nota_credito` reingresa stock con `linea.costo_unitario` (costo de la venta) en lugar de restaurar las capas originales consumidas (`ventas/servicios.py:210-220`). No afecta los datos actuales porque no hay NC, pero debe corregirse antes de emitir la primera.

---

## 5. Compras

| Compra | Fecha | Documento | Base | IGV | Total | Estado | Pago |
|---:|---|---|---:|---:|---:|---|---|
| 15 | 2026-09-18 | F002-00005995 | 274.58 | 49.42 | 324.00 | Confirmada | Pagada 18/09, BBVA |
| 16 | 2026-09-18 | F002-00005998 | 338.14 | 60.86 | 399.00 | Confirmada | Pagada 18/09, BBVA |
| 17 | 2026-11-02 | F002-00007373 | 239.15 | 43.05 | 282.20 | Confirmada | Pagada 02/11, BBVA |
| 18 | 2026-11-02 | F002-00007362 | 222.20 | 40.00 | 262.20 | Confirmada | Pagada 02/11, BBVA |

- Todas están confirmadas, pagadas y con stock ingresado.
- Los importes coinciden con los movimientos de tesorería y con los asientos de compra y pago.
- **Glosas incompletas (Fase 0):** los asientos 26 y 28 decían solo "Compra", y los movimientos 27 y 29 "Pago compra Pendiente". Se corrigió en la Fase 1: `compras.views.corregir` ahora refresca las glosas de asientos y movimientos vinculados. No hubo impacto de saldo, solo de trazabilidad.
- **Atomicidad (Fase 0):** las vistas de alta/edición creaban la compra y luego las líneas sin `transaction.atomic` (`compras/views.py:267-307`). Corregido en la Fase 1: `nueva`, `corregir` y `ventas.views.nueva` están envueltas en transacción.
- **Revaluación:** no hay compras en moneda extranjera en la base actual; no hay impacto. La prueba existente cubre un caso de revaluación (`tests/test_invariantes.py:552`), pero conviene añadir pruebas de idempotencia y de compras ya pagadas.

---

## 6. Ventas y comprobantes electrónicos

| Venta | Fecha | Documento | Cliente | Base | IGV | Total | Costo de venta |
|---:|---|---|---|---:|---:|---:|---:|
| 10 | 2026-10-29 | E001-1 | MAQUINARIAS Y DIVERSOS S.A.C. | 598.31 | 107.69 | 706.00 | 274.58 |
| 11 | 2026-10-29 | E001-2 | MAQUINARIAS Y DIVERSOS S.A.C. | 598.31 | 107.69 | 706.00 | 338.14 |

- Ambas ventas están confirmadas, cobradas por Mercado Pago y con costo PEPS correcto.
- **E001-1 y E001-2 ya fueron aceptadas por SUNAT.** No se deben modificar. La numeración `E001-1` / `E001-2` no es la correlativa estándar, pero al estar aceptadas es inmutable; se documenta y se deja intacta.
- La serie `E001` tiene `ultimo_numero = 2`, consistente con las dos ventas.
- **Riesgo de código (Fase 0):** `_numero_siguiente` (`ventas/views.py:30-36`) calculaba el siguiente número como `ultimo_numero + 1`, pero no guardaba el incremento en `Serie.ultimo_numero`. Corregido en la Fase 1: se actualiza de forma atómica al confirmar la venta, con bloqueo de la empresa. Las ventas en borrador no consumen número.
- No hay notas de crédito ni de débito.

---

## 7. Gastos, provisiones y registro de compras

### Los 11 gastos registrados

| Gasto | Fecha | Documento | Total | Crédito | Deducible | Tipo | Periodo económico | Tratamiento |
|---:|---|---|---:|---|---|---|---|---|
| 1 | 2026-09-11 | FB29-29158446 | 45.00 | Sí | Sí | Factura | Setiembre | Gasto real; casilla 120 |
| 2 | 2026-09-30 | FB29-29458395 | 15.00 | Sí | Sí | Factura | Setiembre | Gasto real; casilla 120 |
| 3 | 2026-09-30 | OTRO | 18.00 | Sí | Sí | Provisión FV20 | Setiembre | **Provisión**; el documento final es el gasto 9 |
| 5 | 2026-10-03 | OTRO | 39.00 | Sí | Sí | Token físico | Octubre | Gasto real pagado en efectivo; sin comprobante; no va al 621 |
| 6 | 2026-10-17 | FN01-52311518 | 10.00 | Sí | Sí | Factura | Octubre | Gasto real; casilla 120 |
| 7 | 2026-10-31 | B001-00393302 | 198.04 | No | No | Boleta | Octubre | Gasto real (6311); sin crédito ni deducción; no va al 621 |
| 8 | 2026-10-30 | FB29-29938941 | 15.00 | Sí | Sí | Factura | Octubre | Gasto real; casilla 120 |
| 9 | 2026-10-05 | FV20-01490476 | 18.00 | Sí | Sí | Factura | **Setiembre** (decisión) | Documento final de la provisión 3; casilla 120 de setiembre |
| 11 | 2026-11-04 | FV15-01525308 | 28.00 | Sí | Sí | Factura | **Octubre** (decisión) | Documento final de las provisiones 12 y 13; casilla 120 de octubre |
| 12 | 2026-10-03 | OTRO | 10.00 | No | Sí | Provisión FV15 | Octubre | **Provisión**; el documento final es el gasto 11 |
| 13 | 2026-10-31 | OTRO | 18.00 | No | Sí | Provisión FV15 | Octubre | **Provisión**; el documento final es el gasto 11 |

### Conciliación del registro de compras

Antes de la corrección, el registro de compras incluía **todas** las filas de `Gasto`, incluidas las provisiones `OTRO`, y sumaba el campo `total` aunque la fila no otorgara crédito (`reportes/views.py:267-301`). Eso producía esta diferencia:

| Concepto | Importe |
|---|---:|
| Total anterior del registro, setiembre–noviembre | S/ 1,681.44 |
| Menos provisiones 3, 12 y 13 | (S/ 46.00) |
| **Total de documentos finales** | **S/ 1,635.44** |
| Compras (4 facturas) | S/ 1,267.40 |
| Gastos finales (8 documentos) | S/ 368.04 |
| Suma | S/ 1,635.44 |

Los **S/ 368.04** de gastos finales coinciden exactamente con los gastos operativos del estado de resultados (`6391` neto S/ 170.00 + `6311` S/ 198.04). El resultado contable ya era correcto; el registro de compras mostraba **S/ 46.00 de más** por las provisiones. Después de la corrección, el registro muestra **S/ 1,635.44**.

### Tratamiento contable (antes de la corrección)

Los asientos de provisión y aplicación existían y, en neto, el gasto era correcto. El problema era la convivencia de dos formas de registrar el mismo gasto y una línea mal clasificada:

- **FV20:** el pago real se contabilizó en el asiento **12** (D `6391` 18 / H `1061` 18, importe del banco). Luego se creó la provisión **36** (D `6391` 18 / C `4212` 18) y la aplicación **41** (D `4212` 18 / H `6391` 18). El neto es un solo gasto de S/ 18. El asiento **37** volvió a registrar el mismo pago del 31/10 y quedó anulado.
- **FV15:** el asiento **38** registró la provisión de S/ 10 del 03/10 con crédito a `1061` (debía ser `4212`); el asiento **32** es el pago real de esos S/ 10. La provisión **40** registró los S/ 18 de mantenimiento (D `6391` 18 / C `4212` 18); la factura final **31** registró S/ 28 (D `6391` 28 / C `4212` 28); las aplicaciones **39** y **42** revirtieron S/ 10 y S/ 18; el pago real de S/ 18 quedó en el asiento **33**, con fecha corregida al 31/10. El neto es un solo gasto de S/ 28.

El problema no era el neto, sino que **no había un vínculo único** entre provisión, factura final, pago y movimiento bancario. Eso permitió que se registrara el asiento 37 duplicado, que el 38 se clasificara contra banco y que el registro de compras sumara las provisiones.

### Modelo implementado (Fase 1)

1. Campos añadidos a `Gasto`:
   - `provision` (booleano): marca la fila como provisión.
   - `gasto_origen` (FK a `Gasto`, opcional): la factura final a la que pertenece la provisión.
   - `estado` (`PROVISION`, `REGISTRADO`, `PAGADO`, `ANULADO`).
   - `fecha_devengado`: fecha económica para el PDT 621.
2. Las provisiones se excluyen de los totales del registro de compras y de las casillas del 621 por `provision=True`, no por el tipo de documento.
3. La factura final se registra como gasto normal y la provisión queda vinculada a ella. Las aplicaciones se registran con asientos de reverso; el neto del gasto no cambia.
4. El periodo económico se asigna con `fecha_devengado`. La fecha del documento se conserva y el PDT 621 usa la fecha devengada. Los estados financieros siguen la fecha de los asientos contables.

---

## 8. Tesorería y conciliación bancaria

### Saldos (antes de la corrección)

| Cuenta | Libro de tesorería | Contabilidad | Diferencia |
|---|---:|---:|---:|
| BBVA | S/ 457.60 | (parte de `1061`) | — |
| BCP | S/ 444.00 | (parte de `1061`) | — |
| **Subtotal bancos** | **S/ 901.60** | **S/ 873.60** (`1061`) | **−S/ 28.00** |
| Mercado Pago | S/ 1,213.96 | S/ 1,213.96 (`1031`) | S/ 0.00 |
| Caja | S/ 0.00 | S/ 0.00 (`101`) | S/ 0.00 |
| **Total** | **S/ 2,115.56** | **S/ 2,087.56** | **−S/ 28.00** |

Después de la corrección, `1061` quedó en **D S/ 901.60** y coincide con BBVA + BCP. El total de tesorería no cambió: **S/ 2,115.56** de libro contra **S/ 2,115.56** de contabilidad.

### Causa de la diferencia

La diferencia de S/ 28.00 tenía dos causas: el asiento **37** duplicaba un pago real y el asiento **38** clasificaba una provisión contra banco.

| Asiento | Fecha | Debe | Haber | Origen | Glosa | Diagnóstico |
|---:|---|---:|---:|---|---|---|
| 37 | 2026-10-31 | `4212` 18.00 | `1061` 18.00 | GASTO:9 | Pago FV20 – BCP | **Duplicado**: el pago real del 31/10 ya está en el asiento 33 |
| 38 | 2026-10-03 | `6391` 10.00 | `1061` 10.00 | GASTO:12 | Envío estado de cuenta – provisión FV15 | **Mal clasificado**: es una provisión; el crédito debe ir a `4212`, no a `1061` |

El asiento **32** (03/10, D `4212` 10 / H `1061` 10) **no es un duplicado**: es el pago real de los S/ 10 y se conserva.

Evidencia en tesorería:

- 2026-10-03: BCP egreso S/ 10.00, origen `GASTO:11` ("Envío estado de cuenta BCP – pago FV15").
- 2026-10-31: BCP egreso S/ 18.00, origen `GASTO:11` ("Mantenimiento de cuenta BCP – pago FV15").
- 2026-09-30: BCP egreso S/ 18.00, origen `IMPORTACION:10` ("sin comprobante – BCP"), que es el pago real de FV20.
- No existe un segundo débito de S/ 18.00 el 31/10 por FV20. El débito de S/ 10.00 del 04/11 que muestra el banco (`ENVIO.ESTADO.CTA`) **no está registrado** en `MovimientoTesoreria`; queda pendiente de decisión del usuario.

### Asientos legítimos que se conservaron

| Asiento | Fecha | Debe | Haber | Origen | Glosa | Veredicto |
|---:|---|---:|---:|---|---|---|
| 12 | 2026-09-30 | `6391` 18.00 | `1061` 18.00 | IMPORTACION:10 | sin comprobante – BCP | Pago real FV20; conservado |
| 31 | 2026-11-04 | `6391` 28.00 | `4212` 28.00 | GASTO:11 | FV15 – provisión | Factura final; conservada |
| 32 | 2026-10-03 | `4212` 10.00 | `1061` 10.00 | GASTO:11 | Pago FV15 – portes 10 | Pago real; conservado |
| 33 | **2026-10-31** | `4212` 18.00 | `1061` 18.00 | GASTO:11 | Pago FV15 – mantenimiento 18 | Pago real; fecha corregida |
| 36 | 2026-10-05 | `6391` 18.00 | `4212` 18.00 | GASTO:9 | FV20 – provisión | Conservado; glosa corregida |
| 38 | 2026-10-03 | `6391` 10.00 | **`4212` 10.00** | GASTO:12 | Envío estado de cuenta – provisión FV15 | Provisión; reclasificada |
| 39 | 2026-11-04 | `4212` 10.00 | `6391` 10.00 | GASTO:11 | Aplicación provisión 03/10 | Reverso de provisión; conservado |
| 40 | 2026-10-31 | `6391` 18.00 | `4212` 18.00 | GASTO:13 | Provisión mantenimiento octubre FV15 | Provisión; conservada |
| 41 | 2026-10-05 | `4212` 18.00 | `6391` 18.00 | GASTO:9 | Aplicación pago 30/09 | Reverso de provisión; conservado |
| 42 | 2026-11-04 | `4212` 18.00 | `6391` 18.00 | GASTO:11 | Aplicación pago 31/10 | Reverso de provisión; conservado |

### Impacto de la corrección (anular 37 y reclasificar 38)

| Concepto | Antes | Después | Variación |
|---|---:|---:|---:|
| `4212` | D 28.00 | 0.00 | −28.00 |
| `1061` | D 873.60 | D 901.60 | +28.00 |
| Total activo | 2,576.91 | 2,576.91 | 0.00 |
| Total pasivo | 579.00 | 579.00 | 0.00 |
| Resultado neto | 197.91 | 197.91 | 0.00 |
| Descuadre | 0.00 | 0.00 | 0.00 |

La anulación del 37 y la reclasificación del 38 **no afectan el resultado**: ambos son movimientos de balance (D `4212` / H `1061`). Solo corrigen la clasificación y la conciliación bancaria.

---

## 9. Contabilidad general y estados financieros

### Balanza de comprobación

| Concepto | Debe | Haber | Saldo |
|---|---:|---:|---:|
| Total general (confirmados) | 10,665.51 | 10,665.51 | 0.00 |

### Saldos clave al 30/11/2026 (después de la corrección)

| Cuenta | Nombre | Debe | Haber | Saldo | Interpretación |
|---|---|---:|---:|---:|---|
| `101` | Caja | 39.00 | 39.00 | 0.00 | Correcto |
| `1031` | Efectivo en tránsito | 1,412.00 | 198.04 | D 1,213.96 | Coincide con Mercado Pago |
| `1061` | Depósitos de ahorro | 2,339.00 | 1,437.40 | **D 901.60** | Coincide con BBVA + BCP |
| `20111` | Costo (inventario) | — | — | D 461.35 | Coincide con capas 18/19 |
| `40111` | IGV – Cuenta propia | 193.33 | 215.38 | C 22.05 | IGV octubre 105.10 menos crédito noviembre 83.05 |
| `40171` | Renta de tercera categoría | 0.00 | 17.95 | C 17.95 | Renta RER octubre pendiente |
| `4212` | Emitidas (por pagar) | 1,351.40 | 1,351.40 | **0.00** | Corregido |
| `5011` | Acciones | 0.00 | 1,800.00 | C 1,800.00 | Capital suscrito |
| `6391` | Gastos bancarios | — | — | D 170.00 | Neto de gastos y reversos |
| `6311` | Transporte | 198.04 | 0.00 | D 198.04 | Boleta Mercado Libre |
| `69121` | Costo de venta | 612.72 | 0.00 | D 612.72 | Costo PEPS de ventas 10/11 |
| `881` | Impuesto a las ganancias – corriente | 17.95 | 0.00 | D 17.95 | Renta RER octubre |

### Estado de situación financiera al 30/11/2026 (después de la corrección)

| Rubro | Importe |
|---|---:|
| `1031` Efectivo en tránsito | 1,213.96 |
| `1061` Depósitos de ahorro | 901.60 |
| `20111` Inventario | 461.35 |
| **Total activo** | **2,576.91** |
| `40111` IGV por pagar | 22.05 |
| `40171` Renta por pagar | 17.95 |
| `4411` Préstamo de socio | 500.00 |
| `4419` Otras cuentas por pagar | 39.00 |
| **Total pasivo** | **579.00** |
| `5011` Capital | 1,800.00 |
| Resultado del ejercicio | 197.91 |
| **Total patrimonio** | **1,997.91** |
| **Total pasivo + patrimonio** | **2,576.91** |

El descuadre es **S/ 0.00** y ya no hay ningún saldo deudor de `4212` presentado como activo. Además, `reportes/eeff.py` se corrigió: un saldo deudor del elemento 4 en una cuenta que no empieza con `40` reduce el pasivo, mientras que un saldo deudor de tributos (`40...`) sigue mostrándose como crédito fiscal por recuperar.

### Estado de resultados

| Rubro | Importe |
|---|---:|
| Ingresos por ventas | 1,196.62 |
| Costo de ventas | (612.72) |
| Gastos operativos | (368.04) |
| Resultado de operación | 215.86 |
| Impuesto a la renta RER | (17.95) |
| **Resultado neto** | **197.91** |

### Periodos y cierre

- Los periodos 2026-09, 2026-10 y 2026-11 están **ABIERTOS**.
- No se ejecutó el cierre anual.
- **No cerrar** hasta que se corrijan los P0 y el usuario revise los tres meses.
- Cualquier prueba de cierre debe hacerse dentro de `transaction.atomic()` con `set_rollback(True)`, nunca contra la base real.

---

## 10. Tributación

### PDT 621 calculado

| Casilla | Setiembre | Octubre | Noviembre |
|---|---:|---:|---:|
| 100 Ventas netas | 0.00 | 1,196.62 | 0.00 |
| 101 IGV ventas | 0.00 | 215.38 | 0.00 |
| 107 Compras netas | 612.72 | 0.00 | 461.35 |
| 108 IGV compras | 110.28 | 0.00 | 83.05 |
| 120 Compras no gravadas | 78.00 | 53.00 | 0.00 |
| 140 Resultado IGV | −110.28 | 215.38 | −83.05 |
| 145 Saldo a favor anterior | 0.00 | 110.28 | 0.00 |
| 184 IGV a pagar / saldo a favor | −110.28 | **105.10** | −83.05 |
| 301 Base renta | 0.00 | 1,196.62 | 0.00 |
| 312 Renta RER | 0.00 | 17.95 | 0.00 |

### Reasignación de FV20 y FV15

La decisión del usuario es FV20 = setiembre y FV15 = octubre. El único casillero afectado es el **120** (compras no gravadas), porque ambas facturas tienen IGV 0:

| Casilla 120 | Setiembre | Octubre | Noviembre |
|---|---:|---:|---:|
| Antes (Fase 0) | 60.00 | 43.00 | 28.00 |
| Después (aplicado) | **78.00** | **53.00** | **0.00** |

La reasignación se implementó con `Gasto.fecha_devengado`: la fecha del documento se conserva y el PDT 621 usa la fecha devengada. El total sigue siendo **S/ 131.00**. No cambia el IGV (casillas 101/108/140/184) ni la renta RER (casilla 312), porque la renta RER es el 1.5 % de las ventas netas y no depende de los gastos.

### IGV de octubre

- El PDT de octubre arroja **S/ 105.10** por pagar: S/ 215.38 de IGV de ventas menos S/ 110.28 de saldo a favor de setiembre.
- El usuario confirmó que **aún no se paga**.
- Al 30/11, `40111` tiene saldo acreedor de **S/ 22.05**: los S/ 105.10 de octubre menos los S/ 83.05 de crédito de las compras de noviembre.
- Si en el futuro se paga, el asiento debe ser D `40111` / H `1061` (o la cuenta de tesorería que corresponda) por S/ 105.10. Después del pago, `40111` quedaría deudor por S/ 83.05 (saldo a favor), que es coherente con el PDT de noviembre.
- **No registrar el pago hasta que el usuario lo confirme con fecha y cuenta.**
- El flujo ya está implementado: `contabilidad/impuestos.pagar_igv`, la vista `reportes:pagar_igv` y el formulario en la pantalla del PDT 621 validan periodo abierto, importe pendiente y medio de pago, y generan asiento, movimiento de tesorería e historial. La prueba `tests.test_auditoria_p0.PagoIGV` cubre pago parcial y sobrepago.

### Renta RER

- Octubre: 1.5 % de S/ 1,196.62 = **S/ 17.95**.
- Asiento 25: D `881` 17.95 / C `40171` 17.95.
- Al 30/11, `40171` acreedor **S/ 17.95** y `881` deudor **S/ 17.95**; la renta está devengada pero no pagada.
- Setiembre y noviembre: S/ 0.00.
- No hay pagos de renta registrados.

### Otros temas tributarios

- **Detracciones:** no se identificaron operaciones sujetas en los datos actuales. Sigue en backlog.
- **Retenciones:** no hay retenciones registradas. Sigue en backlog.
- **Crédito fiscal 12 meses:** las compras de setiembre se usaron en octubre, dentro del plazo. No hay crédito vencido. La funcionalidad de control sigue en backlog.
- **Alerta RER S/ 525,000:** las ventas acumuladas son S/ 1,196.62, muy por debajo del límite. La alerta sigue en backlog.
- **Bancarización:** la mayoría de pagos son bancarios; el token de S/ 39 se pagó en efectivo. No hay operación que supere el umbral de bancarización. La funcionalidad de control sigue en backlog.
- **SIRE:** el lector `reportes/sire.py` es heurístico y no se probó con un archivo real. Pendiente el RVIE/RCE que adjuntará el usuario.

---

## 11. Causas raíz y hallazgos de código

### Causa raíz principal: dos flujos que no se hablan

El ERP tiene dos formas de registrar una salida de dinero:

1. **Importación bancaria:** crea un asiento `IMPORTACION:...` y un movimiento de tesorería.
2. **Registro de gasto/pago:** `registrar_gasto` crea un asiento `GASTO:...` y un movimiento de tesorería; `pagar` crea un asiento `COMPRA_PAGO` y otro movimiento.

No existe una clave única que impida que el mismo débito bancario se registre dos veces por los dos caminos. El asiento **37** es exactamente eso: el banco ya estaba importado (asiento 33) y luego se volvió a registrar el pago como si fuera una obligación de `Gasto`. El asiento **32** es un pago real y el **38** era una provisión mal clasificada. La solución no era solo anular el duplicado; es **vincular pago, asiento y movimiento** y validar la idempotencia. Además se separó provisión de pago con `Gasto.provision` y `Gasto.gasto_origen`.

### Tabla de hallazgos de código

| Prioridad | Archivo | Hallazgo | Impacto | Corrección propuesta |
|---|---|---|---|---|
| P0 | Datos | Asiento 37 duplica el pago del 31/10 y el asiento 38 clasifica una provisión contra banco | `4212` D 28; banco corto 28 | **Aplicado:** 37 anulado, 38 reclasificado a `4212`, 32 y 33 conservados, con historial |
| P0 | `compras/models_gasto.py` | `Gasto` no distingue provisión, pago ni vínculo con factura final | Duplicidad y pérdida de trazabilidad | **Aplicado:** `provision`, `gasto_origen`, `estado`, `fecha_devengado` |
| P0 | `contabilidad/impuestos.py` | No hay servicio de pago de IGV; la regla `IGV_MENSUAL` existe pero no se usa | No se puede registrar el pago de octubre | **Aplicado:** `pagar_igv` con validación, asiento, tesorería, auditoría y pruebas |
| P0 | `ventas/views.py:30-36` | `_numero_siguiente` no actualiza `Serie.ultimo_numero` | Números repetidos o concurrencia | **Aplicado:** bloqueo de empresa y actualización atómica al confirmar |
| P1 | `compras/views.py:727-779` | `corregir` no refresca glosas de asientos/tesorería | Trazabilidad engañosa | **Aplicado:** glosas vinculadas en la misma transacción |
| P1 | `compras/views.py:267-307`; `ventas/views.py:263-296` | Alta/edición sin `transaction.atomic` | Documentos incompletos ante error | **Aplicado:** vistas envueltas en transacción |
| P1 | `ventas/servicios.py:210-220` | NC reingresa stock al costo de la venta, no al de las capas originales | Costo distorsionado en devoluciones | Pendiente (Fase 2) |
| P1 | `reportes/views.py:267-301` | Registro de compras suma provisiones `OTRO` | Sobreestima compras en S/ 46 | **Aplicado:** excluye `provision=True` |
| P1 | `reportes/eeff.py:107-111` | Saldo deudor del elemento 4 se presenta como activo | Oculta el D 28 de `4212` | **Aplicado:** saldos deudores no tributarios reducen el pasivo |
| P2 | `core/management/commands/importar_excel.py:250` | `"Standard"` se mapea a `TIL-000002` (monitor) | Producto equivocado en instalación nueva | Parametrizar el mapeo y validar SKU |
| P2 | `core/management/commands/importar_excel.py:30-33` | Filas 3 y 9 de SUNAT hardcodeadas | Datos antiguos recreados | Leer del RVIE/RCE o de un archivo de configuración |
| P2 | `reportes/sire.py` | Lector heurístico sin prueba con archivo real | Importación SIRE no verificada | Probar con RVIE/RCE real y añadir pruebas |
| P2 | `pyproject.toml` / CI | Ruff no está en CI; 106 E501 en migraciones | Gate de estilo inconsistente | Excluir migraciones y añadir ruff a CI |

---

## 12. Plan de corrección (Fase 1 ejecutada)

**Estado:** los siete bloques de la Fase 1 se aplicaron el 2026-11-05 en `fix/auditoria-p0`, salvo el pago del IGV de octubre, que queda pendiente de confirmación del usuario. La corrección de datos se ejecutó con `manage.py corregir_auditoria_p0 --usuario mathew` (idempotente, transaccional y con validación previa). Las pruebas específicas `tests.test_auditoria_p0` pasaron: 9 de 9.

### Fase 1 — P0 contable (antes de cualquier funcionalidad nueva)

1. **Respaldo y rama de trabajo.**
   - Rama `fix/auditoria-p0`.
   - No se tocó `main`.
   - Migraciones aplicadas a Supabase.

2. **Anulación del asiento 37 y reclasificación del 38.**
   - Servicio `anular_asiento` con validación de estado, periodo abierto y permiso.
   - `estado = ANULADO`; no se borraron líneas ni asientos.
   - Motivo, usuario y detalle en `HistorialDocumento` (tipo `ASIENTO`).
   - Servicio `reclasificar_linea_asiento` para mover el crédito de S/ 10 de `1061` a `4212` conservando la línea y su historial.
   - Verificado: `4212 = 0`, `1061 = D 901.60`, balanza D=H, resultado 197.91, idempotencia y rechazo de periodos cerrados.

3. **Modelo de provisiones.**
   - Migración con `Gasto.provision`, `Gasto.gasto_origen`, `Gasto.estado` y `Gasto.fecha_devengado`.
   - Backfill: gastos 3, 12 y 13 como provisiones; 3 → 9; 12 y 13 → 11.
   - Exclusión de provisiones en `registro_compras`, exportaciones y casillas del 621.
   - FV20 con `fecha_devengado=2026-09-30` y FV15 con `2026-10-31`; la fecha del documento se conserva.
   - La contabilidad mantiene la fecha del documento; el PDT 621 usa la fecha devengada. No se movieron los asientos 31, 36, 39, 41 ni 42 de periodo.
   - Verificado: registro total S/ 1,635.44; casilla 120 78/53/0; sin doble conteo; resultado sin cambio.

4. **Flujo de pago de IGV.**
   - Servicio `pagar_igv(empresa, fecha, importe, medio, anio, mes)` con la regla `IGV_MENSUAL`.
   - Valida periodo abierto, importe pendiente y medio de pago.
   - Crea asiento D `40111` / H tesorería, movimiento de tesorería y registro de auditoría.
   - Botón y formulario en la pantalla del PDT 621 cuando la casilla 184 es positiva y hay saldo pendiente.
   - Pruebas: pago parcial y sobrepago.
   - **El pago de octubre no se registró:** siguen pendientes S/ 105.10 hasta que el usuario confirme fecha y cuenta.

5. **Series y numeración.**
   - `Serie.ultimo_numero` se actualiza de forma atómica al confirmar la venta, con bloqueo de la empresa.
   - No se modificaron E001-1/E001-2: ya están aceptadas por SUNAT.
   - Prueba: el correlativo avanza al confirmar y no retrocede.

6. **Glosas y atomicidad.**
   - `compras.views.corregir`: refresca glosas de asientos y movimientos vinculados.
   - `compras.views.nueva`, `compras.views.corregir` y `ventas.views.nueva`: envueltas en `transaction.atomic`.
   - Se actualizaron las glosas de los asientos 36, 39 y 41 con el número real de FV20.

7. **Pruebas e integración.**
   - Pruebas nuevas: anulación con historial e idempotencia, periodo cerrado, provisión sin tesorería, exclusión del 621, `fecha_devengado`, correlativo de series, pago parcial/sobrepago de IGV y clasificación de `4212` en los EEFF.
   - `manage.py check`: sin issues.
   - `ruff check` sobre los archivos modificados: sin errores.
   - `manage.py test tests.test_auditoria_p0 --keepdb`: 9 pruebas OK.
   - Este documento y `docs/manual.md` actualizados.

### Fase 2 — P1

- Nota de crédito: reingreso de stock al costo de las capas originales.
- Detracciones y retenciones.
- Control de crédito fiscal dentro de 12 meses.
- Alerta RER S/ 525,000.
- Control de bancarización.
- Formset de líneas en compras/ventas.
- Prueba del importador SIRE con el RVIE/RCE real.
- Prueba de cierre anual en `transaction.atomic()` + `set_rollback(True)`.

### Fase 3 — P2

- Guardrails del importador de Excel.
- Consistencia de `sembrar_productos` (TIL-000002 inactivo, TIL-000001 activo).
- Alertas y dashboard de conciliación bancaria.
- Documentación de operación y respaldo.

---

## 13. Criterios de aceptación de la Fase 1

| Criterio | Valor esperado |
|---|---|
| `4212` | S/ 0.00 |
| `1061` | D S/ 901.60 |
| `1031` | D S/ 1,213.96 |
| `40111` | C S/ 22.05 |
| `40171` | C S/ 17.95 |
| Balanza | Debe = Haber = S/ 10,665.51 |
| Resultado neto | S/ 197.91 |
| Total activo | S/ 2,576.91 |
| Registro de compras set–nov | S/ 1,635.44 |
| Casilla 120 | 78.00 / 53.00 / 0.00 |
| Asiento 37 | `ANULADO`, con historial; líneas conservadas |
| Asiento 38 | Crédito reclasificado de `1061` a `4212`; línea conservada |
| Asientos 32 y 33 | Conservados como pagos reales; 33 con fecha 31/10 |
| FV20 | Número `FV20-01490476` |
| Provisiones 3, 12 y 13 | `provision=True`, vínculo a factura final, excluidas del 621 |
| Documentos eliminados | 0 |
| Compras/ventas/capas eliminadas | 0 |
| Pruebas | 9/9 en `tests.test_auditoria_p0` |
| `manage.py check` | Sin issues |

---

## 14. Riesgos y prohibiciones

- **No borrar** asientos, compras, ventas, capas, movimientos ni gastos. Usar anulación, reverso o corrección con historial.
- **No modificar** E001-1/E001-2: ya están aceptadas por SUNAT.
- **No enviar** nada a SUNAT desde esta auditoría.
- **No almacenar** XML/PDF de comprobantes.
- **No commitear** `.env`, contraseñas ni cadenas de conexión.
- **No cerrar** periodos ni ejecutar el cierre anual hasta revisar los P0.
- **No reasignar** periodos con asientos en periodos cerrados sin reapertura auditada.
- **No confiar** en que "la balanza cuadra" como prueba de corrección: el caso de `4212` demuestra que un saldo deudor mal clasificado puede ocultar un descuadre.

---

## 15. Anexo: consultas de verificación

Comandos usados para la auditoría (solo lectura):

```powershell
# Estado del proyecto
.\.venv\Scripts\python.exe manage.py check

# Ruff sobre código de aplicación (las migraciones generadas se excluyen)
.\.venv\Scripts\ruff.exe check . --exclude migrations

# Pruebas específicas de la Fase 1 (contra Supabase, reutilizando la BD de test)
.\.venv\Scripts\python.exe manage.py test tests.test_auditoria_p0 --keepdb --noinput

# Dry-run y aplicación de la corrección de datos
.\.venv\Scripts\python.exe manage.py corregir_auditoria_p0 --dry-run --usuario mathew
.\.venv\Scripts\python.exe manage.py corregir_auditoria_p0 --usuario mathew
```

Consultas de control en Django shell:

```python
from decimal import Decimal
from django.db.models import Sum
from contabilidad.models import AsientoLinea
from contabilidad.impuestos import saldo_cuenta
from core.models import Empresa

empresa = Empresa.objects.get(ruc="20615841961")

# Balanza
AsientoLinea.objects.filter(
    asiento__empresa=empresa, asiento__estado="CONFIRMADO"
).aggregate(d=Sum("debe"), h=Sum("haber"))

# Saldos clave (acreedor positivo)
for cod in ["1061", "1031", "40111", "40171", "4212"]:
    print(cod, saldo_cuenta(empresa, cod, "2026-11-30"))
```

---

## 16. Historial de revisiones

| Fecha | Versión | Cambio |
|---|---|---|
| 2026-11-05 | 1.0 | Auditoría inicial de Fase 0; sin cambios en datos. |
| 2026-11-05 | 2.0 | Fase 1 aplicada: asiento 37 anulado, 38 reclasificado, 33 corregido, FV20 `01490476`, provisiones, `fecha_devengado`, pago de IGV, series y atomicidad. Balanza final S/ 10,665.51. |

## 17. Revisión adicional del lector SIRE — 2026-11-06

- Se corrigió la interpretación de importes con separadores mixtos: tanto
  `1.234,56` como `1,234.56` se interpretan como 1234,56. Se agregó una
  prueba de ambos formatos. El resultado no valida otros formatos ambiguos.
- SUNAT publica [estructuras de archivos SIRE](https://cpe.sunat.gob.pe/estructura-de-archivos),
  incluidos los anexos para reemplazo del RVIE y RCE. Es incorrecto afirmar
  de forma general que el formato no es público. Esas estructuras no prueban
  por sí solas que el lector heurístico admita todos los archivos de propuesta.
- Sigue pendiente contrastar el lector con archivos reales de propuesta RVIE y
  otros períodos de RCE, incluidos descuentos, signos, cabeceras y codificación.
  La propuesta RCE real de octubre contiene tres documentos y total S/ 43,00;
  el lector detecta base e IGV cero y ese total. El cálculo del ERP muestra
  S/ 53,00 no gravados. No considerar la conciliación validada integralmente.
- El cálculo anterior de gastos del 621 usaba `fecha_devengado` en lugar de un
  período de anotación tributaria independiente. La propuesta de octubre incluye FV20
  emitida en octubre, aunque corresponda a septiembre, y no incluye FV15,
  emitida en noviembre para octubre. La diferencia exige revisar documentos y
  reglas del período de anotación; no trasladar importes ni presentar cifras
  como definitivas hasta resolverlo. Las fechas contables y tributarias pueden
  diferir y deben poder explicarse por separado.
- Corrección del 06/11: la estimación usa la fecha del comprobante, no el
  devengo, y advierte que debe contrastarse con el RCE. Consultando los datos
  reales en modo lectura se obtienen 60,00 / 43,00 / 28,00 para septiembre,
  octubre y noviembre respectivamente. La estimación no implementa aún el
  período efectivo de anotación: una anotación posterior necesita revisión
  manual. Los valores 78/53/0 en secciones históricas quedaron supersedidos.
- Inventario: se impide que una salida consuma una capa de fecha posterior;
  la base real no tiene consumos con fecha posterior ni producto distinto.
  Se bloquean entradas y salidas anteriores a una salida ya registrada para el
  mismo producto. El sistema no recalcula PEPS retrospectivamente; queda
  pendiente un flujo auditado de corrección. Dentro del mismo día se conserva
  el orden de registro, pues no se captura la hora efectiva del movimiento.
- La exportación CSV duplicaba la base de compras no gravadas en las columnas
  de base gravada y no gravada; se corrigió y se añadió una prueba.
- La pantalla de compras solo consultaba mercadería. Se integraron los gastos y
  provisiones, con filtros, detalle y enlaces a sus relaciones; la lista no suma
  provisiones y facturas como si fueran operaciones independientes.
- La importación de mercadería desde XML creaba el borrador y sus líneas antes
  de confirmar; si la confirmación fallaba, el borrador quedaba en la base. La
  creación del proveedor, la compra, las líneas y la confirmación se agruparon
  en una transacción; al fallar se conserva la vista previa para corregirla.
- El administrador permitía crear o editar compras y gastos directamente sin
  ejecutar las operaciones contables. Se dejó en modo de consulta; las compras
  se registran desde su módulo y los gastos mediante importación o el nuevo
  formulario de gasto pagado en soles, con comprobante y pago de igual fecha.
  El vínculo de una provisión con su factura no la liquida por sí solo; falta
  implementar la liquidación completa y auditada de provisiones.
- Notas de venta: una nota sin reingreso generaba un asiento de inventario pese
  a no crear stock; se elimina esa reversión de costo cuando no hay retorno.
  Se rechazan notas anteriores a su venta y se serializan notas de crédito de
  una misma venta. El formulario solo ofrece anulación y devolución; los demás
  motivos requieren lógica propia. No había notas en la base real al auditar.
  Los servicios rechazan series y números repetidos dentro de una empresa,
  incluso entre ventas distintas y con ceros iniciales; separan notas de crédito
  y débito. Ventas y notas de crédito son de solo consulta en administración;
  la restricción de base sigue siendo por venta y no cubre escrituras directas.
- Conciliación SIRE: el lector sumaba importes DGNG y DNG como si fueran
  compras destinadas exclusivamente a operaciones gravadas. Ahora advierte y
  detiene la comparación al encontrar valores en esas columnas; no calcula la
  prorrata ni las casillas de operaciones mixtas. La propuesta real de octubre
  sigue leyendo tres documentos por S/ 43,00. La
  [ayuda oficial del 621](https://e-plataformaunica.sunat.gob.pe/app/recaudacion/tributaria/internet/html/archivos-ayuda/ayuda_621_igv_renta_mensual.pdf)
  distingue las casillas para compras destinadas a operaciones mixtas.
- La conciliación verifica el RUC y el período de la propuesta cuando aparecen
  por fila; rechaza diferencias y advierte si no pudo comprobarlos. También
  rechaza importes ilegibles y detecta el separador CSV desde la cabecera.
  El archivo real de octubre supera la comprobación de RUC y período. El tipo
  de registro aún debe confirmarse manualmente al seleccionar RCE o RVIE.
- Pago de IGV: el cierre del período tributario impedía registrar un pago en un
  mes posterior. El registro ahora comprueba que esté abierto el período de la
  fecha de pago, sin exigir reabrir el mes al que corresponde la deuda. El
  saldo del 621 sigue siendo una estimación y debe cotejarse con lo declarado.
- Identificación de gastos: se corrigió la restricción para incluir al proveedor
  además de empresa, tipo, serie y número. La prueba confirma que proveedores
  distintos pueden usar el mismo número y que no se repite el del mismo emisor.
  La migración 0016 se aplicó después de respaldar los gastos. Una consulta de
  lectura no encontró comprobantes coincidentes entre compras y gastos. Los
  servicios de compra y gasto ahora comprueban duplicados entre módulos y
  normalizan ceros iniciales y mayúsculas al comparar. Las provisiones no son
  facturas recibidas y quedan fuera de esa comparación; migración 0017 aplicada
  tras un respaldo de 11 gastos. El control no cubre escrituras directas por
  administración o SQL y no permite dividir un comprobante mixto en ambos
  módulos; requiere un diseño de líneas unificado.
- La [ayuda vigente del formulario 621](https://e-plataformaunica.sunat.gob.pe/app/recaudacion/tributaria/internet/html/archivos-ayuda/ayuda_621_igv_renta_mensual.pdf)
  describe la casilla 120 y su relación con el RCE. Las
  [preguntas frecuentes de SUNAT sobre SIRE](https://cpe.sunat.gob.pe/node/131)
  distinguen el período de anotación y sus ajustes. No se ha verificado aún si
  la propuesta de octubre fue aceptada o modificada antes de generar el RCE.
- Los artículos 18 y 19 de la [Ley del IGV](https://www.sunat.gob.pe/legislacion/tributaria/igv/ley/capitul6.htm)
  establecen requisitos sustanciales y formales para el crédito fiscal: una
  factura, por sí sola, no demuestra que el crédito corresponda.
- Una consulta de solo lectura al 30/11 confirmó los saldos de 1061
  (−901,60), 1031 (−1213,96), 40111 (22,05), 40171 (17,95) y 4212 (0,00),
  usando la convención de acreedor positivo. Los demás saldos y documentos de
  la revisión anterior aún no se han vuelto a verificar en esta revisión.
- Comprobación del 06/11: 11 pruebas de `tests.test_auditoria_p0` y 10 de
  `tests.test_sire` aprobadas; `manage.py check`, revisión de migraciones y
  Ruff sin hallazgos. Posteriormente se ejecutó la suite completa: 96 pruebas
  aprobadas. El ajuste final de importación se realizó durante esa ejecución y
  se comprobó después por separado junto con duplicados: seis pruebas aprobadas.

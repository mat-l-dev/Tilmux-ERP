# Auditoría exhaustiva del ERP TILMUX — Documento consolidado

> **Para colocar en `docs/` del repo como `docs/auditoria-exhaustiva-2026-11-10.md`**
> Consolida: auditoría v1 (2026-11-10), auditoría v2 (2026-11-10 noche), investigación normativa SUNAT (2026-11-09) y auditoría de vigencia del stack (2026-11-09).
> Corrige y reemplaza los documentos anteriores. Donde v1 y v2 discrepan, vale v2.

- **Repositorio:** `mat-l-dev/Tilmux-ERP` (privado, Python / Django 6.1 sobre PostgreSQL)
- **Rama auditada:** `main`
- **HEAD verificado:** `70271c790ec656d53c9eb7667b6b7d3f10f5f8aa` — «Registrar prueba de restauración verificada», 2026-11-10 00:01:14Z. Sin commits nuevos después de esa fecha en la verificación de v2.
- **Fecha de consolidación:** 2026-11-10 (Lima)
- **Alcance:** SOLO auditoría. Sin modificar código, sin crear rama, sin abrir PR, sin tocar `main`. Sin registrar pagos, declaraciones, restituciones ni movimientos. Sin acceso a la base real ni a SUNAT en vivo.
- **Empresa:** TILMUX S.A.C., RUC 20615841961 (termina en **1**), régimen RER, periodos 2026-09/10/11 ABIERTOS, sin cierre anual.
- **Método:** lectura completa de `docs/continuacion.md`, `docs/auditoria.md` (799 líneas), `docs/manual.md`, contraste con el código en `main` vía GitHub, 4 revisiones por dominio, re-verificación de los 17 archivos que en v1 quedaron sin leer por HTTP 429 (en v2, cero errores 429), y verificación de normativa SUNAT y del stack solo en fuentes oficiales consultadas el 09/11/2026.

---

## 1. Resumen ejecutivo

El ERP está contablemente ordenado en lo formal — balanza cuadrada, Fase 1 aplicada, reversión y liquidación verificadas como sólidas en código — pero **no es seguro declarar ni operar sobre él sin resolver los 8 P0**.

Los tres P0 nuevos no son adornos:

- **P0-6:** EXP-002 afirma un pago de S/ 500 que el usuario confirma que **no ocurrió**.
- **P0-7:** la confusión entre propuesta SIRE y registro generado ya está bloqueando el cierre de octubre.
- **P0-8:** vencimiento a días — SIRE **16/11/2026**, PDT 621 **17/11/2026** — con la caja dependiendo de que Mercado Pago transfiera el dinero.

A eso se suma un riesgo del stack que v1 no había cuantificado: **si el Postgres de producción en Render es plan Free, los datos caducan a los 30 días**. Hay que aclararlo antes que cualquier P0 de código.

La prioridad inmediata, antes de escribir una línea de código, es tributaria y documental: generar el RCE/RVIE de octubre (con la boleta complementada), declarar el PDT 621 el 17/11, pagar los S/ 105, corregir EXP-002 a PENDIENTE y hacer las restituciones con voucher cuando llegue el depósito de Mercado Pago.

### Cifras de control — valores corregidos y vigentes

| Dato | Valor verificado |
|---|---|
| Balanza (documentada 5–9/11, no re-verificada contra BD) | D = H = S/ 10.665,51; resultado neto S/ 197,91; descuadre S/ 0,00 |
| Saldos clave al 30/11 | `1061` D 901,60 (BBVA 457,60 + BCP 444,00); `1031` D 1.213,96 (Mercado Pago); `40111` C 22,05; `40171` C 17,95; `4212` 0,00; `4411` C 500,00; `4419` C 39,00; inventario `20111` D 461,35 |
| Ventas octubre (RVIE, confirmado) | BI 1.196,62; IGV 215,38; total 1.412,00 |
| Renta RER octubre | **S/ 17,95** (1,5% × 1.196,62) |
| IGV octubre | En libros **S/ 105,38** (215,38 − 110); en declaración en enteros **S/ 105** (RS 025-2000, primer decimal 3 < 5). **Sin pagar al 09/11/2026** |
| Saldo a favor setiembre (145) | **110 en enteros** (constancia 1211949769). No 110,28. La v1 usaba 110,28 y daba 105,10; queda corregido |
| Crédito fiscal octubre | **0** (propuesta RCE: BI gravado 0, IGV 0) |
| Casilla 120 octubre | **43** por propuesta CSV (15 + 10 + 18). **241,04 en libros con la boleta complementada** (43 + 198,04). No 53 (ERP sobrecuenta S/ 10) |
| PDT 621 setiembre — cerrado | Orden **1211949769**, presentada 19/10/2026 09:41:33, total a pagar S/ 0. 107 = 613; 108 = 110; 120 = 60; 184 = −110; 303 = 0; 304 = 0 |
| RCE setiembre — definitivo | «Propuesta Aceptada», 4 registros: BI 612,72 + IGV 110,28 + no gravado 60,00 = 783,00. RVIE setiembre: 0 registros, 0 inconsistencias |
| PDT 621 octubre | **No declarado al 09/11/2026** |
| RCE / RVIE octubre definitivo | **No generados al 09/11/2026**. Solo existen: RVIE octubre como export/propuesta (2 docs) y RCE octubre como propuesta CSV (3 docs, S/ 43) |

---

## 2. Cuadro consolidado de prioridades

### P0 — bloquean declarar u operar

| # | Hallazgo | Dónde / evidencia |
|---|---|---|
| **P0-1** | CI solo corre tras el merge a `main`; merge = despliegue automático sin gate | `.github/workflows/tests.yml` (solo `push main` + manual, sin `pull_request`, sin ruff), `render.yaml` (`autoDeploy: true`). Agravado: `checkout@v4` / `upload-artifact@v4` sobre Node 20 deprecado; sin caché de uv; `uv sync` sin `--frozen` |
| **P0-2** | No existe flujo de nota / devolución a proveedor (deuda, reembolso, inventario, RCE) | Ausencia en `compras/`. `compras/reversion.py` verificado en v2: es corrección interna sólida, **no** devolución. Manual lo confirma: «aún no está implementado» |
| **P0-3** | No existe flujo de devolución del préstamo socio S/ 500 (`4411`) ni del reembolso S/ 39 (`4419`) | Reglas solo en sentido de entrada (`PRESTAMO_SOCIO`, `REEMBOLSO_SOCIO` en `sembrar_reglas.py`); `REEMBOLSO_SOCIO` no tiene ningún llamador. Intentar por flujos existentes cae en `4212` o en gasto |
| **P0-4** | Moneda extranjera: no se conserva el saldo en moneda original | `compras/models.py` (solo `total_moneda_origen` estático), `compras/servicios.py:430-434, 488` (`pagar()` descarta la porción FX). `TipoCambio.del_dia()` (`core/models.py:98-103`): fallback silencioso al TC anterior confirmado |
| **P0-5** | Casilla 184 no es la deuda final; pago de IGV ignora la constancia; no hay declaración vigente; residuo de céntimos sin vía | `contabilidad/impuestos.py:153-241`, `contabilidad/models.py:9-44`, `reportes/views.py:365-581, 650-671`. **Cuantificado en v2:** libros 105,38 / declaración 105, crédito 0, 120 = 43 / 241,04. Boleta sube a P0 porque bloquea el cierre de octubre |
| **P0-6 — NUEVO** | Veracidad documental: EXP-002 dice RESTITUIDO 08/10/2026 por S/ 500, el usuario confirma que **NO pagó, se olvidó** | EXP-002 (texto, elaboración 07/10/2026): retiro op 6674 18:15:02, depósito op 6675 18:16:30, 18/09/2026. Datos de R1 en [COMPLETAR]. Sin voucher, sin N° de operación. El ERP debe exigir voucher bancario y mantener PENDIENTE hasta tenerlo |
| **P0-7 — NUEVO** | SIRE: propuesta ≠ aceptada ≠ generada; el ERP no distingue los estados | `reportes/sire.py` solo lee primera hoja, no distingue propuesta de definitivo, tipo elegido manualmente. Debe guardar por separado: (a) propuesta, (b) propuesta complementada, (c) definitivo con constancia de recepción |
| **P0-8 — NUEVO** | Alerta de vencimiento y caja: PDT octubre sin declarar, SIRE octubre sin generar, IGV sin pagar, restituciones esperando a Mercado Pago | Vencimientos RUC …1: SIRE **16/11/2026**, PDT 621 **17/11/2026**. Depósito Mercado Pago esperado 09/11, a las 11:22 aún no había llegado. El ERP debe mostrarlo en rojo, no dejar creer que está al día |

### P1 — riesgo alto, no bloquea el cierre de octubre por sí solo

| # | Hallazgo |
|---|---|
| P1-1 | Nota de crédito reingresa al costo promedio, no restaura capas PEPS originales. Confirmado con matiz en v2: el promedio nace en `inventario/servicios.py:139` (`salir()` guarda costo unitario promedio de las capas consumidas). Con una sola capa, promedio = original, por eso los tests no lo distinguen. Ejemplo: venta 2u capas 274,58/338,14, devolución 1u reingresa @306,36 en vez de @274,58 (+S/ 31,78). Manual/README prometen «costo original», lo contrario del código |
| P1-2 | Reversión ≠ devolución; compra pagada + devolución real = sin vía. Reversión verificada en v2 y más estricta de lo mínimo (motivo, sin pagos, sin periodos cerrados, sin stock consumido, coherencia estricta) |
| P1-3 | Casilla 120 contradictoria entre docs — **resuelto para octubre:** 120 = 43 por propuesta; 241,04 en libros con boleta. La contradicción 53 vs 43 queda explicada: el ERP sobrecuenta S/ 10 |
| P1-4 | SIRE: lector heurístico, solo probado con archivos sintéticos. Avance parcial: ahora hay archivos reales SUNAT para validar (RCE setiembre definitivo, RVIE octubre export). Sigue sin validarse contra el RCE octubre definitivo, que no existe aún |
| P1-5 | Tipo de cambio: fallback silencioso, `SinTipoCambio` no capturado en `pagar()`. Confirmado en código (`core/models.py:98-103`, `contabilidad/moneda.py`) |
| P1-6 | Transferencia BBVA↔BCP invisible en contabilidad (ambas 1061: D/H se anulan; solo queda en `MovimientoTesoreria`) |
| P1-7 | Conciliación manual, solo soles, ±3 días, sin extractos. Caso vivo: débito BCP 04/11 S/ 10 `ENVIO.ESTADO.CTA` ausente del ERP. EXP-003 confirma que ese cobro existe como operación distinta, pero sigue sin extracto/voucher |
| P1-8 | Respaldo «verificado» solo compara filas (46 tablas). No cubre secuencias, permisos, RLS, índices/triggers/vistas, ni arranque de la app. **Agravado por stack:** Postgres de producción en Render no está documentado; si es plan Free, caduca a los 30 días. Respaldo en Artifacts (30 días) no es un almacén de respaldos |
| P1-9 | Cobro bloqueado por movimiento histórico no vinculado; asignación a cuotas exige que el cobro quepa en una sola cuota |
| P1-10 | IGV de costos landed (flete/internamiento) se acredita sin comprobante propio |
| P1-11 | Provisiones 4211 (nuevas) / 4212 (históricas) conviviendo. **Liquidación verificada en v2** (`compras/liquidacion.py`): las reglas del manual sí están en código, con matiz (atomicidad no visible en el archivo; `liquidar_provisiones()` sin `@transaction.atomic` visible) |
| P1-12 | Permisos por empresa incompletos. Parcialmente verificado en v2: filtros por empresa consistentes en `core/views.py` (panel, periodos, cierre); **no hay RLS en el código de la app** (0 menciones en 17 archivos); aislamiento solo a nivel de aplicación. Falta revisar migraciones para descartar RLS a nivel BD. Única excepción: `core/views.py:221` conteo global de cuentas activas |
| P1-13 | Casillas 303/304 en `None`; sin control de crédito fiscal a 12 meses; detracciones/retenciones/bancarización/RER S/ 525.000 en backlog. **303/304 cerrados para setiembre:** 0,00 / 0,00 (detalle de casillas, orden 1211949769) |

### P2 — higiene, docs y controles menores

| # | Hallazgo |
|---|---|
| P2-1 | Ruff en `pyproject.toml` pero no en CI; 106 E501 en migraciones. Ruff 0.17.3 en lock vs 0.17.4 vigente. Sin `exclude` para migraciones |
| P2-2 | Nota de débito sin validar motivo ni tope; motivos de NC incompletos (solo 01, 06, 07) |
| P2-3 | Duplicado de comprobante solo se controla al confirmar, no al crear el borrador; serie/número de compra confirmada con error no se corrige, solo se rellena |
| P2-4 | Comprobante mixto mercadería+gasto sin división; gasto en USD sin mensaje propio; compra FX en borrador queda varada sin aviso al crearla |
| P2-5 | Docs internos contradictorios: cifras de pruebas 73/96/304, casilla 120, respaldo de lunes, total del registro. `README.md` omite la mayoría de módulos reales |

**Orden de trabajo recomendado:** (1) gate de CI en PR + freno al despliegue automático + aclarar Postgres de producción en Render; (2) nota de proveedor con salida PEPS por capa original; (3) restitución 4411/4419 con voucher obligatorio (P0-6); (4) saldo en moneda original + TC sin fallback silencioso; (5) deuda final de IGV contra constancia con campo vigente y redondeo a enteros registrado como campo auditable + estados SIRE separados (P0-7) + alerta de vencimiento (P0-8); (6) flujo Complementar propuesta RCE para la boleta tipo 03.

---

## 3. Hallazgos detallados

### 3.1 IGV declarado, pagos y cierre tributario (P0-5 ampliado)

**P0-5a. La 184 registrada no es la deuda final y el pago ignora la constancia.**
`contabilidad/impuestos.py:153-185` (`igv_pendiente` = 184 estimada del libro − pagado) y `:189-241` (`pagar_igv`); `reportes/views.py:365, 429-430, 444-448, 474-476, 650-671`. El código nunca lee `DeclaracionIGV621`. `pagar_igv_mes` rechaza usar el saldo declarado para pagar (`views.py:670-671`). Reproducir: registrar constancia octubre con 140=215, 145=110, 184=105; el pendiente seguirá siendo el del libro y el pago máximo seguirá siendo el del libro, no 105. Riesgo: pagar 105,38 creyendo que es «la 184», o pagar 105 creyendo que salda la deuda; libro y SUNAT quedan desalineados sin ningún campo de deuda final, intereses ni mora.

**P0-5b. Rectificatoria/sustitutoria sin declaración vigente.**
`contabilidad/models.py:9-44` (`DeclaracionIGV621`, tipos ORIGINAL/SUSTITUTORIA/RECTIFICATORIA, `UniqueConstraint` empresa+número de orden solo si `anulada=False`); migración `0012_declaracionigv621.py` (generada 2026-11-09, con RLS `REVOKE ALL … FROM PUBLIC, anon, authenticated`); `reportes/views.py:510-581`; `reportes/forms.py:20-41` (solo valida 184 = 140 − 145). El modelo guarda solo tipo, número de orden, fecha, casillas 140/145/184 en enteros, registrado por/en y anulación. No hay campo vigente/efectiva, ni vínculo con pagos, ni casillas 100/101/107/108/120/301/312 de esa constancia. «Anular» solo marca el registro interno. Test `tests/test_declaracion_621.py:37-50`: original 184=105 y rectificatoria 184=106 coexisten (`count()==2`), sin pago creado. Con una rectificatoria presentada, el ERP sigue calculando desde el libro y mostrando ambas sin indicar cuál rige.

**P0-5c. Diferencia de céntimos — corregido en v2.**
No existe ningún tipo de asiento, cuenta ni servicio de ajuste por redondeo. `contabilidad/servicios.py:38` usa `quantize(CENT, ROUND_HALF_UP)`; `reportes/casillas.py:107` calcula la renta con `(base × 0,015).quantize(0,01)` sin `rounding=` (contexto por defecto, `ROUND_HALF_EVEN`). Las casillas de la constancia son enteras.
Regla verificada (RS 025-2000, art. 2): las declaraciones-pago se presentan en enteros (en medios telemáticos, solo el rubro determinación de la deuda); primer decimal < 5 queda igual, ≥ 5 sube. El redondeo **no** aplica a libros/registros. 105,38 → primer decimal 3 → **105**. Por eso v1 (105,10) queda corregida: en libros la deuda es **105,38** (215,38 − 110), en la declaración es **105**. El ERP debe guardar céntimos en libros y redondear solo la deuda (184/188/304), registrando el redondeo (S/ −0,38) como campo auditable, no como asiento sin sustento. `docs/continuacion.md` lo prohíbe expresamente: «No modificar libros por céntimos sin evidencia».

**P0-5d. La 40111 mezcla meses.**
`contabilidad/impuestos.py:174-185`, `:130-151`. Al 30/11 la `40111` tiene C 22,05 = 105,38 (octubre) − 83,05 (crédito noviembre); la 184 de noviembre es solo noviembre (−83,05) y no arrastra la deuda impaga de octubre. Riesgo: leer la 40111 (22,05) como si fuera la deuda de octubre.

**Casilla 120 y renta.**
`reportes/casillas.py:18` (`TASA_RENTA_RER = 0,015`), `:50-90` (compras y gastos: `fecha_tributaria = Coalesce(fecha_anotacion, fecha)`, `con_credito=True`; no gravado = compras con `igv == 0`), `:92, 106-107` (renta = base ventas × 1,5%). La renta coincide con auditoría §10 (1,5% × 1.196,62 = 17,95; asiento 25: D 881 / C 40171). El código actual usa `fecha_anotacion` (o emisión si está vacía), **no** `fecha_devengado`: el modelo de §7 («el PDT 621 usa la fecha devengada») está obsoleto. Diferencia en octubre: S/ 10,00 (53 vs 43). Test `tests/test_periodo_anotacion.py:56-75` confirma el criterio actual.

**SIRE: lector heurístico, solo archivos sintéticos.**
`reportes/sire.py:47-77, 142-193, 227-281`; `reportes/views.py:830-958`; `reportes/conciliacion_rce.py:21, 34-66`. `tests/test_sire.py` (282 líneas) usa solo archivos construidos en el test con `SimpleTestCase` y mocks; ningún test carga un archivo descargado de SUNAT. El lector solo lee la primera hoja, no distingue propuesta de RCE/RVIE definitivo generado, y el tipo de registro se elige manualmente. La propuesta RCE real de octubre contiene 3 documentos por S/ 43,00; el ERP muestra S/ 53,00 no gravados (`cuadra=False`, `dif_total ≠ 0`).

**Boleta B001-00393302 S/ 198,04 — clasificación correcta, sin vía para incluirla.**
Gasto 7 (6311, sin crédito ni deducción, no va al 621). `compras/comprobantes.py:22-31` (`evaluar_tributacion`: `incluido = con_credito and tipo == "FACTURA" and not incompleto`; una boleta nunca es `incluido`). `reportes/casillas.py:71-90` la excluye doblemente de 107/108 y de 120. En `registro_compras` (`reportes/views.py:277-360`) aparece con base/no gravado/IGV = 0, pero su total (198,04) **sí suma al total del registro**, y `reportes/conciliacion_documentos.py:55-76` la acumula en `sin_credito`. No existe ninguna función, campo ni vista para «incluir manualmente» un documento en la propuesta RCE; el ERP no escribe a SUNAT. Además `reportes/casillas.py:113-181` (`casillas_documento`) solo tiene ramas `Compra` y `Venta`: un gasto devuelve `[]`, así que su tarjeta «PDT 621» no muestra casilla.

**P2 tributario.** Casillas 303/304 hardcodeadas a `None` (`reportes/views.py:490-491`); la renta a pagar se muestra solo vía saldo 40171. Sin verificación del plazo de crédito fiscal a 12 meses. Operaciones mixtas/IVAP bloquean la conciliación, no se calculan (`reportes/sire.py:255-265`). Sin verificación de la constancia ante SUNAT ni de intereses/mora. La renta asentada distinta a la calculada exige anulación manual (`contabilidad/impuestos.py:80-90`). El cierre de mes no exige constancia 621, RCE/RVIE definitivo ni pagos: solo «revaluar y cerrar, no deben quedar borradores». La exportación CSV ya tuvo un bug de duplicación de base no gravada, corregido con test (`tests/test_exportar.py:14-37`).

### 3.2 Compras, notas de proveedores, devoluciones y PEPS (P0-2, P0-3, P1-1, P1-2)

**P0-2. No existe flujo de nota/devolución a proveedor.**
Búsqueda de «nota» en `compras/servicios.py` y `compras/models.py`: cero ocurrencias reales (solo `anotar`/`fecha_anotacion`). En `compras/views.py` la única mención es el rechazo en importación (L.692): «Este flujo solo registra facturas y boletas; las notas requieren otro tratamiento». `docs/continuacion.md` pendiente 2 y `docs/manual.md` §Compras lo confirman. Consecuencia: una devolución real no puede reducir la deuda `4212`, ni revertir el IGV `40111`/RCE, ni dar salida PEPS de las capas de esa compra, ni registrar el reembolso en tesorería, ni vincular la NC del proveedor a la compra original.

**P1-1. Nota de crédito de venta: reingreso al costo promedio.**
`ventas/servicios.py:197-339` (`emitir_nota_credito`). L.281-285: `costo = linea.costo_total × proporcion_acumulada − costo_anterior`, cálculo puramente proporcional, sin leer ninguna capa/consumo. L.308-320: una sola llamada a `entrar(..., costo_unitario = costo/pedida, origen_tipo="NOTA_CREDITO")`, que crea **una capa nueva al promedio**, no las capas originales. Causa raíz, L.146-148 en `confirmar`: la línea guarda solo `costo_unitario` (promedio) y `costo_total`; no hay vínculo línea→capas consumidas que la NC pudiera restaurar. Verificado en v2: `inventario/servicios.py:139` — `salir()` guarda el costo unitario promedio ponderado de las capas consumidas. Hoy sin impacto en datos porque «no hay NC», pero es el primer riesgo en la primera devolución real.
Detalles: con `reingresa_stock=False`, `costo=0`, no hay `entrar()`, pero sí se acreditan base+IGV; si el bien vuelve físicamente y se marca `False`, el stock se pierde silenciosamente. Si `costo/pedida` no se representa con 10 decimales exactos a céntimos, la NC **falla** (`VentaError`) en vez de asignar el residuo a la última unidad (L.309-312). El periodo cerrado no lo valida la NC.

**P1-2. Reversión ≠ devolución.**
`compras/views.py:1156-1170` (`anular`): exige `confirmo_error=on`, mensaje «Confirma que se trata de un registro interno erróneo, **no de una devolución**», y llama a `revertir_registro`. `compras/reversion.py` — **verificado en v2 (152 líneas)**: `revertir_registro()` L19–152 impone todas las condiciones y más: motivo 10–1000 caracteres; solo compra CONFIRMADA de la empresa; **sin pagos**; **sin periodos cerrados**; **sin stock consumido**; coherencia estricta (exactamente 1 asiento COMPRA CONFIRMADO, debe = haber = total, haber−debe en 4212 = total, líneas = capas = entradas). Ejecución: asiento inverso, origen `REV_COMPRA`; SALIDA que consume cada capa (no borra historia); compra → ANULADA + historial REVERSION. **La reversión es una corrección interna sólida; sigue sin ser una devolución a proveedor (P0-2).** Agujero combinado: compra **pagada** + devolución real = bloqueada para revertir (tiene pago) y sin flujo de nota → **sin ninguna vía en el sistema**.

**P2-2. Nota de débito sin controles; motivos NC incompletos.**
`ventas/servicios.py:341-389` (`emitir_nota_debito`): valida venta confirmada, fecha ≥ venta, sin cobros posteriores y numeración, pero **no valida `motivo_codigo`**, no topa base/IGV contra la venta, no exige descripción ni comprueba notas previas. `MOTIVOS_CREDITO_IMPLEMENTADOS = {"01","06","07"}` (L.34).

**P2-3. Duplicados y corrección de serie/número.**
`compras/servicios.py:36-45` (`validar_comprobante`) delega en `buscar_comprobante` (`compras/comprobantes.py` — **verificado en v2, 58 líneas**: normaliza serie y número, solo FACTURA/BOLETA, busca en `Compra` CONFIRMADA y `Gasto` con `provision=False`, **no cuenta provisiones**). Se invoca en `confirmar` y en `registrar_gasto` no-provisión, pero `compras/views.py:343-633` (`nueva`) **no** la llama: dos borradores con el mismo serie-número pueden coexistir; el error aparece recién al confirmar el segundo. `corregir` (`views.py:1099-1102`) solo **rellena** serie/número vacíos; una serie/número con error de digitación en compra confirmada no se puede corregir por este flujo.

**Mixto / landed / provisiones.**
Comprobante mixto: `Compra` (`compras/models.py:13-77`) es solo mercadería; `Gasto` es un modelo aparte sin FK a `Compra`; no hay campo de reparto ni vínculo. Costos landed: `compras/servicios.py:94-114` prorratea por valor o cantidad; `CostoAdicional` solo tiene concepto/base/IGV/total/criterio, **sin tipo_doc, serie, número ni RUC**. L.104: sin crédito, el IGV del costo va al inventario (correcto); con crédito, L.139-141 suma `c.igv` al `compra.igv` y `postear` lo trata como crédito, **sin que exista documento que sustente ese IGV**. Provisiones: `registrar_gasto` (L.216-232) permite `gasto_origen` solo si `provision=True`, sin IGV. `compras/liquidacion.py` — **verificado en v2 (144 líneas)**: `preparar_provisiones()` exige `igv == 0` salvo `permite_igv`, misma empresa/proveedor, exactamente 1 asiento GASTO/PROVISION_GASTO; `cuenta_deuda_provision()` acepta 4211 nueva o 4212 histórica, sin mezclar; `validar_provisiones_vinculadas()` con IGV solo si `con_credito` + FACTURA + exactamente 1 provisión. **Las reglas del manual sí están en código (P1-11 pasa de «no verificado» a «verificado con matiz»).** Rama provisión (L.285-311): asienta D gasto / H **4211**; las provisiones históricas quedaron en **4212** y «conservan su asiento original». Convivencia 4211/4212 sin nota de migración: riesgo de que reportes que filtren por una sola cuenta pierdan las otras.

### 3.3 Moneda extranjera, tesorería, pagos y conciliación (P0-4, P0-3, P1-5/6/7/9)

**P0-4. Saldo en moneda original no conservado.**
`compras/models.py` (`Compra`): solo existe `total_moneda_origen` (total original, estático) y `tipo_cambio` (informativo). **No existe** `pagado_moneda_origen` ni `saldo_moneda_origen`; `monto_pagado` es en soles. `pagar()` (:430-434): calcula la porción FX proporcional, luego `pagado = _cent(porcion × tasa)` y `diferencia = pagado − llevado`, pero **descarta `porcion`**: `:488` hace `monto_pagado = pagado_previo + llevado` (soles). Tras un pago completo no queda registro de cuántos USD se pagaron ni a qué TC efectivo. `revaluar()` (:538-539): `objetivo = total_moneda_origen × tasa_cierre` vs `llevado = total + revaluacion`; ignora cualquier pago parcial (por eso lo bloquea en :512). Reproducir: compra USD 100 / S/ 345,20; pagar completo con TC 3,500 → `pagado=350,00`, diferencia 4,80 (test `tests/test_invariantes.py:552-601`); intentar pagar 50 parcial → error de :410. **Levantar los bloqueos sin añadir un campo de saldo en moneda origen produciría saldos imposibles de conciliar.**

**Bloqueos FX verificados (mensajes literales, coherentes con docs):** confirmar compra mercadería USD — `compras/servicios.py:61-62`; confirmar venta USD — `ventas/servicios.py:99-100`; cobrar venta USD — `ventas/servicios_cobro.py:63-64`; pago parcial USD — `compras/servicios.py:409-410`; pago desde cuenta no-PEN — `:374-375`; revaluar con parciales — `:512-515`; transferencia entre monedas o en USD — `tesoreria/servicios.py:120-132`; gasto USD — `compras/servicios.py:234-236`. Una compra FX creada como borrador nunca se puede confirmar y queda varada en Pendientes; no hay aviso en `nueva` que impida crearla.

**Diferencia de cambio (verificada).** Cuentas `6761` (pérdida) y `7761` (ganancia). Pago: `pagado − llevado`; si > 0 → D `6761`; si < 0 → H `7761`; siempre D `4212` por `llevado` y H tesorería por `pagado`. Revaluación: `delta = total_moneda_origen × TC_cierre − (total + revaluacion)`; si > 0 → D `6761` / H `4212`; si < 0 → D `4212` / H `7761` (asiento `REVALUACION` al último día del mes). Ventas: **no hay** diferencia de cambio (venta USD y cobro USD bloqueados).

**P1-5. Tipo de cambio SUNAT: fallback silencioso y error no capturado.**
Descarga: `core/management/commands/actualizar_tipo_cambio.py` — `GET https://www.sunat.gob.pe/a/txt/tipoCambio.txt`, solo descarga el día corriente, no rellena días perdidos. Programación: `.github/workflows/tipo-cambio.yml`, cron `1 5 * * *` (00:01 Lima) + manual, sin reintento ni aviso de fallo. Uso: `contabilidad/moneda.py:tipo_cambio_de()` → `TipoCambio.del_dia(fecha)` (`core/models.py:98-101`): `filter(fecha__lte=fecha).first()` (orden `-fecha`). **Si no hay TC de esa fecha, usa silenciosamente el último anterior**, sin advertencia ni log; si no hay ninguno, `ValueError` → `SinTipoCambio`. En `compras/servicios.py:418-428` el `try` solo captura `(InvalidOperation, ValueError)`; `SinTipoCambio` (subclase directa de `Exception`) **escapa sin convertirse en `CompraError`**. `a_soles()` usa `venta` por defecto; `pagar()` y `revaluar()` también usan **venta**, nunca compra.

**Pagos parciales en soles: funcionan.** Compras (`compras/servicios.py:391-407`); gastos por pagar (`compras/gastos_pendientes.py: pagar_gasto`); ventas al crédito (`ventas/servicios_cobro.py`).

**P1-9. Cobro bloqueado por movimiento histórico no vinculado.**
`ventas/servicios_cobro.py:80-84`: si existe **cualquier** `MovimientoTesoreria` con `origen_tipo="VENTA"` e `INGRESO` para esa venta, bloquea todo cobro posterior. La asignación a cuotas exige que el cobro completo quepa en **una sola cuota** (:104-112); no reparte entre cuotas.

**P1-6. Transferencia BBVA↔BCP invisible en contabilidad.**
`1061` agrega **BBVA + BCP** en una sola cuenta (457,60 + 444,00 = D 901,60). No hay submayor por banco en contabilidad. `tesoreria/servicios.py: transferir()` crea los dos movimientos y un asiento `TRANSFERENCIA` (regla en `sembrar_reglas.py:85-88`). **Si origen y destino apuntan a la misma cuenta contable (BBVA→BCP, ambas 1061), el asiento es D 1061 / H 1061 por el mismo importe: neto cero e invisible en el mayor.** El traslado solo queda en `MovimientoTesoreria`.

**P1-7. Conciliación bancaria: existe, pero manual, solo soles, sin extractos.**
`tesoreria/models.py: ConciliacionBancaria` y `tesoreria/conciliacion.py: buscar_candidatos()` (misma cuenta, mismo tipo, mismo importe exacto, ±3 días), `confirmar()` (exige `moneda="PEN"`), `revertir()`. Lo que **no** hace: no importa extractos, no compara saldo bancario contra saldo contable, no hay saldo inicial, no concilia cuentas en USD, no detecta movimientos **ausentes** en el ERP. Caso vivo: débito BCP 04/11 S/ 10,00 (`ENVIO.ESTADO.CTA`) no está en `MovimientoTesoreria` y la conciliación no puede encontrarlo.

**P0-3. Devoluciones S/ 500 y S/ 39: sin flujo de restitución.**
Estado en libros: `4411` C S/ 500,00; `4419` C S/ 39,00; pasivo total S/ 579,00. Ambas siguen pendientes. Las reglas **existen solo en sentido de entrada**: `PRESTAMO_SOCIO` = D medio / H `4411` y `REEMBOLSO_SOCIO` = D medio / H `4419` (`sembrar_reglas.py:61-63, 81-83`). **No existe** ninguna regla inversa ni servicio/vista que las use. `PRESTAMO_SOCIO` aparece solo en modelos, migraciones, `sembrar_reglas.py` e `importar_excel.py` (suspendido); `REEMBOLSO_SOCIO` aparece solo en modelos, migraciones y `sembrar_reglas.py`: **ningún llamador en todo el repo**. El asiento correcto sería D `4411` S/ 500 / H `1061` (o `101`) y D `4419` S/ 39 / H medio que corresponda, con movimiento de tesorería y voucher — **ese servicio no existe**. Riesgo si se intenta por los flujos existentes: `tesoreria/servicios.py: registrar()` egreso → D `4212` / H banco (la `4411`/`4419` nunca se cancela); `registrar_gasto()` → D cuenta 6xxx / H banco (la devolución se registraría como **gasto**); `pagar()` / `pagar_gasto()` → D `4212` / H banco (mismo error). **No se registró ninguna de estas devoluciones en esta auditoría.**
Doble conteo S/ 39: gasto 5 (token físico S/ 39,00, pagado en efectivo, **sin comprobante**, no va al 621) ya está reconocido y **además** existe `4419` C 39,00. Interpretación probable (a confirmar con documentos): el Gerente General adelantó los S/ 39 (por eso `4419`) y el gasto se pagó con ese efectivo. Si es así, la devolución es solo D `4419` / H `101` o banco, **sin tocar gasto**. Sin voucher no se puede distinguir de un gasto pagado con caja propia mal clasificado en `4419` o de un segundo registro del mismo hecho. Registrar la devolución como gasto nuevo duplicaría los S/ 39.

### 3.4 P0-6, P0-7, P0-8 — los tres nuevos, detallados

**P0-6. Veracidad documental — EXP-002 afirma un pago que no existió.**
EXP-002 (elaboración 07/10/2026) dice «RESTITUIDO; transferencia realizada el 08/10/2026» y «RESTITUIDO — PAGADO» por S/ 500. El usuario confirmó el 09/11/2026 que **no pagó, se olvidó**. Los datos de R1 siguen en [COMPLETAR]. Sin voucher, sin N° de operación, sin cuenta de origen.
Riesgo: si el ERP (o una persona) toma el texto del expediente como prueba, la 4411 queda en cero falso y la restitución desaparece del pendiente. Es el mismo patrón que v1 ya señalaba para la 184: un documento interno no es una constancia.
Qué debe exigir el ERP: estado de la restitución = PENDIENTE hasta que exista un movimiento bancario verificable (voucher con N° de operación, fecha/hora, cuenta de origen y destino, importe exacto S/ 500,00, concepto). El expediente debe corregirse a PENDIENTE y completarse solo con el voucher real. Lo mismo aplica al reembolso de S/ 39: EXP-003 dice PENDIENTE correctamente; no debe cambiar a PAGADO sin voucher.
Relacionado: P0-3 y P0-6 se resuelven juntos: el flujo debe pedir el voucher como dato obligatorio, no opcional.

**P0-7. SIRE: propuesta ≠ aceptada ≠ generada.**
Hecho normativo (verificado, §4): propuesta desde el día 2; preliminar desde el día 8 del mes siguiente; Aceptar ≠ Generar.
Hecho del ERP: el lector SIRE (`reportes/sire.py`) solo lee la primera hoja, no distingue propuesta de definitivo, y el tipo de registro se elige manualmente. No existe campo de estado del periodo SIRE.
Qué debe guardar el ERP, por periodo y por registro (RVIE y RCE por separado): (a) propuesta descargada (archivo original, fecha de descarga, hash); (b) propuesta complementada/reemplazada (qué comprobantes se agregaron o excluyeron, con motivo); (c) registro generado (constancia de recepción, N° de operación, fecha/hora, N° de registros). Sin (c), el periodo no está cerrado tributariamente, aunque la propuesta esté aceptada.
Caso vivo: el CSV de propuesta RCE octubre (3 docs, S/ 43) existe desde el 05/11, pero no hay RCE definitivo de octubre. El ERP no debe mostrar octubre como «conciliado» ni «cerrado».
Corrección al diagnóstico anterior: el «No items found» en Gestión de Compras el 09/11 21:55 fue transitorio (el usuario indica que el periodo siempre aparece ahí). No es un fallo del SIRE ni del ERP; la propuesta existe. La lección es la contraria: que la propuesta exista no significa que el registro esté generado.

**P0-8. Alerta de vencimiento y caja.**
Hechos: PDT 621 octubre sin declarar (vence **17/11/2026**); SIRE octubre sin generar (vence **16/11/2026**); IGV octubre sin pagar (S/ 105 en enteros); restituciones S/ 500 + S/ 39 esperando a que Mercado Pago transfiera el dinero (el depósito se esperaba el 09/11 y a las 11:22 aún no había llegado).
Qué debe mostrar el ERP: un panel de vencimientos con ambas fechas, el estado de cada registro (propuesta / complementada / generada / declarada / pagada), y la dependencia de caja (las restituciones no se pueden hacer sin el depósito de Mercado Pago; el IGV sí vence aunque el depósito no llegue).
Riesgo si no se hace: declarar tarde por creer que «la propuesta ya está» o pagar tarde por esperar el depósito. La facultad discrecional hasta 28/02/2027 (RSNATI 041-2026) cubre la sanción por SIRE, no el vencimiento del PDT ni los intereses moratorios del IGV.

### 3.5 Respaldos y verificación de restauración (P1-8)

Respaldo diario `.github/workflows/backup.yml`: cron `0 6 * * *` (06:00 **UTC** = 01:00 Lima; el manual dice «todos los días a las 06:00» sin precisar zona — discrepancia P2), `pg_dump "$DATABASE_URL" -Fc` a `out/tilmux.dump`, artefacto `tilmux-<run_number>`, `retention-days: 30`. **El workflow no verifica el dump**: ni restaura, ni comprueba lectura, ni checksum. Verificador `scripts/verificar_respaldo.py`: `huellas_tablas()` = por cada tabla `public` con prefijo ERP: `count(*)` + `md5(string_agg(md5(row_to_json(t)::text)))`. `crear_copia()`: conexión `REPEATABLE READ` + `pg_export_snapshot()`, `pg_dump -Fc -n public --snapshot=…`. `verificar_copia()`: compara cantidad+huella tabla por tabla. Workflow `.github/workflows/verificar-restauracion.yml`: lunes 09:00 UTC + manual; levanta `postgres:17`, `DROP SCHEMA public CASCADE`, `pg_restore -O -x --exit-on-error`, luego `verificar`. La ejecución del 9/11 (run 42724851652) con coincidencia en **46 tablas** es afirmación de `docs/continuacion.md` — **el log de esa ejecución no se verificó**, solo el documento y el código del verificador.
**Qué NO verifica:** (1) **secuencias**; (2) **permisos/roles** (`pg_restore -O -x` descarta propietario y privilegios; `row_security off` ignora RLS); (3) **índices, triggers, constraints, funciones, vistas** (solo `relkind IN ('r','p')`); (4) **funcionamiento de la app restaurada** (no ejecuta `manage.py check`, ni tests, ni login, ni `/salud/` contra la BD restaurada); (5) **corrección contable** (el hash no distingue un asiento correcto de uno erróneo). El manual exagera: «Cada lunes se restaura en una base limpia y se comprueba que los **saldos** coincidan» — el código comprueba huellas de filas, no saldos; y hay una sola copia (artefacto GitHub, 30 días) sin segunda copia externa ni cifrado documentado.

### 3.6 Estructura, CI, despliegue, pantallas y permisos (P0-1, P1-12, P2)

**P0-1. CI solo post-merge.**
`.github/workflows/tests.yml`: `on: push branches: [main]` + `workflow_dispatch` — sin `pull_request`. Servicio `postgres:17`, `uv sync`, `uv run python manage.py test tests -v 2`. Reproducir: abrir `Actions → Tests` en un PR contra `main` — no se ejecuta; mergear a `main` y solo entonces corre. Riesgo: código roto o con invariantes contables rotas llega a `main` y, combinado con P0-2, a producción antes de saberse.

**P0-1 (despliegue). Merge a `main` = despliegue automático, migraciones fuera de `render.yaml`.**
`render.yaml: autoDeploy: true`, sin comando de migración visible en ese archivo. `docker-entrypoint.sh` (6 líneas, **verificado en v2**): `uv run --no-dev python manage.py migrate --noinput` y luego `exec "$@"`. **Migraciones al arrancar: CONFIRMADO, comando exacto ese.** `Dockerfile` (24 líneas, verificado): `python:3.14-slim`, `uv sync --frozen --no-dev`, `collectstatic` con `DATABASE_URL` dummy de build, gunicorn 2 workers, puerto 8080. `docs/despliegue.md` (32 líneas, verificado): Render free/Blueprint, `DATABASE_URL` Supabase session pooler 5432, `autoDeploy: true`, migraciones al arrancar vía entrypoint, salud en `/salud/`. Riesgo: un merge con migración defectuosa, o con una migración ya aplicada editada, migra la base real de producción sin aprobación manual ni paso previo. Agravado por `0012_declaracionigv621`: ya está aplicada y no debe editarse.

**Cifras de pruebas contradictorias.**
`continuacion.md`: **304 pruebas** (9/11). `auditoria.md` §2: **73 pruebas OK (1008 s)** contra Supabase con `--keepdb`, 5/11. `auditoria.md` §17: **96 pruebas** aprobadas, 6/11; `11/11` en `test_auditoria_p0` y `10/10` en `test_sire`. Búsqueda `filename:test_` devuelve 47 archivos `test_*.py`. No se puede afirmar «la suite pasa / son 304» para el HEAD `70271c`; 73/96/304 corresponden a fechas, bases y alcances distintos. Verificación pendiente: `Actions → Tests` en el commit `70271c` y contar `Ran N tests`.

**P2-1. Ruff sin gate.**
`pyproject.toml`: `ruff>=0.17.3` solo en grupo `dev`; `[tool.ruff] line-length=120`, `select=["E","F","I","UP","B"]`. `tests.yml` no tiene ningún paso `ruff`. Auditoría §2: «`ruff check .` falla con **106 E501** en archivos de migración generados. El código de aplicación sí pasa `ruff check . --exclude migrations`. La CI no ejecuta ruff».

**P1-12. Permisos por empresa: modelo declarado, incompleto.**
Manual: «Un usuario con un perfil asignado a una empresa solo puede seleccionarla… Los superusuarios pueden seleccionar cualquier empresa activa… **los catálogos siguen siendo compartidos entre empresas**». Advertencias en auditoría §17: «Pago, confirmación, corrección y anulación verifican la empresa seleccionada. **Esta protección no sustituye un modelo de permisos de acceso por empresa**»; «Los catálogos compartidos y **el aislamiento de los demás módulos aún requieren revisión**»; «El control [de duplicados] **no cubre escrituras directas por administración o SQL**». **Verificado en v2:** `core/views.py` (425 líneas) — `panel()` L118–250 todo filtra `empresa=empresa_actual(request)`; periodo validado estricto (AAAA-MM). Única excepción: L221 `cuentas_activas = Cuenta.objects.filter(activa=True).count()` sin filtro de empresa — coherente si el PCGE es catálogo global, pero es el único conteo global. `cambiar_empresa()`, `periodos()`, `cerrar_periodo()`, `revaluar_periodo()` (solo si ABIERTO), `reabrir_periodo()`, `cerrar_ejercicio()`, `revertir_ejercicio()` (**solo superusuario**): todos con filtro por empresa y `requiere_escritura` donde corresponde. Tests de permisos (`test_empresas_permisos.py`, 8 tests) cubren sesión manipulada, 404 en documentos ajenos, 403 sin empresa y 403 en admin para staff no superusuario. `config/settings.py` (196 líneas, verificado): solo PostgreSQL, vía `DATABASE_URL` obligatoria; `sslmode` `require` por defecto; `TIME_ZONE = America/Lima`, `LANGUAGE_CODE = "es-pe"`; **RLS: ninguna mención** (grep RLS/POLICY = 0 en los 17 archivos). El aislamiento es a nivel de aplicación: `core.acceso.AccesoEmpresaMiddleware` + filtros por empresa. Salvedad: las migraciones no se revisaron en esta ronda y podrían contener políticas SQL.

**P2. Pantallas/flujos: lo que dice el manual no quedó contrastado con vista/template/test en v1.**
Manual: Panel — saldos 101/1031/1061 hasta último día del mes elegido, «no es un saldo bancario conciliado»; ventas del mes sin IGV, con notas en mes de emisión. Mayor — selector de cuentas, saldo inicial con asientos confirmados anteriores. Compras — filtro Tipo, búsqueda por proveedor/comprobante/concepto, fechas emisión/devengo/anotación. Pendientes — cada fila tiene **Completar**. Tesorería — «Comparar con el banco» ventana ±3 días, solo soles. **No verificado en v1:** `core/views.py`, templates, `tests/test_panel_periodos.py`, `test_filtros_ventas.py`, `test_filtros_reportes.py`, `test_guia.py` (bloqueados por 429). En v2 `core/views.py` sí se verificó (ver arriba); templates y tests de filtros siguen sin verificación en vivo. **Laguna de verificación, no bug demostrado.**

**P2. `README.md` §Estructura omite la mayoría de los módulos reales.**
La tabla lista solo `config/`, `core/`, `contabilidad/`, `data/`, `templates/`, `static/`. Omite `catalogo`, `compras`, `ventas`, `inventario`, `tesoreria`, `reportes`, `tests/`, `docs/`.

**Funciones incompletas / «todavía no» (todas citadas en docs o código verificados).**
Moneda extranjera; PEPS sin recálculo retrospectivo; nota de proveedor / reversión auditable; comprobante mixto; notas de venta (motivos de descuento y corrección de descripción «aún no están implementados»); SIRE (IVAP y operaciones mixtas «se bloquean… porque el ERP aún no calcula esas casillas»); tributario en backlog (detracciones, retenciones, control de crédito fiscal a 12 meses, alerta RER S/ 525.000, bancarización); respaldo (verificador «no valida permisos, secuencias, extensiones ni corrección contable»); cierre tributario sin checklist; dentro del mismo día se conserva el orden de registro, pues no se captura la hora efectiva del movimiento; la marca de conciliación bancaria requiere un flujo de usuario auditado que aún no está implementado; los anticipos, detracciones, retenciones y otras deducciones en ventas al crédito «requieren tratamiento adicional».

### 3.7 Otros hallazgos de código verificados

- **Causa raíz de los duplicados (auditoría §11, vigente como riesgo):** dos formas de registrar una salida de dinero sin clave única — importación bancaria (asiento `IMPORTACION:...`) y registro de gasto/pago (`GASTO:...`, `COMPRA_PAGO`) — sin idempotencia que impida que el mismo débito bancario se registre dos veces por los dos caminos. El asiento 37 fue exactamente eso.
- **Importador de Excel (suspendido):** `core/management/commands/importar_excel.py:250` mapea `"Standard"` a `TIL-000002`; `:30-33` filas 3 y 9 de SUNAT hardcodeadas. El README lo marca como suspendido: «requiere actualizar y verificar sus asociaciones antes de usarlo».
- **Tests FX bypassean el bloqueo:** `tests/test_invariantes.py:552-601` (pago USD completo, dif. 4,80 en `6761`) y `:604-657` (revaluación 4,80 y pago posterior) crean la compra USD directamente en BD, bypasseando `confirmar()`. No hay test que afirme el rechazo de pago parcial USD, el rechazo de revaluar con parciales, ni el comportamiento sin TC. Una regresión que levante un bloqueo pasaría inadvertida.
- **Balanza que cuadra no prueba corrección:** auditoría §14 — «No confiar en que "la balanza cuadra" como prueba de corrección: el caso de `4212` demuestra que un saldo deudor mal clasificado puede ocultar un descuadre». Sigue vigente como principio: todos los hallazgos anteriores coexisten con balanza D=H y descuadre 0,00.
- **`inventario/servicios.py` — verificado en v2 (166 líneas):** `entrar()` L49–88 crea `CapaFIFO` con el costo unitario dado, sin promediar. `salir()` L91–166: PEPS real — capas `fecha__lte`, `cantidad_restante__gt=0`, `order_by("fecha","id")`, `select_for_update`; costo por capa redondeado al centavo; si falta stock, `StockError` dentro de `@transaction.atomic`.
- **`compras/comprobantes.py` — verificado en v2 (58 líneas):** `evaluar_tributacion()` L22–32: `incluido` solo si `con_credito` + FACTURA + no incompleto; `requiere_revision` si incompleto o `con_credito` con tipo ≠ FACTURA. Docstring: «sin comprobar la validez del comprobante en SUNAT». `ruc_valido()` L17–19: 11 dígitos ASCII.
- **Tests muestreados en v2 — verificados (68 métodos en 6 archivos; `tests/` tiene 47 archivos `test_*.py`):** `test_notas_redondeo.py` (3), `test_numeracion_notas.py` (6), `test_reversion_compra.py` (5), `test_invariantes.py` (41 tests, 842 líneas: «contrato del motor»), `test_empresas_permisos.py` (8), `test_panel_periodos.py` (5).

---

## 4. Evidencia nueva aportada por el usuario (revisada en v2)

### 4.1 PDT 621 setiembre 2026 — cerrado
- Constancia Form. 0621, periodo 202609, original, N.° de orden **1211949769**, presentada **19/10/2026 09:41:33**. Total a pagar **S/ 0**.
- Detalle de casillas: 107 = 613,00; 108 = 110,00; **120 = 60,00**; ventas 100/101 = 0; 301 = 0; 140 = −110; 145 = 0; **184 = −110**; 302 = 0; **303 = 0; 304 = 0**; 185 = 0; 187 vacío; 188 = 0.
- RCE setiembre definitivo, «Propuesta Aceptada», 4 registros: BI 612,72 + IGV 110,28 + no gravado 60,00 = 783,00. Docs: BBVA FB29-29158446 11/09 no gravado 45; MERCADOLIBRE F002-5995 18/09 BI 274,58 IGV 49,42 total 324; BBVA FB29-29458395 30/09 no gravado 15; MERCADOLIBRE F002-5998 18/09 BI 338,14 IGV 60,86 total 399. RVIE setiembre: 0 registros, 0 inconsistencias.
- **Corrección a v1:** la v1 calculaba el saldo a favor de setiembre como 110,28 (céntimos del RCE). La constancia declara **110 en enteros**. El arrastre a octubre es 110, no 110,28.

### 4.2 Octubre 2026 — ventas confirmadas, compras con crédito cero
- RVIE octubre (archivo de exportación/propuesta, generado 08/11/2026, 2 documentos E001-1 y E001-2, 29/10): BI **1.196,62**, IGV **215,38**, total 1.412,00. Confirma exactamente las ventas del ERP. **No** es la constancia del RVIE definitivo.
- RCE octubre, propuesta CSV `20615841961-20261105-1833-propuesta.csv` (descargada 05/11/2026 18:33): periodo 202610, 3 documentos, todos no gravados, total **S/ 43,00**: BBVA FB29-29938941, 30/10/2026, S/ 15,00; BCP FN01-52311518, 17/10/2026, S/ 10,00; BCP FV20-1490476, 05/10/2026, S/ 18,00. BI gravado 0,00; IGV 0,00.
- **Boleta B001-00393302 S/ 198,04 no está en la propuesta** (comportamiento normativo, ver §5). No hay RCE octubre definitivo, no hay PDT 621 octubre, no hay pago del IGV de octubre.

### 4.3 Expedientes EXP-001 / EXP-002 / EXP-003
- **EXP-001 (capital inicial, 06/10/2026):** aportes S/ 1.800 en BBVA (07/09 S/ 500 + 17/09 S/ 400 + 17/09 S/ 900). Documento dice expresamente que no es aumento de capital ni préstamo. **Es un S/ 500 distinto del préstamo BCP** (aporte en BBVA 07/09 vs entrega temporal BCP 18/09). Riesgo real de confundir los dos S/ 500. Sin firmas ni datos completos.
- **EXP-002 (entrega temporal S/ 500, elaboración 07/10/2026, texto compartido 09/11/2026):** entrega 18/09/2026, retiro op 6674 18:15:02, depósito op 6675 18:16:30, S/ 500, para apertura de cuenta BCP. Afirma «RESTITUIDO; transferencia realizada el 08/10/2026» y «RESTITUIDO — PAGADO». **El usuario corrigió el 09/11/2026: la restitución NO se pagó, se olvidó de pagar.** Los datos de R1 siguen en [COMPLETAR]. Sin firmas ni datos completos. **Ver P0-6: el expediente, tal como está, es falso en su afirmación central y no puede usarse como sustento de cancelación de la 4411.**
- **EXP-003 (token físico BCP S/ 39, 08/10/2026):** 03/10/2026, retiro TILMUX op 0412566 −39, depósito personal del Gerente General op 0416457 +39, constancia BCP «COMISIÓN TOKEN FÍSICO» S/ 39, IGV 0. Reembolso **PENDIENTE** (la constancia dice que no acredita que ya se efectuó). Cuentas candidatas 6391 / 4419. **Discrepancia sin resolver:** el expediente dice que adelantó el Gerente General; la auditoría lo registraba como «S/ 39 al padre». Sin firmas ni datos completos. Excluye expresamente el cobro de S/ 10 por envío de estado de cuenta (confirma que existe como operación distinta, sin extracto). Menciona que existe un EXP-002 (ahora aportado como texto).

---

## 5. Normativa SUNAT verificada en fuentes oficiales (09/11/2026)

Solo lectura de fuentes oficiales. **[Verificado]** = leído en fuente oficial SUNAT / El Peruano en esa sesión. **[Interpretación]** = aplicación razonada de la regla verificada al caso TILMUX. **No verificado** = no se encontró fuente oficial; no inventar.

### 5.1 SIRE — RS 112-2021, RS 040-2022, propuesta RCE, Anexo 8 / Tabla 11

| Punto | Regla verificada | Fuente oficial |
|---|---|---|
| Base | RS 112-2021 aprueba el módulo RVIE; RS 040-2022 aprueba el módulo RCE y conforma el SIRE (RVIE + RCE) | SUNAT RCE: https://cpe.sunat.gob.pe/node/160 |
| Propuesta RCE | SUNAT pone la propuesta desde el **2.º día calendario** de cada mes; se actualiza diariamente. Contiene solo lo indicado en la columna «Información de la propuesta» de la **Tabla 11, Anexo 1, RS 040-2022** | https://cpe.sunat.gob.pe/node/160 |
| Preliminar: día 8 | El preliminar se genera **a partir del 8.º día calendario del mes siguiente** al periodo | https://cpe.sunat.gob.pe/node/160 |
| Aceptar | Aceptar = sin ninguna modificación respecto de lo propuesto; luego se genera el preliminar. Se pueden excluir documentos (salvo notas de crédito) solo en el módulo RCE vía SOL / cliente SIRE | https://cpe.sunat.gob.pe/node/160 |
| Complementar (Anexo 8) | Complementar = incluir información de documentos comprendidos en la propuesta, modificarla o reubicarla; o **incluir documentos que se pueden complementar**, en formulario o archivo plano según **Anexos 8 o 10** | https://cpe.sunat.gob.pe/node/160 |
| Reemplazar (Anexo 11) | Reemplazar = modificar o añadir **incluso información que, según la Tabla 11, no puede ser considerada al complementar**, con archivo plano Anexo 11 | https://cpe.sunat.gob.pe/node/160 |
| Tabla 11: tipo 03 Boleta de Venta | **«03 Boleta de Venta — No / Sí / No»**: columna «Información de la propuesta» = **No**; columna «Información del RCE (8.4)» = **Sí**. En cambio 01 Factura = Sí / Sí / No; 07 Nota de crédito = Sí; 08 Nota de débito = Sí | El Peruano, Anexo B RS 040-2022, Tabla 11: http://www.normaslegalesonline.pe/imagenes//24/03/2022/1648162434976_ANEXO-B.pdf — corroborado por SUNAT RCE, que lista los comprobantes que presenta la propuesta —01, 07, 08, 23, 30, 34, 42— sin el 03 |
| Plazo máximo de atraso SIRE — periodo oct-2026, RUC termina en 1 | **16 de noviembre de 2026** (columna «1»). Tabla completa oct-2026: 0→13 nov, 1→16 nov, 2 y 3→17 nov, 4 y 5→18 nov, 6 y 7→19 nov, 8 y 9→20 nov, Buenos contribuyentes/UESP→23 nov | SUNAT, Cronograma de atraso de registros electrónicos 2026: https://www.sunat.gob.pe/orientacion/cronogramas/cronoRegistroC-V-2026.html — Anexo II, RS 281-2022/SUNAT |
| Facultad discrecional RSNATI 041-2026 | Amplía la facultad de **no sancionar** las infracciones de los numerales 2 y 10 del art. 175 CT configuradas en los periodos **ago, set, oct, nov, dic 2026 y ene 2027**, siempre que se regularice **hasta el 28 de febrero de 2027**. No modifica los plazos máximos de atraso ni elimina la obligación | SUNAT Emprender, Facultad discrecional: https://emprender.sunat.gob.pe/acciones-sunat/facultad-sancionadora/facultad-discrecional — texto en El Peruano: https://busquedas.elperuano.pe/dispositivo/NL/2548699-1/pdf |

**Consecuencia directa para la boleta:** la boleta tipo 03 **no está en la propuesta por diseño normativo, no por error**. Debe incorporarse por **Complementar (Anexo 8)**, no por Reemplazar. Va al RCE (compra), no al RVIE. **Corrección a v1:** la v1 decía que la norma del Anexo 8 / tipo 03 «no aparece en el repo y no se contrastó con la fuente oficial». En v2 queda **verificada en fuente oficial**.

### 5.2 PDT 621 / Declara Fácil — IGV, renta RER, casillas, redondeo, plazos

| Punto | Regla verificada | Fuente |
|---|---|---|
| Requisito previo | Para usar el FV 621 hay que haber presentado antes el RVIE y el RCE del periodo; el formulario muestra automáticamente la información de esos registros | SUNAT, Ayuda FV 621: https://e-plataformaunica.sunat.gob.pe/app/recaudacion/tributaria/internet/html/archivos-ayuda/ayuda_621_igv_renta_mensual.pdf, §2 |
| Tasa IGV | Tasa total **18%**. **Novedad 2026 (Ley 32387): la composición cambia — 2026: IGV 15,5% + IPM 2,5% = 18%;** 2027: 15,0% + 3,0%; 2028: 14,5% + 3,5%; 2029: 14,0% + 4,0%. El total a pagar no cambia | SUNAT Orientación IGV: https://orientacion.sunat.gob.pe/3053-concepto-tasa-y-operaciones-gravadas-igv-empresas |
| Casilla 100 / 101 | 100 = ventas netas gravadas (base, sin IGV), dato del RVIE. 101 = 18% sobre 100 | Ayuda FV 621, § II Ventas |
| Casilla 107 / 108 | 107 = compras netas destinadas a ventas gravadas exclusivamente (base, neta de descuentos/devoluciones), dato del RCE. 108 = 18% sobre 107 | Ayuda FV 621, § II Compras |
| Casilla 120 | 120 = **compras netas internas no gravadas**: monto total de adquisiciones internas no gravadas, netas de descuentos y devoluciones, dato del RCE | Ayuda FV 621, § II Compras |
| Casilla 140 / 145 / 184 | 140 = impuesto resultante o saldo a favor IGV. 145 = saldo a favor del periodo anterior (IGV). **184 = 140 − 145** | Ayuda FV 621, § III |
| Casillas 185 / 187 / 188 | 185 = pagos previos (IGV). 187 = interés moratorio (TIM diaria = TIM/30). **188 = 184 − (171+168+179+176+185) + 187**. 189 = importe a pagar (= 188) | Ayuda FV 621, § III |
| Casillas 301 / 312 / 302 / 303 / 304 | 301 = ingresos netos (base). **RER: 1,5% de los ingresos netos (casilla 301)**. 312 = tributo resultante. 302 = 312. 303 = saldo a favor del periodo anterior (renta). **304 = 302 − 303**. Luego 317 pagos previos, 319 interés, **324 = 304 − (326+327+305+328+306+317) + 319** | Ayuda FV 621, § II Renta y § III; tasa RER también en https://emprender.sunat.gob.pe/ruc/regimenes-tributarios-mype/regimen-especial-renta-rer |
| Saldo a favor anterior | Casillas 145 (IGV) y 303 (renta) recogen el saldo a favor del periodo anterior, cada tributo por separado | Ayuda FV 621, § III |
| Redondeo RS 025-2000 | Art. 2: la información de las declaraciones-pago se expresa en **números enteros**; en medios telemáticos, solo el rubro **determinación de la deuda tributaria**. Primer decimal < 5 → queda igual; ≥ 5 → sube. **El redondeo NO se aplica a los Libros y Registros Contables** | SUNAT, RS 025-2000: https://www.sunat.gob.pe/legislacion/superin/2000/025.htm |
| Vencimiento PDT 621 oct-2026, RUC termina en 1 | **Martes 17 de noviembre de 2026** (columna «1»). Tabla oct-2026: 0→16 nov, 1→17 nov, 2 y 3→18 nov, 4 y 5→19 nov, 6 y 7→20 nov, 8 y 9→23 nov, Buenos contribuyentes/UESP→24 nov | SUNAT, Cronograma de obligaciones mensuales 2026: http://www.sunat.gob.pe/orientacion/cronogramas/2026/cObligacionMensual2026.html — Anexo I, RS 281-2022/SUNAT |

**Aplicación a octubre:** 105,38 → primer decimal **3** (< 5) → **105**. El ERP debe guardar céntimos en libros/RCE y redondear **solo la deuda** (casillas 184/188/304/324). No redondear bases 100/107/120/301. La diferencia de S/ 0,38 no es un error ni un descuadre: es el redondeo normativo, y debe quedar registrada como campo `redondeo_deuda = -0,38`, no como ajuste manual sin explicación.
**Secuencia TILMUX oct-2026:** preliminar SIRE desde 8 nov → SIRE límite 16 nov → 621 límite 17 nov.

**Respuestas a las tres preguntas (verificadas):**
1. **¿B001-00393302 debe ir en el RCE por Complementar? Sí.** Tipo 03 no está en la propuesta por Tabla 11, sí es información del RCE, Complementar es la vía correcta (Anexo 8). Clasificar como **tipo 03, estado «a complementar»**, periodo 202610. **No va a 107/108** (no da crédito fiscal: boleta, sin IGV discriminado utilizable). Va a **casilla 120**. Efecto fiscal: **ninguno en IGV a pagar ni en renta RER**. Su efecto es de completitud y sustento. Condición: verificar el desglose del XML/PDF de la boleta antes de cerrar; si fuera factura cambiaría todo, pero con serie B001 no es el caso.
2. **¿Casilla 120 de octubre es 43? Sí, y pasa a 241,04 si se complementa la boleta.** 15 + 10 + 18 = **43**. Aceptando la propuesta tal cual, 120 = 43. Complementando la boleta, 120 = 43 + 198,04 = **241,04** (en libros, con céntimos).
3. **¿IGV octubre 105 en enteros vs 105,38 en libros es redondeo SUNAT? Sí — si 105,38 es la deuda tributaria (no una base).** Ver RS 025-2000 arriba.

### 5.3 RER — requisitos, libros, sin declaración anual

| Punto | Regla verificada | Fuente |
|---|---|---|
| Sujetos y actividades | Personas naturales, sociedades conyugales, sucesiones indivisas y personas jurídicas domiciliadas, con rentas de 3.ª categoría de **comercio y/o industria** y **servicios** | https://emprender.sunat.gob.pe/ruc/regimenes-tributarios-mype/regimen-especial-renta-rer — DS 179-2004, arts. 117–124 LIR |
| Límites (art. 118 LIR) | Ingresos netos anuales ≤ **S/ 525 000**; adquisiciones afectadas anuales ≤ **S/ 525 000**; activos fijos afectados ≤ **S/ 126 000** (sin predios ni vehículos); personal ≤ **10 por turno**. Superar cualquiera = salida del RER (al RMT o RG desde el mes en que se supera) | Misma página SUNAT RER |
| Tributos | Renta: **1,5% de ingresos netos mensuales** (cuota definitiva). IGV: **18%**. Declaración mensual por FV 621 | Misma página SUNAT RER |
| Libros obligatorios | **Solo Registro de Ventas y Registro de Compras** (hoy vía SIRE) | Misma página SUNAT RER |
| Declaración anual | **Los contribuyentes del RER no están obligados a realizar la Declaración Jurada Anual del Impuesto a la Renta** | Misma página SUNAT RER |

**Implicación ERP:** debe llevar acumulados anuales de ingresos y adquisiciones y alertar al acercarse a S/ 525 000. No debe exigir Libro Diario/Mayor ni DJ anual para RER. Sí debe llevar control interno de caja/cuentas por cobrar-pagar e inventario (gestión, no obligación tributaria formal) — distinguir ambos planos en la UI.

### 5.4 Bancarización — Ley 28194, DL 1529

| Punto | Regla verificada | Fuente |
|---|---|---|
| Umbral | Obligatorio usar medios de pago desde **S/ 2 000 o US$ 500**. Aplica aun cuando se cancele mediante pagos parciales menores (se evalúa el total de la obligación, no cada parcial) | SUNAT Emprender, Bancarización: https://emprender.sunat.gob.pe/comprobantes-libros/comprobantes-pago/bancarizacion — Informe SUNAT 047-2026/340000: https://www.sunat.gob.pe/legislacion/oficiosAd/2026/2026-INF-047-340000.pdf |
| Medios de pago (art. 5) | Depósitos en cuenta, giros, transferencias, órdenes de pago, tarjetas de débito/crédito expedidas en el país, cheques, remesas y cartas de crédito (vía empresas del sistema financiero) | Misma página SUNAT Emprender; Informe 047-2026 |
| Consecuencia (art. 8) | Los pagos sin medio de pago **no dan derecho a deducir gastos, costos o créditos**; ni a compensaciones, devoluciones, saldos a favor, reintegros, recuperación anticipada o restitución de derechos arancelarios | Informe SUNAT 047-2026 (art. 8 TUO Ley 28194) |

**Implicación TILMUX:** compras de S/ 272–399 y la restitución de S/ 500 están **por debajo** del umbral: no hay obligación de bancarizar esas operaciones concretas. Pero fraccionar artificialmente una operación ≥ S/ 2 000 no elude la obligación. El ERP debe evaluar el **importe total de la obligación**, no cada pago aislado; si importe ≥ S/ 2 000 y medio = efectivo, marcar alerta dura. La restitución de S/ 500 y el reembolso de S/ 39 conviene hacerlos por transferencia con concepto claro, como evidencia — recomendación de gestión, no obligación por umbral. Yape/Plin: **no verificado** si SUNAT los admite como medio de pago del art. 5 entre privados — no asumirlo.

### 5.5 Comprobantes de pago — factura vs boleta, crédito fiscal, liquidación de compra

| Punto | Regla verificada | Fuente |
|---|---|---|
| Factura vs boleta (crédito fiscal) | Crédito fiscal: requisitos sustanciales (art. 18 Ley IGV) y formales (art. 19: **IGV discriminado en el comprobante**, nombre/RUC del emisor, **anotación en el Registro de Compras**). La boleta no discrimina el IGV para el comprador y **no da derecho a crédito fiscal** | Arts. 18–19 TUO Ley IGV (DS 055-99-EF) y Ley 29215, art. 2 — verificados vía análisis concordantes; **texto oficial del TUO no abierto en esa sesión: calificar como verificado-vía-secundaria**. Reglamento IGV, art. 6: https://www.sunat.gob.pe/legislacion/igv/regla/cap5.pdf |
| Anotación y plazo del crédito | El crédito se ejerce en el periodo en que el comprobante se anota en el RCE; la Ley 29215 permite anotar hasta 12 meses desde el mes siguiente a la emisión, y no se pierde si la anotación es **antes de que SUNAT requiera** la exhibición del registro | Misma verificación que la fila anterior (Ley 29215, art. 2) |
| Liquidación de compra (Reglamento de Comprobantes de Pago, art. 6) | Solo la emiten adquirentes por compras a **personas naturales productoras y/o acopiadoras** de **productos primarios** (agropecuaria, pesca artesanal, madera, minería aurífera artesanal, artesanía, desperdicios, etc.) a personas sin RUC | SUNAT, Carta 018-2005: https://www.sunat.gob.pe/legislacion/oficios/2005/oficios/c0182005.htm — Informe 125-2013: https://www.sunat.gob.pe/legislacion/oficios/2013/informe-oficios/i125-2013.pdf |
| Boleta con RUC del comprador | Que la boleta se emita con el RUC de TILMUX y aparezca en «Comprobantes de Pago» de SUNAT no la convierte en factura ni le da crédito fiscal | Consecuencia directa de arts. 18–19 + Tabla 11 |

**Consecuencia directa:** la liquidación de compra **NO aplica** a la compra del Starlink Mini normal (ni a ninguna electrónica): no es producto primario, el vendedor es persona con RUC 10 y DNI, y el bien es manufacturado/importado. El ERP **no debe ofrecer** liquidación de compra como vía para comprarle el Mini al usuario. **No verificado:** cuál es la vía correcta para que TILMUX adquiera un bien a una persona natural con RUC 10 sin actividad empresarial — queda como punto abierto para consulta SUNAT/contador.

### 5.6 Precios de transferencia / valor de mercado — art. 32 y 32-A LIR

| Punto | Regla verificada | Fuente |
|---|---|---|
| Art. 32 LIR (regla general) | En ventas, aportes de bienes y demás transferencias, el valor asignado será el **de mercado**. Entre vinculadas, el valor de mercado son los precios que se hubieran acordado entre partes independientes en transacciones comparables, según el art. 32-A | SUNAT, Informe 000042-2026-SUNAT/7T0000: https://www.sunat.gob.pe/legislacion/oficios/2026/informe-oficios/i000042-2026-7T0000.pdf |
| Art. 32-A: métodos | Métodos: 1) precio comparable no controlado, 2) precio de reventa, 3) costo incrementado, 4) partición de utilidades, 5) margen neto transaccional, 6) otros (modificado por DL 1663, vigente 1 ene 2025; reglamentado por DS 302-2025-EF) | Mismo Informe 042-2026 |
| Restitución del préstamo S/ 500 | **[Interpretación, no una regla citada]** La restitución (devolver los mismos S/ 500) **no es** una venta, aporte ni prestación de servicios del art. 32: no hay transferencia de propiedad ni contraprestación, sino extinción de una obligación. El art. 32/32-A **no fija** un «precio de mercado» para la restitución del principal. Lo que sí exige el ordenamiento es **sustento**: préstamo y devolución documentados (transferencia con concepto, acuerdo interno/acta, registro en cuentas por pagar al socio) y no registrarlo como ingreso ni como gasto. Si se pactaran **intereses**, esos sí serían una contraprestación (renta) a valor de mercado | — |

**Implicación ERP:** si TILMUX le compra el Mini normal al usuario (socio/gerente = parte vinculada), el precio debe ser el de mercado: el comparable es el precio a independientes (p. ej. tienda oficial S/ 279, o su propio precio de venta S/ 394, según el comparable más adecuado). El ERP debe guardar el comparable (captura de precio oficial / listing) como sustento, no solo el precio pactado. **No verificado:** si TILMUX, por su tamaño, está obligado a Declaración Jurada Informativa Reporte Local / Reporte Maestro / Estudio Técnico de PT. No afirmar que debe presentarlos ni que está exento.

### 5.7 Checklist normativo que el ERP debe cumplir

1. **Estados SIRE separados:** propuesta (día 2) → preliminar (día 8) → generado + constancia. Aceptar ≠ generar. Fechas oct-2026 para RUC …1: SIRE 16 nov, 621 17 nov.
2. **Clasificador por tipo de comprobante:** 01 → 107/108 (si IGV discriminado y destino gravado); 03/02/04/05/12/13 y demás no gravados → 120 (o 113/119/122 según corresponda); nunca 03 → 107/108.
3. **Complementar, no Reemplazar, para boletas** y demás documentos complementables (Anexo 8). Reemplazar solo para registro completo o no complementables (Anexo 11).
4. **Redondeo solo en deuda:** libros y RCE con 2 decimales; deuda 621 en enteros (RS 025-2000). Guardar el redondeo como campo auditable.
5. **Tasa 18% total;** no hardcodear 16%+2% para el desglose 2026 (Ley 32387: 15,5%+2,5%).
6. **Renta RER = 1,5% × 301**, sin coeficiente ni PDT 625. Saldos a favor 145/303 por tributo y por separado.
7. **Bancarización:** alerta si obligación ≥ S/ 2 000 / US$ 500 y medio de pago no bancario; evaluar el total de la obligación, no cada parcial.
8. **Acumulados RER:** ingresos y adquisiciones anuales vs S/ 525 000; activos fijos vs S/ 126 000; personal vs 10/turno.
9. **Vinculadas:** si se compra al socio, precio a valor de mercado con comparable guardado (art. 32/32-A); la restitución del préstamo (mismo importe, sin intereses) no es venta — documentarla como préstamo/devolución, no como ingreso/gasto.
10. **No ofrecer liquidación de compra** para electrónica ni para vendedor con RUC.
11. **Alertas, no prórrogas:** la facultad discrecional hasta 28 feb 2027 no mueve los vencimientos en la UI.

### 5.8 No verificado (queda abierto, no inventar)

- El desglose interno (OP gravada / IGV / exonerada) de B001-00393302; leer su XML/PDF antes de cerrar 120 = 241,04.
- El tipo de comprobante exacto de los 3 documentos bancarios del CSV (FB29/FN01/FV20).
- La vía correcta para que TILMUX adquiera el Starlink Mini normal a una persona natural con RUC 10.
- Umbrales y obligaciones formales de precios de transferencia (Reporte Local/Maestro/Estudio Técnico) para TILMUX.
- Si Yape/Plin cuentan como medio de pago del art. 5 Ley 28194 entre privados.
- La causa del «No items found» en SIRE el 9 nov 21:55 (requiere revisión en vivo en SOL).
- La fecha de afiliación/obligación SIRE exacta de TILMUX y si es Buen Contribuyente (cambiaría las fechas a 23/24 nov).
- Arts. 18–19 Ley IGV verificados vía análisis secundarios concordantes, texto oficial del TUO no abierto en esa sesión.

---

## 6. Documentación vigente del stack (09/11/2026)

| Tecnología | En repo | Vigente nov 2026 | Riesgo | Recomendación |
|---|---|---|---|---|
| Django | `>=6.1,<6.2`, lock **6.1.3** | **6.1.3** (03/11/2026), serie lanzada 05/08/2026. **No es LTS.** Mainstream hasta abr 2027, extendido hasta dic 2027. Próxima LTS: **6.2, abr 2027–abr 2030** | Bajo hoy (patch al día); medio a 5 meses vista | Mantener 6.1.3 con cada patch; saltar a **6.2 LTS en abr–jun 2027**. Desde 2028 Django pasa a ciclo anual y se retira la etiqueta LTS |
| PostgreSQL | `postgres:17` (sin minor) en CI/backup/restore; **versión de producción en Render no está en el repo** | Mayor vigente **18.6** (13/08/2026, EOL 14/11/2030). **17.11** minor vigente (EOL 08/11/2029). PG 19 en RC1 (15/10/2026), GA prevista 19/11/2026 | Bajo (17 soportada hasta 2029). Riesgo real: no saber qué corre en Render | Seguir en **17** (no saltar a 18 ni a 19.0 recién lanzado). Fijar `postgres:17.11`; anotar versión/plan del Postgres de Render; evaluar 18 en 2027, no 19.0 recién lanzado |
| Render | Docker, plan free, virginia, `/salud/`, `autoDeploy: true`, sin `preDeployCommand` | `preDeployCommand` solo en planes de pago; en Free la doc indica migraciones en el build command. Existe `autoDeployTrigger: checksPass` | **Alto si hay datos de producción: Postgres Free caduca a los 30 días** (+14 días de gracia, luego se borra con los datos), 1 GB, sin backups. Web Free se duerme a los 15 min sin tráfico. Render: «Do not use them for production applications» | Pasar web a paga desde **$7/mes** y Postgres paga desde **$6/mes** (o DB externa). Entonces mover `migrate` a `preDeployCommand` y quitarlo del entrypoint; poner `autoDeployTrigger: checksPass` + branch protection. Si se queda en Free, documentar que es solo demo y que la DB expira |
| GitHub Actions | `tests.yml` solo push main + manual, sin ruff, sin caché uv, uv por `curl install.sh` sin fijar versión, `checkout@v4`, `upload-artifact@v4`, `ubuntu-latest` sin fijar, `uv sync` sin `--frozen` | Best practice: `on: [push, pull_request]`, `astral-sh/setup-uv` con caché, servicio postgres con `pg_isready`, `uv sync --frozen`, ruff antes de tests. Node 20 deprecado (forzado a Node 24 el 16/06/2026, eliminado 16/09/2026) | **Medio-alto:** un PR puede mergearse sin tests ni lint; acciones v4 corren sobre Node 20 deprecado | Añadir `pull_request:` a `tests.yml`; añadir job/paso `ruff check .` y `ruff format --check .`; usar `astral-sh/setup-uv` con `enable-cache: true` y `cache-dependency-glob: uv.lock`; `uv sync --frozen`; subir `checkout` y `upload-artifact` a sus majors vigentes; fijar `ubuntu-24.04`; activar branch protection exigiendo los checks |
| uv | Sin fijar (Dockerfile `pip install uv`, CI `curl install.sh`); lock revision 3, `requires-python >=3.14`, sin `required-version`, sin `.python-version` | **0.13.7** (03/11/2026); 0.13.4/0.13.5 retiraron una raíz eMudhra comprometida e incluyeron parches de seguridad de CPython | Medio-bajo: builds no reproducibles | Fijar uv, crear `.python-version` con `3.14` |
| ruff | Dev `>=0.17.3`, lock **0.17.3**; line-length 120, `select = ["E","F","I","UP","B"]`; sin `exclude`, sin config de formato; **CI nunca ejecuta ruff** | **0.17.4** (05/11/2026); default line-length 88 | Bajo (1 patch atrás); riesgo de proceso: el lint existe pero nadie lo corre; migraciones linteadas como código propio | Subir a 0.17.4; ruff check + format en CI; excluir `*/migrations/*` |
| Python | `FROM python:3.14-slim` (sin patch), `requires-python >=3.14` (sin cota superior) | 3.14 vigente; 3.15 ya existe; Django 6.1.3 añadió soporte de Python 3.15 | Bajo-medio: `>=3.14` sin techo permitiría 3.15/3.16 sin probar | Fijar patch o digest; cota `<3.16`; `.python-version` |
| psycopg / resto | `psycopg[binary]>=3.2`, lock **3.3.8**; gunicorn 26.2.0, whitenoise 6.12.0, openpyxl 3.1.5, waitress 3.0.2, reportlab 5.1.0 | psycopg 3.3.8 reciente; últimas exactas de gunicorn/whitenoise/etc. **no verificadas** una por una | Bajo. `waitress` está en dependencias pero el arranque usa gunicorn: valorar eliminarla | — |

Hallazgos del stack no pedidos pero relevantes:
- **Migraciones al arrancar** (`docker-entrypoint.sh`): opción documentada para plan Free, pero retrasa la primera respuesta al health check y con >1 réplica dos instancias migrarían a la vez (hoy 1 instancia, riesgo latente). Un rollback de Render revierte código, no la DB.
- **Django 6.1:** abandona PostgreSQL 14 (mínimo PG 15; PG 14 llega a EOL el 12/11/2026), abandona MySQL < 8.4, Python 3.12–3.15, deprecado `email_backend` de `AdminEmailHandler`, `BitAnd/BitOr/BitXor` de `contrib.postgres` deprecados.
- **PG 17 para backup/restore:** backups incrementales son de `pg_basebackup`, no de `pg_dump`; dump paralelo `-j` solo con formato directorio (`-Fd`), no con el `-Fc` que usa `backup.yml`; `pg_dump` con `--enable-row-security` respeta RLS. El restore usa `-O -x --exit-on-error`, buena práctica.
- **Backup en Artifacts no es un almacén de respaldos:** retención 30 días, descarga manual, sin alerta si el dump sale vacío. Mitigado en parte por `verificar-restauracion.yml` semanal (buena práctica, mantener).
- **`tipo-cambio.yml`** escribe directo a producción desde CI sin `concurrency:` que evite ejecuciones solapadas.

**Prioridades del stack (orden):** 1) Aclarar el Postgres de producción en Render (plan y versión; si es Free, migrar a pago antes de los 30 días). 2) Añadir `pull_request` + ruff a `tests.yml` y branch protection. 3) Subir a plan pago en Render y mover migraciones a `preDeployCommand`; quitar `migrate` del entrypoint. 4) Fijar versiones: uv, `checkout`/`upload-artifact`, `postgres:17.11`, patch de `python:3.14`. 5) Respaldos fuera de Artifacts y `concurrency:` en `tipo-cambio.yml`. 6) Plan de salto a Django 6.2 LTS (abr–jun 2027).

---

## 7. Qué se verificó como ya corregido (Fase 1, 2026-11-05)

Asiento 37 anulado (duplicado pago FV20), asiento 38 reclasificado (provisión S/ 10 de `1061` a `4212`), asiento 33 con fecha corregida a 31/10, FV20 corregida a `FV20-01490476`, modelo de provisión (`provision`, `gasto_origen`, `estado`, `fecha_devengado`), exclusión de provisiones del registro de compras y del 621, flujo de pago de IGV (`pagar_igv`), correlativo de serie atómico al confirmar, glosas vinculadas en `corregir`, atomicidad de alta/confirmación de compras y ventas, clasificación de saldos deudores del elemento 4 en EEFF, corrección del CSV que duplicaba la base no gravada, manejo de separadores mixtos en SIRE y fecha de anotación tributaria opcional.

---

## 8. Re-verificación de los archivos pendientes del 429 (cerrado en v2)

Método v2: 17 archivos descargados vía GitHub (`get_file_contents`, pausa de 7 s entre llamadas). **Cero errores 429 en toda la ronda.** No se modificó código. HEAD sigue en `70271c79`, sin commits nuevos. **Ramas: NO VERIFICADO** — `list_branches` está clasificado como `mcp.write` y no se usó la vía de escritura. No se puede confirmar si existe otra rama además de `main`.

Archivos cerrados en v2 (resumen; detalle en §3 y §6): `inventario/servicios.py` (166 líneas, PEPS real, promedio en L139), `compras/reversion.py` (152 líneas, corrección interna sólida), `compras/comprobantes.py` (58 líneas), `compras/liquidacion.py` (144 líneas, reglas del manual en código), `config/settings.py` (196 líneas, sin RLS), `core/models.py` (165 líneas, fallback TC confirmado L98-103), `core/views.py` (425 líneas, filtros por empresa consistentes), `Dockerfile`, `docker-entrypoint.sh`, `docs/despliegue.md`, `render.yaml`, `tests.yml`, y tests muestreados (68 métodos en 6 archivos).

---

## 9. Qué falta y qué se necesita del usuario

| Hallazgo | Documento / constancia / decisión necesaria |
|---|---|
| P0-8 PDT octubre | **Urgente (vence 17/11):** RCE octubre definitivo y RVIE octubre definitivo (constancias de recepción), para declarar. Sin ellos no se fija la 184. El usuario confirmó el 09/11 que aún no declaró el PDT 621 de octubre |
| P0-5 IGV octubre | Comprobante de pago del IGV cuando se pague (fecha, cuenta, importe exacto). El usuario confirmó el 09/11 que aún no pagó el IGV |
| P0-7 Boleta B001-00393302 | Confirmar cuando la incorpore manualmente en el RCE de octubre (Complementar propuesta) y enviar el RCE definitivo generado después, para ver si figura y con qué total |
| P0-6 / P0-3 S/ 500 | Hacer la transferencia cuando Mercado Pago deposite; enviar el voucher (fecha/hora, cuenta de origen, N° de operación, S/ 500,00) y **corregir EXP-002 a PENDIENTE hasta entonces**. El usuario confirmó el 09/11 que la hará cuando Mercado Pago transfiera |
| P0-6 / P0-3 S/ 39 | Hacer el reembolso cuando Mercado Pago deposite; enviar el voucher; **aclarar beneficiario: Gerente General (según EXP-003) o padre (según registro anterior)** |
| P0-1 / stack | Log de `Actions → Tests` en `70271c` (¿verde? ¿`Ran N tests`?); decisión de añadir `pull_request` (+ ruff) a la CI; **aclarar plan y versión del Postgres de producción en Render (¿Free? Si es Free, migrar a pago antes de los 30 días)**; falta un log de despliegue mostrando `migrate` al arrancar |
| P0-2 Nota proveedor | NC de proveedor real + voucher de reembolso + RCE del mes |
| P0-4 FX | Un caso real documentado (factura USD con TC de emisión y de pago) y criterio de TC cuando SUNAT no publica |
| P1-7 / P1-5 | Extractos BBVA/BCP a fecha de corte, incluido noviembre con el débito de S/ 10 por envío de estado de cuenta; un caso real de cobro histórico no vinculado |
| P1-8 Respaldos | Log de la ejecución 42724851652 o nueva ejecución manual, más prueba de arranque de la app contra la BD restaurada |
| Docs | EXP-001 y EXP-003 completos y firmados (nombres, DNI, partida, fecha real de firma); EXP-002 corregido a PENDIENTE y completado con el voucher cuando se pague |
| Decisión | Para cada «todavía no» (FX, nota de proveedor, mixto, detracciones/retenciones): ¿se implementa, se mantiene bloqueado, o se documenta como limitación permanente? |

---

## 10. Limitaciones de esta auditoría consolidada

1. **Ramas no verificadas:** `list_branches` es vía de escritura; no se usó. Solo se confirma `main` y su HEAD.
2. **Tests locales no ejecutados:** sin PostgreSQL, uv, psql ni docker en esta VM, y el repo privado no se puede clonar sin credenciales. No se verificó el conteo de pruebas en el HEAD ni que la suite pase en `70271c79`. Las cifras 73/96/304 siguen siendo afirmaciones documentales de fechas y bases distintas.
3. **Sin ejecución de la app ni de la suite; sin acceso a la base real ni a SUNAT en vivo.** Las cifras de saldos y asientos siguen siendo las documentadas en `docs/auditoria.md` (5–9/11) y pueden haber cambiado.
4. **Log de restauración 42724851652 y log de despliegue de Render no verificados.**
5. **Normativa:** arts. 18–19 Ley IGV verificados vía análisis secundarios concordantes, texto oficial del TUO no abierto en esa sesión; causa del «No items found» en SIRE requiere revisión en vivo en SOL; umbrales formales de precios de transferencia y si Yape/Plin es medio de pago del art. 5, no verificados.
6. **Versiones exactas nov 2026** de `actions/checkout`, `setup-uv`, `upload-artifact`, gunicorn, whitenoise y demás paquetes secundarios no verificadas contra su fuente primaria.
7. **Migraciones no revisadas en v2:** no se puede descartar RLS a nivel BD solo con el código de la app; la migración `0012_declaracionigv621.py` (RLS `REVOKE ALL … FROM PUBLIC, anon, authenticated`) es la única pista de RLS y no se releyó en v2.
8. **Pantallas/flujos en vivo no verificados:** templates y tests de filtros siguen sin verificación en vivo. Es laguna de verificación, no bug demostrado.

---

## 11. Instrucciones para el agente que implemente los P0 (para DeepSeek Harness / OpenCode)

> Eres el agente de desarrollo del ERP TILMUX. Vas a continuar un proyecto existente, no a construirlo desde cero.
> Lee `docs/continuacion.md`, `docs/auditoria.md`, `docs/manual.md` y este documento consolidado antes de tocar código. No asumas que el ERP ni una IA anterior tienen siempre la razón.
> Trabaja en rama, nunca directo en `main`. `main` tiene despliegue automático en Render. Haz un P0 a la vez, con tests que cubran el comportamiento y las regresiones relevantes.
> Reglas duras: no registres pagos, declaraciones, restituciones ni movimientos no verificados con voucher/constancia; no alteres datos históricos para que los reportes cuadren; no generes asientos de redondeo sin sustento — el redondeo a enteros (RS 025-2000) es un campo auditable, no un asiento; no hagas pruebas destructivas ni cargas de datos en la base real, usa PostgreSQL aislado y revisa las migraciones antes de aplicarlas; no subas contraseñas, tokens, DNI ni datos bancarios al repo ni al chat.
> Orden: (1) CI en PR + freno a autoDeploy, (2) nota de proveedor con salida PEPS por capa original, (3) restitución 4411/4419 con voucher obligatorio, (4) saldo en moneda original + TC sin fallback silencioso, (5) deuda final de IGV contra constancia con campo vigente y redondeo auditable + estados SIRE separados + alerta de vencimiento, (6) Complementar propuesta RCE para la boleta tipo 03.
> Datos que no debes inventar ni dar por pagados: IGV octubre S/ 105 en enteros / 105,38 en libros, sin pagar; PDT octubre sin declarar, vence 17/11/2026; SIRE octubre sin generar, vence 16/11/2026; S/ 500 NO restituido (EXP-002 dice lo contrario y es falso); S/ 39 NO reembolsado, beneficiario sin aclarar (Gerente General vs padre); boleta B001-00393302 S/ 198,04 no está en la propuesta por diseño (tipo 03, Tabla 11 RS 040-2022), va por Complementar a casilla 120, sin crédito fiscal.
> Al final de cada bloque reporta qué cambió, cómo lo probaste, qué falta, y qué información/documento necesitas del usuario.

---

## 12. Conclusión

La auditoría consolidada no cambia el diagnóstico de fondo de v1, lo endurece en tres puntos y lo precisa en los números: el ERP sigue ordenado en lo formal (balanza cuadrada, Fase 1 aplicada, reversión y liquidación verificadas como sólidas en código), pero **no es seguro declarar ni operar sobre él sin resolver los 8 P0**. Los tres nuevos no son adornos: el P0-6 es un expediente que afirma un pago falso, el P0-7 es la confusión entre propuesta y registro generado que ya está bloqueando octubre, y el P0-8 es un vencimiento a días con la caja dependiendo de Mercado Pago. A eso se suma un riesgo del stack que la v1 no había cuantificado: **si el Postgres de producción en Render es plan Free, los datos caducan a los 30 días** — hay que aclararlo antes que cualquier P0 de código. La prioridad inmediata, antes de escribir una línea de código, es tributaria y documental: generar el RCE/RVIE de octubre (con la boleta complementada), declarar el PDT 621 el 17/11, pagar los S/ 105, corregir EXP-002 a PENDIENTE y hacer las restituciones con voucher cuando llegue el depósito de Mercado Pago. **Nada de esto se implementó en esta auditoría, por instrucción expresa del usuario: solo auditoría, sin rama ni PR.**

*Fuentes internas: `docs/continuacion.md` (9/11/2026), `docs/auditoria.md` (5/11/2026, §17 6/11/2026), `docs/manual.md`, `README.md`, `render.yaml`, `Dockerfile`, `docker-entrypoint.sh`, `docs/despliegue.md`, `.github/workflows/*.yml`, `pyproject.toml`, código citado en `main` en el commit `70271c79`, archivos subidos por el usuario (constancias PDT setiembre, RCE/RVIE setiembre y octubre, CSV propuesta RCE octubre, EXP-001/002/003) y los tres informes de trabajo de v2. Normativa SUNAT y documentación del stack citadas con URL y fecha en §5 y §6; donde una norma no se pudo verificar en fuente oficial, queda marcado como no verificado. Este documento reemplaza a `tilmux-erp-auditoria-2026-11-10.md` (v1) y a `tilmux-erp-auditoria-2026-11-10-v2.md` (v2) como referencia única.*

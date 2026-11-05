# Manual de uso

## Entrar

Doble clic en **Tilmux ERP** del escritorio. Abre `http://127.0.0.1:8000`.

## Apagar

Tienes tres formas, de la más simple a la más manual:

1. **Doble clic en «Detener Tilmux ERP»** del escritorio. Es lo recomendado.
2. Cerrar la ventana negra del servidor.
3. `Ctrl+C` en esa ventana.

Mientras está encendido ocupa unos **120 MB de RAM**. Al apagarlo no queda nada
corriendo y los datos siguen intactos en Supabase.

Para comprobar que está apagado, vuelve a abrir «Detener»: si dice *«El servidor
no está corriendo»*, está limpio.

## Orden de trabajo

1. Catálogos (una sola vez).
2. Compras.
3. Ventas.
4. Cobros y pagos.
5. Cierre del mes.

**Constitución y aportes.** El capital suscrito se registra cuando se suscribe:
si la escritura de constitución es anterior al inicio de actividades, la
suscripción se registra al activar el RUC. Los aportes en efectivo se registran
cuando entran al banco y cancelan la cuenta 1421.

## Catálogos

En **Configuración** (el admin) se cargan productos, proveedores, clientes,
unidades, series y cuentas de tesorería. Las cuentas contables ya están cargadas:
1 636 del PCGE 2026, con 44 activas.

## Compras

**Compras → Nueva compra.** Escribes la factura del proveedor, agregas las líneas
(con su descripción) y, si hubo flete o aduana, los costos de internamiento. Se
prorratean por valor y el costo unitario final los incluye.

Si no sabes si el precio incluye IGV, usa el interruptor **Los precios incluyen
IGV**; el sistema separa base e impuesto.

Si la factura todavía no llega, marca **La factura aún no llega; guardar como
pendiente de factura**. La compra queda en estado **Pendiente**, no mueve stock
ni contabilidad y aparece en **Pendientes** hasta que completes RUC, serie y
número. Mientras esté pendiente no entra al PDT 621.

**Editar.** Mientras la compra esté en borrador o pendiente, el detalle tiene
**Editar**: puedes cambiar cabecera, descripciones, cantidades, precios y costos.

Al confirmar: se crean las capas de stock y el asiento por pagar. Una compra con
crédito fiscal no se confirma sin RUC, serie y número.

**Corregir datos.** En una compra confirmada puedes completar serie, número,
tipo, glosa y descripciones desde **Corregir datos**. Los importes, la fecha y el
RUC no se editan en una compra confirmada: si están mal, usa una nota de crédito
del proveedor o **Anular compra** (solo si no tiene pagos ni stock consumido).

**Compras → Importar XML.** Subes el XML de SUNAT y el sistema extrae RUC, serie,
número, base, IGV y total. Confirma como gasto o como mercadería.

Regla: una **factura** separa base e IGV; una **boleta** no otorga crédito y su
IGV forma parte del costo.

## Pendientes

En **Pendientes** (y en el panel) aparecen los comprobantes que necesitan algo:
borradores sin confirmar, compras pendientes de factura y compras confirmadas a
las que les falta RUC, serie o número. Cada fila tiene **Completar** y lleva al
formulario que corresponde.

## Pagar una compra

En el detalle de la compra confirmada, **Pagar compra**. Puedes pagar todo o una
parte: el sistema muestra el saldo y lo descuenta con cada pago. La compra queda
como pagada cuando el saldo llega a cero.

Si la compra es en dólares y pagas con otro tipo de cambio, la diferencia se
reconoce en la 6761 o 7761, proporcional a la parte pagada.

## Usuarios y roles

En **Configuración → Perfiles** se asigna a cada usuario un rol:

| Rol | Puede |
|---|---|
| Administrador | Todo |
| Registrador | Registrar y confirmar documentos |
| Solo lectura | Consultar reportes, sin registrar |

Un usuario sin perfil se trata como administrador.

## Ventas

**Ventas → Nueva venta.** Eliges boleta o factura, el cliente y las líneas. El
panel derecho muestra el asiento que se generará.

Mientras la venta esté en borrador, el detalle tiene **Editar** para corregir
descripciones, cantidades o precios. Una venta confirmada no se edita: se corrige
con nota de crédito o débito, que es lo que exige SUNAT.

Al confirmar: descuenta stock por PEPS, calcula el costo real y registra el cobro.

Una factura exige RUC. Una boleta mayor a S/ 700 exige identificar al comprador.

## Notas

En el detalle de una venta confirmada:

- **Nota de crédito**: total o por ítem. Devuelve el stock al costo original.
- **Nota de débito**: intereses o penalidades. Aumenta la cuenta por cobrar.

Cada nota modifica un solo comprobante y usa los catálogos 09 y 10 de SUNAT.

## Reportes

| Reporte | Qué muestra |
|---|---|
| Balance de comprobación | Debe, haber y saldos por cuenta |
| Libro mayor | Movimientos con saldo corrido |
| Registro de ventas | Ventas y notas, con exportación CSV |
| Registro de compras | Compras y gastos, con exportación CSV |
| IGV y RER | IGV del mes y renta del 1,5 % |
| Estados financieros | Situación, resultados, cambios y flujo |
| Conciliación SUNAT | Casillas contra la vista preliminar o contra la propuesta del SIRE |

## Impuestos

**IGV y RER.** El reporte calcula el IGV del mes y la renta del 1,5 %. En el
panel, **IGV por pagar** muestra el saldo real de la cuenta 40111. En
**Impuestos**, el KPI y la tabla **PDT 621** muestran lo que se declara: el 140
es el IGV del mes, el 145 el saldo a favor anterior y el 184 lo que resulta
(140 - 145). Si el libro y el 621 no coinciden, revisa si quedó una declaración
anterior sin pagar.

La tarjeta **Renta RER por pagar** muestra el saldo de la 40171, es decir, la
renta de meses anteriores que aún no se paga.

### PDT 621

La tabla del reporte **IGV y RER** sigue las casillas del formulario:

| Casilla | Qué es |
|---|---|
| 100 / 101 | Ventas netas gravadas y su IGV |
| 102 / 103 | Descuentos y devoluciones de ventas de periodos anteriores |
| 107 / 108 | Compras netas gravadas y su IGV |
| 120 | Compras no gravadas |
| 140 | IGV resultante |
| 145 | Saldo a favor del periodo anterior |
| 184 | IGV a pagar o saldo a favor |
| 301 / 312 | Ingresos netos y renta RER (1,5 %) |
| 303 / 304 | Saldo a favor anterior y renta a pagar |

En el detalle de cada compra o venta hay una tarjeta **PDT 621** con las casillas
que aporta ese comprobante. Una compra sin RUC, serie o número no suma en
107/108. Una boleta de compra no otorga crédito. Una compra pendiente de factura
no entra al 621 hasta completarse.

Cuando hay renta y todavía no está asentada, el botón **Asentar renta de
MM/AAAA** crea el asiento 881 contra 40171. Al cerrar el mes se hace solo. Para
pagarla, usa **Registrar pago**: debita la 40171 y registra la salida del banco.
Si el mes no tiene ventas, la renta del mes es cero, pero el saldo por pagar de
los meses anteriores sigue visible.

## Cierre del mes

**Periodos**. Antes de cerrar:

1. **Revaluar**: ajusta los saldos en dólares al tipo de cambio de fin de mes.
2. **Cerrar**: bloquea el mes. No deben quedar borradores.

Un periodo cerrado rechaza asientos nuevos. Reabrirlo exige ser administrador.

Si en **Periodos** aparecen meses que no tienen ningún movimiento, se pueden
eliminar sin tocar la contabilidad:

```
python manage.py limpiar_periodos --si
```

## Cierre anual

Después de cerrar diciembre, en **Periodos → Cierre anual** verás el ejercicio
con sus ingresos, gastos y resultado. El botón **Cerrar 2026** genera dos
asientos al 31 de diciembre:

1. Las cuentas de ingreso (7) se debitan y las de gasto (6 y 8) se acreditan;
   la diferencia va a la cuenta 89.
2. El saldo de la 89 pasa a resultados acumulados: 591 si hubo utilidad o 592
   si hubo pérdida.

No se puede cerrar si queda un mes abierto o un comprobante en borrador. Para
corregir algo después, **Revertir cierre** (solo administrador), reabre
diciembre, ajusta y vuelve a cerrar. El estado de resultados sigue mostrando el
resultado del año: el asiento de cierre no se cuenta dos veces.

También se puede hacer por consola:

```
python manage.py cerrar_anio --anio 2026
python manage.py cerrar_anio --anio 2026 --revertir
```


## Tipo de cambio

Se descarga solo todos los días a las 00:01 desde SUNAT y se guarda por fecha.
También se puede ejecutar a mano:

```
python manage.py actualizar_tipo_cambio
```

## Respaldo

Todos los días a las 06:00 un proceso de GitHub vuelca la base y guarda el
archivo 30 días. Cada lunes se restaura en una base limpia y se comprueba que los
saldos coincidan; si no, el proceso falla y avisa.

## Conciliación con SUNAT

Cada mes, descarga la vista preliminar del SIRE y ejecuta:

```
python manage.py verificar_sunat --anio 2026 --mes 9
```

Compara casilla por casilla: 107 base de compras, 108 IGV, 120 no gravado, 140
saldo. Si algo no cuadra, se ve antes de declarar.

### Conciliar con la propuesta del SIRE

En **Reportes → Conciliación SUNAT → Conciliar con la propuesta del SIRE**
puedes subir el archivo que descarga SUNAT en lugar de copiar las casillas a mano.

1. En SUNAT, abre **SIRE** y elige **RVIE** (ventas) o **RCE** (compras).
2. Descarga la propuesta en Excel o CSV.
3. En el ERP elige año, mes y registro, adjunta el archivo y pulsa **Conciliar**.

El lector busca las columnas por su nombre (base imponible, IGV, importe total),
así que no depende del orden ni de que SUNAT cambie la plantilla. Las notas de
crédito se restan solas porque la estructura del RVIE las exige con signo
negativo; si afectan a un periodo anterior, vienen en las columnas de descuento
y también se restan. La fila de totales se ignora para no contar dos veces.

El resultado muestra base, IGV y total del sistema y de SUNAT, con la
diferencia (sistema menos SUNAT). Una diferencia positiva significa que el ERP
tiene más que la propuesta: revisa si esos comprobantes están en el RCE o si
están duplicados. Una negativa, que SUNAT tiene un comprobante que el ERP no
registró.

El archivo no se guarda ni se envía a SUNAT: se lee en el equipo y se descarta.


## Normativa aplicada

Estas son las normas que usa el ERP y que conviene tener a mano:

| Tema | Norma | Qué implica en el sistema |
|---|---|---|
| Plan de cuentas | Resolución CNC N° 002-2026-EF/30 | PCGE 2026 aplicado anticipadamente; su vigencia obligatoria es el 1/1/2028, pero la norma permite adelantarlo |
| Estados financieros | Resolución CNC N° 001-2024-EF/30 (NPIF) | Vigente desde el 1/1/2025 para microempresas (hasta 150 UIT de ingresos anuales: S/ 825 000 en 2026): situación financiera, resultados, cambios en el patrimonio, flujo de efectivo y notas |
| Renta | Ley del Impuesto a la Renta, capítulo XV | RER: 1,5 % de los ingresos netos mensuales; sin declaración anual |
| Límites del RER | SUNAT | Ingresos o compras hasta S/ 525 000 al año, activos fijos hasta S/ 126 000 y máximo 10 trabajadores por turno |
| IGV | TUO de la Ley del IGV, artículos 18 y 19 | 18 % (16 % IGV + 2 % IPM); el crédito fiscal exige factura y destino a operaciones gravadas |
| Boletas | Reglamento de Comprobantes de Pago | No otorgan crédito fiscal ni sustentan gasto o costo |
| Registros electrónicos | Resolución de Superintendencia N° 000040-2022/SUNAT | RVIE y RCE se llevan en el SIRE; el ERP solo lee la propuesta descargada |

El ERP **no envía nada a SUNAT**. Solo descarga el tipo de cambio y lee archivos
que tú descargas de SUNAT.

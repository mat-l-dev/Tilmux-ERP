# Manual de uso

También puedes abrir **Guía de uso** en el menú del ERP. Allí encontrarás
ejemplos paso a paso para compras, gastos, ventas, cobros y conciliación SIRE.

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

En el **Panel**, el saldo contable de las cuentas 101, 1031 y 1061 se calcula
hasta el último día del mes elegido; no es un saldo bancario conciliado. Las
ventas del mes, el gráfico y el comparativo muestran bases sin IGV y consideran
las notas de crédito y débito en el mes de emisión. Son cifras calculadas con
los registros del ERP y deben contrastarse con los comprobantes y el SIRE.

## Catálogos

En **Configuración** (el admin) se cargan productos, proveedores, clientes,
unidades, series y cuentas de tesorería. El catálogo contable incluye las
cuentas del PCGE 2026; las usadas habitualmente se activan en la configuración inicial.

Un usuario con un perfil asignado a una empresa solo puede seleccionarla en el
ERP; si está inactiva, no se cambia a otra automáticamente. Los superusuarios
pueden seleccionar cualquier empresa activa. Un usuario sin perfil, sin empresa
asignada o con empresa inactiva debe solicitar su asignación al administrador
antes de acceder a operaciones. La administración de Django está reservada a
superusuarios; los catálogos siguen siendo compartidos entre empresas.

## Compras

La lista de **Compras** reúne mercadería, gastos y provisiones. Usa **Tipo**
para filtrar y busca por proveedor, comprobante o concepto. Al abrir un gasto
puedes consultar sus importes, cuenta, asiento, movimientos de tesorería y
provisiones vinculadas cuando existan. Las provisiones se identifican por
separado para no confundirlas con facturas adicionales.

**Compras → Nueva compra.** Escribes la factura del proveedor, agregas las líneas
(con su descripción) y, si hubo flete o aduana, los costos de internamiento. Se
prorratean por valor y el costo unitario final los incluye.
Cuando la compra no usa crédito fiscal, el IGV de los costos adicionales se
incorpora al costo del inventario. El reparto conserva los céntimos del costo
total y no asigna importes negativos a las líneas. Revisa si cada costo es
atribuible a la mercadería antes de registrarlo.

En el listado de compras y gastos puedes consultar por fecha de emisión,
devengo del gasto o anotación tributaria. Si no hay fecha de devengo o anotación
se usa la emisión y se indica en la fila; en mercadería el criterio de devengo
muestra la fecha de emisión. La anotación estimada debe contrastarse con el RCE.

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

Una compra confirmada registrada por error puede revertirse desde su detalle,
con motivo y confirmación explícita, solo si no tiene pagos, revaluaciones,
stock consumido ni períodos cerrados posteriores, y si sus capas y asiento
coinciden. Se conserva el historial y se genera un asiento inverso. Esta acción
es una corrección interna: no acredita una baja ante SUNAT ni registra una nota
de crédito o una devolución del proveedor; esos casos requieren otro flujo. La
corrección de datos tampoco se permite si afecta un período cerrado.

Al importar un XML, se comprueba el RUC receptor frente a la empresa elegida.
La importación de gastos registra un pago completo en soles en la fecha del
comprobante solo si lo confirmas; la inclusión tributaria y la deducibilidad
se marcan tras revisar el caso. No se procesan notas, ajustes de totales ni
gastos en moneda extranjera por este flujo. El XML no se conserva y su lectura
no verifica su validez ante SUNAT.

Al registrar un gasto, el sistema exige base y total positivos e IGV no negativo,
comprueba que la cuenta de gasto esté habilitada y que el medio de pago
sea una cuenta activa en soles de la empresa con cuenta contable vinculada.

**Registrar gasto pagado.** Desde la lista de compras puedes registrar comisiones
y otros gastos pagados en soles cuando la fecha del documento y la del pago
coinciden. El registro crea el gasto, el asiento y la salida de tesorería en una
misma operación. Indica la cuenta y el canal real del pago; también se solicita
al registrar un gasto pagado desde XML. Si marcas su inclusión tributaria, el sistema considera todo
el IGV como crédito o, si no tiene IGV, el valor como compra no gravada; revisa
primero que corresponda.

**Registrar gasto por pagar.** Si tienes la factura o boleta pero aún no la has
pagado, registra el comprobante en soles con este botón. La fecha del gasto y la
del comprobante deben coincidir. En su detalle verás el saldo y podrás registrar
uno o varios pagos, cada uno con su fecha real y cuenta. Cuando el saldo llega a
cero, el gasto figura como pagado. Si ya registraste provisiones del mismo
proveedor, puedes seleccionarlas cuando no haya IGV y sumen exactamente el
comprobante. Para una factura con IGV y crédito fiscal, puedes vincular una sola
provisión por su base exacta y confirmar que corresponde a ella. El sistema
verifica el respaldo, evita repetir el gasto y permite pagos posteriores. Otros
casos con IGV, importes diferentes o sin respaldo verificable requieren revisión.

Para proteger el costo PEPS, no se puede ingresar una entrada o salida con fecha
anterior a una salida ya registrada del mismo producto. Si necesitas corregir
un movimiento anterior, revisa el historial y los costos antes de proceder; el
sistema todavía no recalcula automáticamente esas operaciones.

En **Reportes → Inventario** aparecen también los productos agotados con
movimientos; abre su SKU para consultar el kardex. Si la cantidad disponible en
capas difiere del saldo de entradas y salidas, la pantalla muestra una alerta
para investigar el historial. Esta comparación no modifica los datos.

El sistema comprueba proveedor, tipo, serie y número antes de confirmar una
compra o registrar un gasto. Si el comprobante ya está registrado, incluso con
ceros iniciales distintos, muestra un aviso. Las provisiones no se consideran
facturas recibidas. Actualmente un comprobante mixto no puede dividirse entre
una compra de mercadería y un gasto separado; ese caso requiere revisión.

**Corregir datos.** En una compra confirmada puedes completar serie, número,
tipo, glosa y descripciones desde **Corregir datos**. Los importes, la fecha y el
RUC no se editan en una compra confirmada: si están mal, revisa el comprobante
con el proveedor y determina si corresponde corregir un registro interno o
registrar una nota del proveedor; este último flujo aún no está implementado.
Al corregir serie, número o glosa, el sistema actualiza también la glosa del
asiento y del movimiento de tesorería vinculados.

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

Si la compra es en moneda extranjera, solo se permite el pago completo desde
una cuenta en soles; la diferencia de cambio se reconoce en la 6761 o 7761.
Los pagos parciales y la revaluación de una deuda con pagos parciales existentes
requieren revisión: el sistema aún no conserva el saldo pendiente en moneda de
origen con el detalle necesario. El importe del formulario es el saldo contable
en soles, que puede diferir de la salida de dinero por el tipo de cambio.
La confirmación o importación de nuevas compras de mercadería en moneda
extranjera está deshabilitada hasta corregir la conversión de sus líneas.

## Provisión de gastos

Una **provisión** reconoce un gasto antes de que llegue la factura. Puedes
consultar las provisiones existentes desde **Compras** y ver sus vínculos con
comprobantes. La administración de compras y gastos es de solo consulta para
evitar cambios directos que no actualicen la contabilidad.

La provisión:

- Debita la cuenta de gasto y acredita la cuenta 4211 por comprobantes aún no recibidos.
- No mueve tesorería: todavía no ha salido dinero.
- No aparece en el registro de compras ni en el PDT 621.

Al registrar un gasto pagado puedes seleccionar las provisiones pendientes del
mismo proveedor. Si suman exactamente el total y tanto ellas como el comprobante
no tienen IGV, el sistema vincula los documentos, reclasifica la deuda a 4212 y la cancela sin volver a
registrar el gasto. Las provisiones históricas registradas en 4212 conservan su asiento original.
Revisa la selección: si no seleccionas provisiones, se
registra un gasto nuevo. Este flujo no admite pagos parciales ni diferencias o IGV. Los
vínculos históricos por sí solos no implican que se haya liquidado la deuda.

Para registrar una obligación por bienes o servicios ya recibidos y aún sin
comprobante, usa **Compras → Registrar gasto devengado**. El formulario admite
soles sin IGV y crea el gasto y la deuda, sin pago ni crédito fiscal. Un segundo
envío de la misma operación no vuelve a registrarla. Al recibir el comprobante,
regístralo como gasto por pagar y selecciona las provisiones correspondientes.
Sin IGV, deben sumar exactamente el total. Para una factura con IGV y crédito
fiscal, se admite una sola provisión por el importe exacto de la base: confirma
que corresponde a esa base y marca la opción de crédito únicamente después de
verificar sus requisitos. El ERP registra el IGV al recibir la factura, sin
repetir el gasto; el pago se registra por separado. Los demás casos con IGV y
provisiones requieren revisión contable antes de registrarse.

**Fecha devengado y anotación.** El devengo identifica el período económico del
gasto. Desde el detalle de una compra confirmada o de un gasto puedes indicar la
fecha de anotación verificada en el RCE: se conserva la fecha de emisión y se
registra el cambio en el historial. El registro y la estimación del 621 usan esa
fecha; si está vacía, estiman el período por la emisión. No se cambian períodos
contables cerrados ni se envía información a SUNAT. Contrasta el resultado con
el RCE y la declaración; el sistema no valida aún el plazo de crédito fiscal.

## Usuarios y roles

En **Configuración → Perfiles** se asigna a cada usuario un rol:

| Rol | Puede |
|---|---|
| Administrador | Todo |
| Registrador | Registrar y confirmar documentos |
| Solo lectura | Consultar reportes, sin registrar |

Un usuario sin perfil o sin empresa activa asignada no puede consultar ni registrar operaciones de una empresa; los superusuarios pueden seleccionar empresas activas.
En **Configuración**, compras, gastos, ventas, notas de crédito, asientos y
movimientos de inventario y tesorería son de solo consulta. Sus registros se
gestionan desde los módulos correspondientes para mantener la contabilidad.
Desde **Tesorería** puedes consultar los movimientos y sus sumas por cuenta,
filtrar el historial y abrir sus páginas. El neto es la suma de movimientos
registrados, no el saldo del banco: puede faltar el saldo inicial o haber
movimientos pendientes de registrar. No mezcla cuentas ni monedas y conviene
verificar la moneda de los registros anteriores.

**Comparar con el banco** busca posibles movimientos por cuenta en soles, tipo,
importe y una ventana de tres días antes o después de la fecha del extracto.
Puede devolver varias coincidencias: revisa el concepto y el sustento. La
búsqueda no cambia datos. Si confirmas una coincidencia, indica la referencia
única real del banco: el vínculo y el usuario quedan en el historial y puedes
revertirlo indicando el motivo. Por ahora solo admite una operación del banco
por movimiento del ERP y cuentas en soles. No importa extractos ni registra
pagos; las marcas anteriores sin referencia deben revisarse por separado.

## Ventas

**Ventas → Nueva venta.** Eliges boleta o factura, el cliente y las líneas. El
panel derecho muestra el asiento que se generará.

Mientras la venta esté en borrador, el detalle tiene **Editar** para corregir
descripciones, cantidades o precios. Una venta confirmada no se edita; revisa
el procedimiento aplicable al comprobante antes de registrar una nota.

Al confirmar se descuenta stock por PEPS y se calcula el costo real. En una venta al contado también se registra el cobro; en una venta al crédito se registra después desde el detalle de la venta. El saldo considera las notas y los cobros vinculados; los cobros históricos no vinculados requieren revisión.
La confirmación de nuevas ventas admite soles. Para ventas al contado, la cuenta
de cobro debe estar activa, pertenecer a la empresa y tener una cuenta contable.
Antes de confirmar una venta al crédito, registra las cuotas pactadas desde su detalle. Por ahora la suma debe coincidir con el total de la venta; los anticipos, detracciones, retenciones y otras deducciones requieren tratamiento adicional. Las cuotas muestran lo pactado originalmente. Puedes asignar un cobro nuevo a una cuota al registrarlo o asignar un cobro existente desde su fila, después de comprobar a cuál corresponde. No se crea otro movimiento ni se distribuyen automáticamente las notas. La asignación requiere que el cobro completo quepa en una sola cuota y que sus respaldos estén vigentes; las notas y los períodos cerrados requieren revisión. Los movimientos históricos no vinculados a la venta no se asignan en este flujo.
Desde Ventas, «Cuentas por cobrar» permite consultar el saldo documentado según las fechas de venta, notas y cobros hasta la fecha de corte. El filtro inicial incluye tanto saldos pendientes como saldos negativos y movimientos anteriores que requieren revisión; no presume que un saldo negativo sea un reembolso confirmado. El primer vencimiento mostrado es el pactado originalmente y no identifica una cuota vencida pendiente.
El correlativo de la serie (`Serie.ultimo_numero`) se actualiza de forma atómica
en ese momento; una venta en borrador no consume número. Las facturas E001 ya
aceptadas por SUNAT no se modifican.

Una factura exige RUC. Una boleta mayor a S/ 700 exige identificar al comprador.

## Notas

En el detalle de una venta confirmada:

- **Nota de crédito**: el registro admite anulación y devolución total o por
  ítem. Si el bien reingresa, devuelve el stock a su costo original; si no,
  el asiento no registra una entrada de inventario.
- **Nota de débito**: intereses o penalidades. Aumenta la cuenta por cobrar.

El ERP registra estas notas localmente: no las emite ni las envía a SUNAT. Los
motivos de descuento y corrección de descripción aún no están implementados. La
anulación o devolución total requiere acreditar toda la venta sin notas previas.

## Reportes

| Reporte | Qué muestra |
|---|---|
| Balance de comprobación | Saldo inicial, movimientos del período y saldos de cierre por cuenta |
| Libro mayor | Saldo inicial y movimientos con saldo corrido por cuenta |
| Registro de ventas | Ventas y notas, con totales separados por moneda y exportación CSV |
| Registro de compras | Compras y gastos, con exportación CSV; no incluye provisiones |
| IGV y RER | IGV del mes y renta del 1,5 % |
| Estados financieros | Situación, resultados, cambios y flujo |
| Conciliación SUNAT | Casillas contra la vista preliminar o contra la propuesta del SIRE |

El balance y el mayor consideran los asientos confirmados anteriores al rango
para calcular el saldo inicial. Los movimientos corresponden al rango elegido;
un saldo positivo en el mayor es deudor y uno negativo, acreedor. Estos reportes
son consultas del ERP y no constituyen por sí solos libros electrónicos enviados.
El registro de ventas agrupa los importes por la moneda registrada sin hacer una
conversión tributaria. Su CSV es un archivo de revisión, no un archivo validado
para importar directamente a SUNAT; los documentos sin tipo de identidad conocido
dejan el campo vacío en lugar de asumir que se trata de un DNI.

## Impuestos

**IGV y RER.** El reporte calcula el IGV del mes y la renta del 1,5 %. En el
panel, **IGV por pagar** muestra el saldo real de la cuenta 40111. En
**Impuestos**, el KPI y la tabla **PDT 621** muestran una estimación que debe
compararse con el registro y la declaración: el 140 es el IGV del mes, el 145
el saldo a favor anterior y el 184 el resultado (140 - 145). Si el libro y el
621 no coinciden, revisa si quedó una declaración anterior sin pagar.
El reporte de impuestos se consulta por un mes completo y, por defecto, muestra
el mes actual. Los demás reportes permiten elegir un mes o un rango de fechas;
las exportaciones usan el mismo período que se muestra en pantalla.

La tarjeta **Renta RER por pagar** muestra el saldo de la 40171, es decir, la
renta de meses anteriores que aún no se paga.

### Pagar el IGV

En **Impuestos**, la tarjeta **IGV por pagar** muestra el cálculo interno del
período, lo ya registrado como pagado y el pendiente estimado. Contrasta la
casilla 184, los saldos anteriores y el redondeo con la declaración antes de
usar el formulario **Registrar pago de IGV efectuado**. El ERP no hace el pago
ni envía la declaración a SUNAT; el formulario solo registra un pago real.

- Fecha del pago y cuenta de tesorería.
- Importe total o parcial realmente pagado; el sistema no permite superar su
  pendiente estimado. Si la declaración muestra otro importe, revisa la
  diferencia antes de registrar la operación.
- El sistema crea el asiento D 40111 / H banco, el movimiento de tesorería y el
  registro de historial.

Un pago parcial reduce el pendiente y puede completarse después. El pago de
un período cerrado puede registrarse en una fecha posterior cuyo período
contable esté abierto. El pago de octubre solo debe registrarse cuando se
confirme la fecha y la cuenta.

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
| 303 / 304 | Saldo a favor anterior y renta a pagar; pendientes de contrastar con la declaración anterior |

En el detalle de cada compra o venta hay una tarjeta **PDT 621** con las casillas
que aporta ese comprobante. Una compra sin RUC, serie o número no suma en
107/108. Una boleta de compra no otorga crédito. Una compra pendiente de factura
no entra al 621 hasta completarse.

El registro de compras distingue los documentos sin crédito de los que tienen
datos incompletos o una clasificación incompatible; estos últimos se marcan para
revisión. Esta estimación no verifica el comprobante ni todos los requisitos del
crédito fiscal ante SUNAT.

Cuando hay renta y todavía no está asentada, el botón **Asentar renta de
MM/AAAA** crea el asiento 881 contra 40171. Al cerrar el mes se hace solo. Para
pagarla, usa **Registrar pago**: debita la 40171 y registra la salida del banco.
Si el mes no tiene ventas, la renta del mes es cero, pero el saldo por pagar de
los meses anteriores sigue visible.

## Cierre del mes

**Periodos**. Antes de cerrar:

1. **Revaluar**: ajusta los saldos en dólares al tipo de cambio de fin de mes.
2. **Cerrar**: bloquea el mes. No deben quedar borradores.

Un periodo cerrado rechaza asientos nuevos. Reabrirlo exige ser administrador
y escribir un motivo; el cierre y la reapertura dejan un registro con usuario y
fecha. Si el cierre anual está vigente, primero debe revertirse antes de
reabrir un mes de ese ejercicio.

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
2. Descarga la propuesta en Excel, CSV o texto. Si viene en ZIP, extrae primero
   el archivo de texto; el ERP admite texto separado por barras, comas o punto y coma.
3. En el ERP elige año, mes y registro, adjunta el archivo y pulsa **Conciliar**.

El lector busca columnas por su nombre y admite cambios de orden. Una plantilla
con nombres o estructuras distintos requiere revisión. Los importes de notas y
descuentos conservan el signo leído del archivo; contrástalos con el registro.
La fila de totales se ignora para no contar dos veces.
Las operaciones con IVAP o compras destinadas a operaciones mixtas o no gravadas
se bloquean en esta comparación porque el ERP aún no calcula esas casillas.
El ERP intenta identificar si el archivo es RCE o RVIE por columnas distintivas:
si detecta el registro contrario, rechaza la comparación; si no puede
identificarlo, muestra un aviso y no da la comparación por verificada.

El resultado separa base e IGV de la estimación tributaria del total documental.
Este último incluye las boletas con serie y número aunque no otorguen crédito,
para compararlas con una propuesta que el usuario haya complementado. Una
diferencia de totales es una señal para revisar los documentos; no identifica
por sí sola cuál falta ni demuestra un error tributario. Los documentos en otra
moneda impiden comparar los totales hasta revisar su tratamiento.

Cuando reconoce las columnas del RCE, el ERP compara además facturas y boletas
individuales en soles por emisor, tipo, serie y número, y muestra diferencias de
fecha o total, duplicados y documentos que no pudo identificar. Las notas,
rangos y otras monedas quedan fuera de esa comparación individual. El resultado
no demuestra aceptación ni generación del registro por SUNAT. Si incorporas
la boleta en SUNAT, descarga de nuevo el archivo resultante para contrastarlo;
el ERP no modifica la propuesta.

El servidor del ERP procesa el archivo y no lo envía a SUNAT ni lo conserva como
documento del ERP; la plataforma puede usar archivos temporales durante la carga.


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

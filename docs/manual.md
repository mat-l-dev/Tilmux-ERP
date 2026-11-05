# Manual de uso

## Entrar

Doble clic en **Tilmux ERP** del escritorio. Abre `http://127.0.0.1:8000`.
Para apagarlo, cierra la ventana negra.

## Orden de trabajo

1. Catálogos (una sola vez).
2. Compras.
3. Ventas.
4. Cobros y pagos.
5. Cierre del mes.

## Catálogos

En **Configuración** (el admin) se cargan productos, proveedores, clientes,
unidades, series y cuentas de tesorería. Las cuentas contables ya están cargadas:
1 636 del PCGE 2026, con 44 activas.

## Compras

**Compras → Nueva compra.** Escribes la factura del proveedor, agregas las líneas
y, si hubo flete o aduana, los costos de internamiento. Se prorratean por valor y
el costo unitario final los incluye.

Al confirmar: se crean las capas de stock y el asiento por pagar.

**Compras → Importar XML.** Subes el XML de SUNAT y el sistema extrae RUC, serie,
número, base, IGV y total. Confirma como gasto o como mercadería.

Regla: una **factura** separa base e IGV; una **boleta** no otorga crédito y su
IGV forma parte del costo.

## Pagar una compra

En el detalle de la compra confirmada, **Pagar compra**. Sale el dinero de la
cuenta que elijas. Si la compra es en dólares y pagas con otro tipo de cambio, la
diferencia se reconoce en la 6761 o 7761.

## Ventas

**Ventas → Nueva venta.** Eliges boleta o factura, el cliente y las líneas. El
panel derecho muestra el asiento que se generará.

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

## Cierre del mes

**Periodos**. Antes de cerrar:

1. **Revaluar**: ajusta los saldos en dólares al tipo de cambio de fin de mes.
2. **Cerrar**: bloquea el mes. No deben quedar borradores.

Un periodo cerrado rechaza asientos nuevos. Reabrirlo exige ser administrador.

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

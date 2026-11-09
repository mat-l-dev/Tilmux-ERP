# Continuación del ERP TILMUX

Actualizado el 9 de noviembre de 2026. Este documento orienta el siguiente
trabajo; no es una certificación de que el ERP esté terminado ni sustituye la
revisión de la normativa o de los comprobantes.

## Cómo continuar

- Lee `docs/auditoria.md` y `docs/manual.md`, y verifica el estado actual de
  Git y de la base antes de cambiar el código. No incluyas claves, documentos
  de identidad, datos bancarios ni comprobantes sensibles en el repositorio.
- Desarrolla en una rama; prueba con PostgreSQL desechable. No ejecutes pruebas,
  comandos de carga, migraciones de datos o correcciones masivas contra la base
  real. Las actualizaciones de esquema deben revisarse y protegerse antes de
  aplicarlas. No declares, pagues ni registres operaciones que no sucedieron.
- `main` tiene configurado despliegue automático en `render.yaml`; una subida
  puede activar el despliegue y el contenedor aplica migraciones al arrancar.
- Consulta las fuentes oficiales de SUNAT y la documentación de las librerías
  aplicables antes de decidir tratamientos tributarios o de implementación.

## Situación comprobada

- El 9/11 se corrigió el error de Impuestos: faltaba aplicar la migración
  `contabilidad.0012_declaracionigv621`. Ya se aplicó a la base usada por el
  ERP y se verificó la protección de la tabla frente a roles públicos. No
  vuelvas a editar migraciones ya aplicadas; crea una nueva si hace falta.
- La pantalla permite guardar manualmente los datos de una constancia 621
  presentada y conservar registros de rectificatorias o errores de digitación.
  No verifica la constancia con SUNAT y no cambia el pendiente de pago.
- Para octubre de 2026, una consulta de lectura al 9/11 mostró ingresos netos
  de S/ 1.196,62, renta RER estimada en libros de S/ 17,95, saldo de la 40171
  al cierre de S/ 17,95 y ningún pago de IGV de octubre en el ERP. Estas cifras
  son históricas y deben volver a verificarse antes de tomar decisiones.
- El mayor tiene un selector de cuentas con movimientos de la empresa y conserva
  el período; el balance permite abrir el mayor de una cuenta. Sus saldos
  iniciales consideran asientos confirmados anteriores al rango.
- Según lo informado por el usuario al 8/11, el IGV de octubre de S/ 105 no
  estaba pagado; la devolución de S/ 500 al accionista y la de S/ 39 a su padre
  también estaban pendientes. No se debe asumir que una operación sigue o dejó
  de estar pendiente sin comprobar documentación y movimientos posteriores.
- La boleta de comisiones B001-00393302 por S/ 198,04 es la que el usuario
  desea incorporar en la propuesta RCE. La propuesta descargada no demuestra por
  sí sola qué se aceptó, modificó o presentó finalmente.

## Pendientes prioritarios

1. **IGV declarado y pagos.** Diseñar cómo conservar y contrastar la deuda real
   y las constancias del 621, incluidas sustitutorias, rectificatorias, pagos y
   otros conceptos que afecten la deuda final. No confundir la casilla 184 con
   el total necesariamente pagadero ni modificar libros por céntimos sin
   evidencia. Hoy el límite de registro usa una estimación contable; si difiere
   de SUNAT, requiere revisión manual.
2. **Compras y notas de proveedores.** Completar un flujo auditable que distinga
   notas, devoluciones, deudas ya pagadas, reembolsos y situación de inventario.
   El tratamiento contable y tributario depende de los documentos y los hechos.
   No asumir que PEPS devuelve siempre la capa de la compra original.
3. **Moneda extranjera.** Diseñar importes en moneda original, tipos de cambio,
   pagos parciales, conversión y diferencias de cambio con pruebas. Las compras
   y transferencias que el sistema no puede contabilizar correctamente están
   bloqueadas; no levantar los bloqueos sin implementar el flujo completo.
4. **Conciliación y cierre tributario.** Contrastar el RCE/RVIE definitivo y
   las constancias presentadas con los libros, incluyendo la boleta indicada
   por el usuario y cualquier diferencia sustentada. Investigar las reglas de
   anotación, el tratamiento de operaciones mixtas y el redondeo antes de
   automatizarlos. Una propuesta no acredita una presentación.
5. **Revisión integral de pantallas y datos.** Continuar la auditoría de flujos,
   permisos por empresa, trazabilidad, accesibilidad y consistencia entre
   módulos. Priorizar errores reproducidos y respaldarlos con pruebas. Revisar
   los expedientes y vouchers antes de registrar restituciones o movimientos.
6. **Comprobación de respaldos.** La ejecución de «Verificar restauración» del
   9/11 falló porque compara datos restaurados con importes y cantidades fijos
   en `.github/workflows/verificar-restauracion.yml`. Investigar si los valores
   quedaron desactualizados y sustituir esa comparación por verificaciones
   coherentes con el mismo respaldo y con sus invariantes. El fallo por sí solo
   no demuestra pérdida de datos ni valida que el respaldo sea recuperable.

## Verificación reciente

Antes de la entrega se ejecutó la suite completa en PostgreSQL aislado: 301
pruebas, una omitida. La comprobación de seguridad que se omite fuera de CI se
ejecutó aparte con el entorno de CI y pasó. Estas verificaciones no prueban que
todos los flujos o cálculos tributarios del ERP estén completos.

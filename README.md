# Tilmux ERP

ERP contable de TILMUX S.A.C. Django 6.1 sobre PostgreSQL (Supabase).

## Requisitos

- Python 3.14
- [uv](https://docs.astral.sh/uv/)

## Puesta en marcha

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py cargar_pcge
uv run python manage.py sembrar_tilmux
uv run python manage.py runserver
```

Abrir http://127.0.0.1:8000

## Estructura

| Ruta | Contenido |
|---|---|
| `config/` | Configuración de Django |
| `core/` | Empresa, periodos, panel |
| `contabilidad/` | Catálogo PCGE y, más adelante, el motor de asientos |
| `data/` | Catálogo PCGE 2026 en JSON |
| `templates/` | Plantillas |
| `static/` | CSS y JS |

## Comandos propios

| Comando | Qué hace |
|---|---|
| `cargar_pcge` | Carga las 1.636 cuentas del PCGE 2026 |
| `sembrar_tilmux` | Crea la empresa, sus periodos y activa las 44 cuentas en uso |
| `sembrar_base` | Unidades, series y cuentas de tesorería |
| `sembrar_reglas` | Las 15 reglas contables |
| `sembrar_productos` | Los dos SKUs iniciales |
| `importar_excel` | Importa las 23 operaciones del Excel de TILMUX |
| `actualizar_tipo_cambio` | Descarga el tipo de cambio diario de SUNAT |

## Comprobantes electrónicos

En **Compras → Importar XML** se sube una factura, boleta o guía de SUNAT.
El sistema extrae RUC, serie, número, base, IGV y total, y propone el gasto para
confirmarlo. El archivo no se guarda.

Regla aplicada: una **boleta de venta** no otorga crédito fiscal ni sustenta
gasto para efecto tributario, así que se registra por el total. Una **factura**
separa base e IGV y sí genera crédito.

## Uso diario

Doble clic en el acceso directo **Tilmux ERP** del escritorio. Arranca el
servidor y abre el navegador. Detalle en [uso local](docs/uso-local.md).

## Despliegue (opcional)

`render.yaml` deja preparado un despliegue gratuito en Render, sin tarjeta,
para cuando quieras abrirlo desde otro dispositivo. Ver [despliegue](docs/despliegue.md).

## Tests

Los invariantes contables se prueban en integración continua contra un PostgreSQL
local del runner, en segundos:

```
Actions → Tests
```

Cubren: asiento cuadrado, rechazo en la base de un asiento descuadrado, costo
landed, FIFO por capa, conservación del stock, nota de crédito al costo original,
descomposición del IGV y doble confirmación de una venta.

En local tardan varios minutos porque cada consulta viaja a Supabase. Para una
verificación rápida, usa el workflow.

## Respaldo

`.github/workflows/backup.yml` vuelca la base todos los días a las 06:00 UTC y
guarda el archivo 30 días. Requiere el secreto `DATABASE_URL` en el repositorio.

## Decisiones registradas

- **PCGE 2026 con adopción anticipada**, permitida por la Resolución 002-2026-EF/30 (vigencia obligatoria 2028-01-01).
- **Régimen RER.** IGV 18 %, renta 1,5 % mensual sobre ingresos netos.
- **Cantidades con 2 decimales** para bienes medibles (metros de cable).
- **Costeo PEPS** por capas, con redondeo en la línea y nunca en el costo unitario.
- **Un solo almacén** por ahora.
- **La base de datos es el contador; la aplicación es el auxiliar.** Toda invariante contable vive en PostgreSQL.

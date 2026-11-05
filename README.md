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

## Despliegue

```powershell
flyctl auth login
flyctl apps create tilmux-erp
flyctl secrets set DJANGO_DEBUG=false DJANGO_SECRET_KEY=... DATABASE_URL=...
flyctl deploy --remote-only
```

`fly.toml` ya incluye migración automática en cada despliegue y la sonda de
salud en `/salud/`. La máquina se suspende sin tráfico y despierta en menos de
un segundo con la primera visita.

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

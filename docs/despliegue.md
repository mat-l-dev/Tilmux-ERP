# Despliegue en Render

Render free tier no pide tarjeta. El servicio duerme tras 15 minutos sin uso y
despierta con la primera visita en unos 50 segundos.

## Primera vez

1. Entra a https://dashboard.render.com y regístrate con GitHub.
2. **New → Blueprint**.
3. Conecta el repositorio `mat-l-dev/Tilmux-ERP`.
4. Render lee `render.yaml` y pide el valor de `DATABASE_URL`.
   Pega la cadena de Supabase (Session pooler, puerto 5432).
5. **Apply**.

El primer build tarda unos 5 minutos.

## Después

Cada push a `main` pasa primero por `.github/workflows/tests.yml` (jobs `Ruff` e
`Invariantes`). Render solo despliega si esos checks pasan
(`autoDeployTrigger: checksPass`); antes desplegaba con cualquier push
(`autoDeploy: true`). El merge a `main` sigue siendo del usuario: el agente deja
la rama y el PR listos, no mergea.

Las migraciones corren al arrancar el contenedor (`docker-entrypoint.sh`), así
que no hay paso manual. `preDeployCommand` de Render existe solo en planes
pagos: si el servicio pasa a plan pago, mover ahí el `migrate --noinput` y
quitarlo del entrypoint (el comentario está en `render.yaml`).

## Base de datos

La base de producción es **Supabase** (session pooler, puerto 5432), no un
Postgres de Render. Por eso no aplica la caducidad de 30 días de Render
Postgres Free; conviene aun así confirmar el plan de Supabase y sus respaldos.
La versión mayor de PostgreSQL en Supabase no está documentada en el repo:
confirmarla antes de fijar `postgres:17.11` en los workflows de respaldo.

## Verificar

`https://tilmux-erp.onrender.com/salud/` debe devolver `{"estado": "ok"}`.

## Respaldo

`.github/workflows/backup.yml` sigue funcionando: se conecta directo a Supabase,
no depende del hosting. Requiere el secreto `DATABASE_URL` en el repositorio
(ya cargado).

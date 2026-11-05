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

Cada push a `main` despliega solo (`autoDeploy: true`).

Las migraciones corren al arrancar el contenedor (`docker-entrypoint.sh`), así
que no hay paso manual.

## Verificar

`https://tilmux-erp.onrender.com/salud/` debe devolver `{"estado": "ok"}`.

## Respaldo

`.github/workflows/backup.yml` sigue funcionando: se conecta directo a Supabase,
no depende del hosting. Requiere el secreto `DATABASE_URL` en el repositorio
(ya cargado).

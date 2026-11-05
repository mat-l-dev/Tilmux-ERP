# Cómo usarlo en tu PC

## Arrancar

Doble clic en **Tilmux ERP** (el acceso directo del escritorio o el archivo
`Tilmux ERP.bat` de la carpeta del proyecto).

Se abre una ventana negra con el servidor y, cuatro segundos después, el
navegador en `http://127.0.0.1:8000`.

Para apagarlo: cierra la ventana negra o pulsa `Ctrl+C`.

## Qué consume

| | |
|---|---|
| Servidor (Waitress) | ~120 MB de RAM |
| Base de datos | 0 en tu PC: vive en Supabase |
| Arranque | 2 segundos |

No hay Docker, ni Node, ni servicios de fondo. Nada queda corriendo cuando cierras
la ventana.

## Con Docker (opcional)

Si prefieres el contenedor:

```powershell
docker compose up --build
```

Ocupa alrededor de 1,5 GB entre Docker Desktop y WSL, por eso no es la vía
recomendada en un equipo de 16 GB.

## Dónde están los datos

En Supabase, en la nube. Aunque se rompa tu PC, el libro sigue intacto. El
respaldo diario corre en GitHub Actions y guarda un volcado de 30 días.

## Cuentas

| | |
|---|---|
| Usuario | `mathew` |
| Contraseña | la que cambiaste en `/admin/` |

## Si algún día quieres acceso desde el celular

`render.yaml` deja preparado un despliegue gratuito en Render (sin tarjeta).
Solo hay que conectar el repositorio desde el panel de Render.

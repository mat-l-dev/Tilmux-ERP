# Despliegue

El despliegue corre en GitHub Actions, no en tu computadora. Así el antivirus no
interfiere y cada push a `main` publica la versión nueva.

## Secretos del repositorio

En GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secreto | Para qué |
|---|---|
| `FLY_API_TOKEN` | Desplegar en Fly.io |
| `DATABASE_URL` | Respaldo diario de la base |

### Cómo obtener el token de Fly

1. Entra a https://fly.io/user/personal_access_tokens
2. **Create token**, nombre `github-deploy`, sin fecha de expiración.
3. Copia el valor (empieza con `FlyV1 ...`) y guárdalo como `FLY_API_TOKEN`.

El token permite desplegar; no es la contraseña de tu cuenta.

## Desplegar

Con el secreto cargado, cualquier push a `main` despliega. También puedes lanzarlo
a mano desde **Actions → Desplegar → Run workflow**.

La migración corre sola: `fly.toml` la declara como `release_command`.

## Verificar

https://tilmux-erp.fly.dev/salud/ debe devolver `{"estado": "ok"}`.

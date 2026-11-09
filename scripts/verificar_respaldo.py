"""Compara la restauración con la misma instantánea usada por pg_dump.

No imprime filas ni valores financieros. El manifiesto es temporal y contiene
solo cantidades y huellas por tabla; no sustituye conservar el propio respaldo.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql

PREFIJOS_ERP = (
    "auth_", "catalogo_", "compras_", "contabilidad_", "core_", "django_",
    "inventario_", "tesoreria_", "ventas_",
)
TABLAS_ESENCIALES = {
    "auth_user", "core_empresa", "django_migrations", "contabilidad_asiento",
    "contabilidad_asientolinea", "ventas_venta",
}


def huellas_tablas(conexion) -> dict[str, list]:
    """Cuenta y resume el contenido de cada tabla del ERP, sin depender del orden."""
    with conexion.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SET LOCAL DateStyle TO 'ISO, YMD'")
        cursor.execute("SET LOCAL bytea_output TO 'hex'")
        cursor.execute("SET LOCAL extra_float_digits TO 3")
        # Nunca considerar una vista filtrada por políticas como un respaldo completo.
        cursor.execute("SET LOCAL row_security TO off")
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname"
        )
        nombres = [nombre for (nombre,) in cursor.fetchall() if nombre.startswith(PREFIJOS_ERP)]
        if not TABLAS_ESENCIALES.issubset(nombres):
            raise ValueError("Faltan tablas esenciales del ERP en la base consultada.")
        resultado = {}
        for nombre in nombres:
            consulta = sql.SQL(
                "SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                "FROM (SELECT md5(row_to_json(t)::text) AS h FROM {}.{} AS t) AS filas"
            ).format(sql.Identifier("public"), sql.Identifier(nombre))
            cursor.execute(consulta)
            cantidad, huella = cursor.fetchone()
            resultado[nombre] = [cantidad, huella]
        return resultado


def comparar_huellas(original: dict, restaurado: dict) -> list[str]:
    if not original or not restaurado:
        raise ValueError("No se puede comprobar un manifiesto vacío.")
    return sorted(
        nombre for nombre in original.keys() | restaurado.keys()
        if original.get(nombre) != restaurado.get(nombre)
    )


def crear_copia(ruta: Path) -> None:
    ruta.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"]) as conexion:
        conexion.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conexion.read_only = True
        with conexion.cursor() as cursor:
            cursor.execute("SELECT pg_export_snapshot()")
            instantanea = cursor.fetchone()[0]
        huellas = huellas_tablas(conexion)
        # La conexión se mantiene abierta hasta que pg_dump termine de leer.
        # El URI viaja por variable de entorno, no como argumento del comando.
        subprocess.run(
            [
                "docker", "run", "--rm", "--network", "host", "-e", "DATABASE_URL",
                "-v", f"{ruta.resolve()}:/out", "postgres:17", "sh", "-c",
                'exec pg_dump "$DATABASE_URL" -Fc -n public --snapshot="$1" -f /out/tilmux.dump',
                "sh", instantanea,
            ],
            check=True,
            timeout=900,
        )
    (ruta / "huellas.json").write_text(json.dumps(huellas, sort_keys=True), encoding="utf-8")
    print("Copia y huellas generadas desde una misma instantánea.")


def verificar_copia(ruta: Path) -> None:
    original = json.loads((ruta / "huellas.json").read_text(encoding="utf-8"))
    with psycopg.connect(os.environ["RESTORE_DATABASE_URL"]) as conexion:
        conexion.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conexion.read_only = True
        restaurado = huellas_tablas(conexion)
    diferencias = comparar_huellas(original, restaurado)
    if diferencias:
        raise ValueError("La restauración difiere en estas tablas: " + ", ".join(diferencias))
    print(f"Restauración verificada: coinciden las huellas de {len(original)} tablas del ERP.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("crear", "verificar"))
    parser.add_argument("--directorio", type=Path, default=Path("out"))
    args = parser.parse_args()
    if args.accion == "crear":
        crear_copia(args.directorio)
    else:
        verificar_copia(args.directorio)


if __name__ == "__main__":
    main()

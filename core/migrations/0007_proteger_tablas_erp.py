"""Impide el acceso directo público a las tablas internas del ERP."""

from django.db import migrations

TABLAS = (
    "auth_group", "auth_group_permissions", "auth_permission", "auth_user", "auth_user_groups",
    "auth_user_user_permissions", "catalogo_cuentatesoreria", "catalogo_producto", "catalogo_serie",
    "catalogo_tercero", "catalogo_unidadmedida", "compras_compra", "compras_compralinea",
    "compras_costoadicional", "compras_gasto", "compras_pagogasto", "contabilidad_asiento",
    "contabilidad_asientolinea", "contabilidad_cuenta", "contabilidad_regla", "contabilidad_reglalinea",
    "core_empresa", "core_historialdocumento", "core_perfil", "core_periodo", "core_tipocambio",
    "django_admin_log", "django_content_type", "django_migrations", "django_session", "inventario_capafifo",
    "inventario_consumocapa", "inventario_movimientostock", "tesoreria_conciliacionbancaria",
    "tesoreria_movimientotesoreria", "ventas_cobroventa", "ventas_cotizacion", "ventas_cotizacionlinea",
    "ventas_cuotaventa", "ventas_guiaremision", "ventas_notacredito", "ventas_notacreditolinea",
    "ventas_notadebito", "ventas_venta", "ventas_ventalinea",
)


def proteger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    conexion = schema_editor.connection
    cita = schema_editor.quote_name
    with conexion.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        roles = [fila[0] for fila in cursor.fetchall()]
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)", [list(TABLAS)],
        )
        existentes = {fila[0] for fila in cursor.fetchall()}
        faltantes = set(TABLAS) - existentes
        if faltantes:
            raise RuntimeError("No se encontraron todas las tablas del ERP; se canceló la protección.")
        for tabla in TABLAS:
            nombre = f'{cita("public")}.{cita(tabla)}'
            cursor.execute(f"ALTER TABLE {nombre} ENABLE ROW LEVEL SECURITY")
            destinatarios = ", ".join(["PUBLIC", *(cita(rol) for rol in roles)])
            cursor.execute(f"REVOKE ALL PRIVILEGES ON TABLE {nombre} FROM {destinatarios}")
        cursor.execute(
            "SELECT s.relname FROM pg_class s JOIN pg_namespace n ON n.oid = s.relnamespace "
            "JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a', 'i') "
            "JOIN pg_class t ON t.oid = d.refobjid "
            "WHERE n.nspname = 'public' AND s.relkind = 'S' AND t.relname = ANY(%s)", [list(TABLAS)],
        )
        for (secuencia,) in cursor.fetchall():
            nombre = f'{cita("public")}.{cita(secuencia)}'
            cursor.execute(f"REVOKE ALL PRIVILEGES ON SEQUENCE {nombre} FROM {destinatarios}")
        if roles:
            destinatarios_roles = ", ".join(cita(rol) for rol in roles)
            cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {destinatarios_roles}")
            cursor.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {destinatarios_roles}"
            )
        cursor.execute("SELECT to_regprocedure('public.tilmux_asiento_cuadrado()') IS NOT NULL")
        if cursor.fetchone()[0]:
            cursor.execute(f"REVOKE ALL ON FUNCTION public.tilmux_asiento_cuadrado() FROM {destinatarios}")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_alter_historialdocumento_tipo"),
        ("compras", "0019_pagogasto"),
        ("contabilidad", "0010_alter_asiento_tipo_operacion_alter_regla_tipo"),
        ("inventario", "0001_initial"),
        ("tesoreria", "0002_conciliacionbancaria"),
        ("ventas", "0008_cuotaventa"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("sessions", "0001_initial"),
    ]
    # Revertir el esquema no debe volver a exponer los datos; la copia de permisos permite recuperarlos expresamente.
    operations = [migrations.RunPython(proteger, migrations.RunPython.noop)]

import importlib
import os

from django.apps import apps
from django.db import connection
from django.test import TestCase

from core.models import Empresa


class SeguridadTablasERPTest(TestCase):
    def test_tablas_sensibles_no_tienen_acceso_publico_directo(self):
        if connection.vendor != "postgresql":
            self.skipTest("La protección se aplica en PostgreSQL.")
        nombres = [
            "auth_user", "core_empresa", "compras_gasto", "ventas_cobroventa", "django_session",
            "contabilidad_declaracionigv621",
        ]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind='r' AND c.relname = ANY(%s)", [nombres],
            )
            tablas = dict(cursor.fetchall())
            self.assertEqual(set(tablas), set(nombres))
            self.assertTrue(all(tablas.values()))
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")
            roles = [fila[0] for fila in cursor.fetchall()]
            for rol in roles:
                for tabla in nombres:
                    cursor.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", [rol, f"public.{tabla}"])
                    self.assertFalse(cursor.fetchone()[0], f"{rol} puede leer {tabla}")
                    cursor.execute("SELECT has_table_privilege(%s, %s, 'TRUNCATE')", [rol, f"public.{tabla}"])
                    self.assertFalse(cursor.fetchone()[0], f"{rol} puede vaciar {tabla}")
        Empresa.objects.count()

    def test_revoca_permisos_concedidos_a_roles_de_api(self):
        if connection.vendor != "postgresql" or os.environ.get("CI") != "true":
            self.skipTest("La simulación de roles solo se ejecuta en la base desechable de CI.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            if not cursor.fetchone()[0]:
                self.skipTest("La simulación necesita el PostgreSQL desechable de CI.")
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated')")
            existentes = {fila[0] for fila in cursor.fetchall()}
            for rol in ("anon", "authenticated"):
                if rol not in existentes:
                    cursor.execute(f'CREATE ROLE "{rol}" NOLOGIN')
                cursor.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON public.auth_user TO "{rol}"')
                cursor.execute(f'GRANT USAGE ON SEQUENCE public.auth_user_id_seq TO "{rol}"')
        migracion = importlib.import_module("core.migrations.0007_proteger_tablas_erp")
        migracion.proteger(apps, connection.schema_editor())
        with connection.cursor() as cursor:
            for rol in ("anon", "authenticated"):
                for permiso in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    cursor.execute("SELECT has_table_privilege(%s, 'public.auth_user', %s)", [rol, permiso])
                    self.assertFalse(cursor.fetchone()[0], f"{rol} conserva {permiso}")
                cursor.execute("SELECT has_sequence_privilege(%s, 'public.auth_user_id_seq', 'USAGE')", [rol])
                self.assertFalse(cursor.fetchone()[0])

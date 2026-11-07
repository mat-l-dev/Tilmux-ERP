from django.db import connection
from django.test import TestCase

from core.models import Empresa


class SeguridadTablasERPTest(TestCase):
    def test_tablas_sensibles_no_tienen_acceso_publico_directo(self):
        if connection.vendor != "postgresql":
            self.skipTest("La protección se aplica en PostgreSQL.")
        nombres = ["auth_user", "core_empresa", "compras_gasto", "ventas_cobroventa", "django_session"]
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

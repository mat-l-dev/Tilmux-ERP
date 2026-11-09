from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase

from scripts.verificar_respaldo import comparar_huellas, huellas_tablas


class ComparacionRespaldoTest(SimpleTestCase):
    def test_acepta_la_misma_informacion_y_rechaza_cambios_o_tablas_faltantes(self):
        original = {"auth_user": [2, "abc"], "ventas_venta": [1, "def"]}
        self.assertEqual(comparar_huellas(original, dict(original)), [])
        self.assertIn("auth_user", comparar_huellas(original, {**original, "auth_user": [2, "cambio"]}))
        self.assertIn("ventas_venta", comparar_huellas(original, {"auth_user": [2, "abc"]}))
        self.assertIn("nueva_tabla", comparar_huellas(original, {**original, "nueva_tabla": [0, "xyz"]}))

    def test_rechaza_una_comparacion_vacia(self):
        with self.assertRaises(ValueError):
            comparar_huellas({}, {})


class HuellasRespaldoTest(TestCase):
    def test_detecta_cambios_en_el_contenido_aunque_el_numero_de_filas_no_varie(self):
        if connection.vendor != "postgresql":
            self.skipTest("La verificación usa PostgreSQL.")
        usuario = get_user_model().objects.create_user(username="usuario_verificacion")
        antes = huellas_tablas(connection.connection)
        usuario.first_name = "Cambio"
        usuario.save(update_fields=["first_name"])
        despues = huellas_tablas(connection.connection)
        self.assertEqual(antes["auth_user"][0], despues["auth_user"][0])
        self.assertNotEqual(antes["auth_user"][1], despues["auth_user"][1])

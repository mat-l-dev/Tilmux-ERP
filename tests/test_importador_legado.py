from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class ImportadorLegadoTest(SimpleTestCase):
    def test_importador_antiguo_no_ejecuta_asociaciones_no_verificadas(self):
        with self.assertRaisesMessage(CommandError, "importación histórica está suspendida"):
            call_command("importar_excel")

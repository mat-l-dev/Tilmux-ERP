"""Consistencia de los importes exportados del registro de compras."""

import csv
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from reportes.exportar import compras


class ExportacionComprasTest(SimpleTestCase):
    def test_compra_no_gravada_no_se_exporta_como_base_gravada(self):
        request = RequestFactory().get("/reportes/compras/exportar/")
        request.user = SimpleNamespace(is_authenticated=True)
        factura = SimpleNamespace(
            fecha=date(2026, 10, 1), fecha_anotacion=None, tipo_doc="FACTURA", serie="F001", numero="1",
            proveedor=SimpleNamespace(tipo_doc="RUC", numero_doc="20100000001", nombre="Proveedor"),
            con_credito=True, subtotal=Decimal("28"), igv=Decimal("0"), total=Decimal("28"),
        )
        with (
            patch("reportes.exportar.empresa_actual", return_value=object()),
            patch("reportes.exportar.rango", return_value=(date(2026, 10, 1), date(2026, 10, 31))),
            patch("reportes.exportar.Compra.objects.annotate") as compras_anotadas,
            patch("reportes.exportar.Gasto.objects.annotate") as gastos_anotados,
        ):
            compras_filtradas = compras_anotadas.return_value.filter
            gastos_filtrados = gastos_anotados.return_value.filter
            compras_filtradas.return_value.select_related.return_value.order_by.return_value = [factura]
            gastos_filtrados.return_value.exclude.return_value.select_related.return_value.order_by.return_value = []
            respuesta = compras(request)
        filas = list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8-sig"))))
        self.assertEqual(filas[0]["base_imponible"], "0.00")
        self.assertEqual(filas[0]["no_gravado"], "28.00")

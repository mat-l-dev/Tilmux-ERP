"""Validaciones de cabecera de los formularios de venta y compra."""

from __future__ import annotations

from django.test import SimpleTestCase

from compras.forms import CabeceraCompraForm
from ventas.forms import CabeceraVentaForm


class VentaTest(SimpleTestCase):
    def datos(self, **cambios):
        base = {
            "fecha": "2026-11-20",
            "tipo_doc": "BOLETA",
            "serie": "B001",
            "numero": "1",
            "condicion": "CREDITO",
            "canal": "TRANSFERENCIA",
        }
        base.update(cambios)
        return base

    def test_boleta_al_credito_sin_documento_es_valida(self):
        formulario = CabeceraVentaForm(self.datos())
        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_factura_exige_ruc(self):
        formulario = CabeceraVentaForm(self.datos(tipo_doc="FACTURA"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("cliente_doc", formulario.errors)

    def test_factura_con_ruc_valido(self):
        formulario = CabeceraVentaForm(
            self.datos(tipo_doc="FACTURA", cliente_doc="20615841961")
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_contado_exige_cuenta(self):
        formulario = CabeceraVentaForm(self.datos(condicion="CONTADO"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("cuenta", formulario.errors)

    def test_documento_de_longitud_invalida(self):
        formulario = CabeceraVentaForm(self.datos(cliente_doc="123"))
        self.assertFalse(formulario.is_valid())
        self.assertIn("cliente_doc", formulario.errors)


class CompraTest(SimpleTestCase):
    def test_exige_proveedor(self):
        formulario = CabeceraCompraForm(
            {"fecha": "2026-11-20", "tipo_doc": "FACTURA"}
        )
        self.assertFalse(formulario.is_valid())

    def test_ruc_de_longitud_invalida(self):
        formulario = CabeceraCompraForm(
            {
                "fecha": "2026-11-20",
                "tipo_doc": "FACTURA",
                "proveedor_ruc": "123",
                "proveedor_nombre": "Proveedor",
            }
        )
        self.assertFalse(formulario.is_valid())

    def test_proveedor_nuevo_valido(self):
        formulario = CabeceraCompraForm(
            {
                "fecha": "2026-11-20",
                "tipo_doc": "FACTURA",
                "proveedor_ruc": "20605980008",
                "proveedor_nombre": "MERCADOLIBRE PERU S.R.L.",
            }
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)

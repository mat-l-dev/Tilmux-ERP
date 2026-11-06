"""Validaciones de cabecera de los formularios de venta y compra."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from compras.forms import CabeceraCompraForm
from compras.views import confirmar_compra
from inventario.servicios import StockError
from ventas.forms import CabeceraVentaForm
from ventas.views import confirmar_venta


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


class ConfirmacionVentaTest(SimpleTestCase):
    def test_muestra_error_de_stock_sin_error_de_servidor(self):
        request = RequestFactory().post("/ventas/1/confirmar/")
        request.user = SimpleNamespace(is_authenticated=True, perfil=None)
        venta = SimpleNamespace(pk=1)
        with (
            patch("ventas.views.get_object_or_404", return_value=venta),
            patch("ventas.views.confirmar", side_effect=StockError("Stock insuficiente")),
            patch("ventas.views.messages.error") as mostrar_error,
        ):
            respuesta = confirmar_venta(request, pk=1)
        self.assertEqual(respuesta.status_code, 302)
        mostrar_error.assert_called_once_with(request, "Stock insuficiente")

    def test_compra_muestra_aviso_de_movimiento_retroactivo(self):
        request = RequestFactory().post("/compras/1/confirmar/")
        request.user = SimpleNamespace(is_authenticated=True, perfil=None)
        compra = SimpleNamespace(pk=1)
        with (
            patch("compras.views.get_object_or_404", return_value=compra),
            patch("compras.views.confirmar", side_effect=StockError("Existe una salida posterior")),
            patch("compras.views.messages.error") as mostrar_error,
        ):
            respuesta = confirmar_compra(request, pk=1)
        self.assertEqual(respuesta.status_code, 302)
        mostrar_error.assert_called_once_with(request, "Existe una salida posterior")

"""Evita pagos y revaluaciones cuyo cálculo no está respaldado."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria, Tercero
from compras.models import Compra
from compras.servicios import CompraError, confirmar, pagar, revaluar
from contabilidad.models import Asiento, Cuenta
from core.models import Empresa, TipoCambio
from tesoreria.models import MovimientoTesoreria


class ProteccionesPagoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa SAC", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="Otra", razon_social="Otra SAC", ruc="20123456780")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor")
        cls.cuenta_contable = Cuenta.objects.create(codigo="1061", nombre="Banco", elemento=1, naturaleza="D")
        cls.cuenta = CuentaTesoreria.objects.create(
            empresa=cls.empresa, nombre="Banco", cuenta_contable=cls.cuenta_contable,
        )
        cls.compra = Compra.objects.create(
            empresa=cls.empresa, proveedor=cls.proveedor, fecha=date(2026, 11, 10),
            estado=Compra.Estado.CONFIRMADA, moneda="USD", total=Decimal("350"),
            total_moneda_origen=Decimal("100"),
        )
        cls.usuario = get_user_model().objects.create_user(username="pago")

    def test_rechaza_pago_parcial_en_moneda_extranjera_sin_movimiento(self):
        with self.assertRaisesMessage(CompraError, "pagos parciales"):
            pagar(self.compra, cuenta=self.cuenta, fecha=date(2026, 11, 12), importe="175")
        self.assertFalse(MovimientoTesoreria.objects.exists())
        self.assertFalse(Asiento.objects.exists())

    def test_rechaza_revaluar_compra_con_pago_parcial(self):
        self.compra.monto_pagado = Decimal("175")
        self.compra.save(update_fields=["monto_pagado"])
        TipoCambio.objects.create(fecha=date(2026, 11, 30), compra=Decimal("3.50"), venta=Decimal("3.55"))
        with self.assertRaisesMessage(CompraError, "pagos parciales"):
            revaluar(self.empresa, 2026, 11)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.revaluacion, 0)
        self.assertFalse(Asiento.objects.exists())

    def test_rechaza_fechas_cuentas_y_valores_invalidos(self):
        cuenta_otra = CuentaTesoreria.objects.create(
            empresa=self.otra, nombre="Otra cuenta", cuenta_contable=self.cuenta_contable,
        )
        cuenta_usd = CuentaTesoreria.objects.create(
            empresa=self.empresa, nombre="Dólares", moneda="USD", cuenta_contable=self.cuenta_contable,
        )
        for cuenta, fecha, importe, tasa in [
            (self.cuenta, date(2026, 11, 9), None, "3.5"),
            (cuenta_otra, date(2026, 11, 12), None, "3.5"),
            (cuenta_usd, date(2026, 11, 12), None, "3.5"),
            (self.cuenta, date(2026, 11, 12), "NaN", "3.5"),
            (self.cuenta, date(2026, 11, 12), None, "0"),
        ]:
            with self.subTest(cuenta=cuenta.nombre, fecha=fecha, importe=importe, tasa=tasa):
                with self.assertRaises(CompraError):
                    pagar(self.compra, cuenta=cuenta, fecha=fecha, importe=importe, tipo_cambio_pago=tasa)
        self.assertFalse(MovimientoTesoreria.objects.exists())

    def test_formulario_informa_fecha_invalida_sin_error_de_servidor(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()
        respuesta = self.client.post(reverse("compras:pagar", args=[self.compra.pk]), {
            "cuenta": self.cuenta.pk, "fecha": "2026-99-99", "importe": "350",
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(MovimientoTesoreria.objects.exists())

    def test_no_confirma_compra_extranjera_antes_de_corregir_conversion(self):
        self.compra.estado = Compra.Estado.BORRADOR
        self.compra.save(update_fields=["estado"])
        with self.assertRaisesMessage(CompraError, "moneda extranjera"):
            confirmar(self.compra)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.BORRADOR)

    def test_no_importa_mercaderia_extranjera_como_soles(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion["xml_pendiente"] = {
            "moneda_original": "USD", "empresa_id": self.empresa.pk, "receptor_ruc": self.empresa.ruc,
        }
        sesion.save()
        self.client.post(reverse("compras:importar_compra"), {"producto": "1"})
        self.assertEqual(Compra.objects.count(), 1)
        self.assertFalse(Asiento.objects.exists())

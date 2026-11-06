"""Consulta aislada de movimientos y acceso al inventario existente."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria
from core.models import Empresa
from tesoreria.models import MovimientoTesoreria


class TesoreriaVistaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.usuario = get_user_model().objects.create_user(username="consulta_tesoreria")
        cls.cuenta = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco propio", moneda="PEN")
        cls.cuenta_usd = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Cuenta dólares", moneda="USD")
        cls.cuenta_otra = CuentaTesoreria.objects.create(empresa=cls.otra, nombre="Banco ajeno", moneda="PEN")
        for cuenta, tipo, importe, concepto in [
            (cls.cuenta, "INGRESO", "100", "Cobro propio"),
            (cls.cuenta, "EGRESO", "25", "Pago propio"),
            (cls.cuenta_usd, "INGRESO", "50", "Operación dólares"),
            (cls.cuenta_otra, "INGRESO", "900", "Operación ajena"),
        ]:
            MovimientoTesoreria.objects.create(
                empresa=cuenta.empresa, cuenta=cuenta, fecha=date(2026, 11, 1),
                tipo=tipo, importe=Decimal(importe), concepto=concepto,
            )

    def setUp(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()

    def test_menu_y_resumen_por_cuenta_sin_mezclar_empresas(self):
        respuesta = self.client.get(reverse("tesoreria:movimientos"))
        self.assertContains(respuesta, reverse("reportes:inventario"))
        self.assertContains(respuesta, reverse("tesoreria:movimientos"))
        self.assertContains(respuesta, "Cobro propio")
        self.assertNotContains(respuesta, "Operación ajena")
        self.assertNotContains(respuesta, "Banco ajeno")
        filas = {fila["cuenta"].pk: fila for fila in respuesta.context["filas"]}
        self.assertEqual(filas[self.cuenta.pk]["neto"], Decimal("75"))
        self.assertEqual(filas[self.cuenta_usd.pk]["neto"], Decimal("50"))
        self.assertContains(respuesta, "no representan un saldo bancario conciliado")

    def test_filtro_cuenta_y_filtro_ajeno(self):
        respuesta = self.client.get(reverse("tesoreria:movimientos"), {"cuenta": self.cuenta.pk})
        self.assertContains(respuesta, "Pago propio")
        self.assertNotContains(respuesta, "Operación dólares")
        respuesta = self.client.get(reverse("tesoreria:movimientos"), {"cuenta": self.cuenta_otra.pk})
        self.assertNotContains(respuesta, "Operación ajena")
        self.assertContains(respuesta, "No hay movimientos para esta selección")

    def test_filtro_invalido_no_falla(self):
        respuesta = self.client.get(reverse("tesoreria:movimientos"), {"cuenta": "abc"})
        self.assertContains(respuesta, "No hay movimientos para esta selección")

    def test_paginas_no_alteran_totales(self):
        MovimientoTesoreria.objects.bulk_create([
            MovimientoTesoreria(
                empresa=self.empresa, cuenta=self.cuenta, fecha=date(2026, 11, 2),
                tipo="INGRESO", importe=1, concepto=f"Registro {indice}",
            ) for indice in range(35)
        ])
        respuesta = self.client.get(reverse("tesoreria:movimientos"), {"cuenta": self.cuenta.pk, "pagina": 2})
        self.assertEqual(respuesta.context["pagina"].paginator.count, 37)
        self.assertEqual(respuesta.context["pagina"].number, 2)
        filas = {fila["cuenta"].pk: fila for fila in respuesta.context["filas"]}
        self.assertEqual(filas[self.cuenta.pk]["neto"], Decimal("110"))

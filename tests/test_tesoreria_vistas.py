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

    def test_comparacion_muestra_candidatos_sin_conciliar_ni_crear_pagos(self):
        primero = MovimientoTesoreria.objects.get(cuenta=self.cuenta, concepto="Pago propio")
        segundo = MovimientoTesoreria.objects.create(
            empresa=self.empresa, cuenta=self.cuenta, fecha=date(2026, 11, 4),
            tipo="EGRESO", importe=25, concepto="Segundo cargo",
        )
        MovimientoTesoreria.objects.create(
            empresa=self.empresa, cuenta=self.cuenta, fecha=date(2026, 11, 5),
            tipo="EGRESO", importe=25, concepto="Fuera del rango",
        )
        MovimientoTesoreria.objects.create(
            empresa=self.otra, cuenta=self.cuenta_otra, fecha=date(2026, 11, 1),
            tipo="EGRESO", importe=25, concepto="Cargo de otra empresa",
        )
        antes = MovimientoTesoreria.objects.count()
        respuesta = self.client.post(reverse("tesoreria:comparar_banco"), {
            "cuenta": self.cuenta.pk, "fecha": "2026-11-01", "tipo": "EGRESO", "importe": "25.00",
        })
        self.assertContains(respuesta, "Pago propio")
        self.assertContains(respuesta, "Segundo cargo")
        self.assertNotContains(respuesta, "Fuera del rango")
        self.assertNotContains(respuesta, "Cargo de otra empresa")
        self.assertEqual(respuesta.context["cantidad"], 2)
        self.assertEqual(MovimientoTesoreria.objects.count(), antes)
        primero.refresh_from_db()
        segundo.refresh_from_db()
        self.assertFalse(primero.conciliado)
        self.assertFalse(segundo.conciliado)

    def test_comparacion_rechaza_cuenta_ajena_moneda_distinta_y_valores_invalidos(self):
        for cuenta, fecha, importe in [
            (self.cuenta_otra.pk, "2026-11-01", "25"),
            (self.cuenta_usd.pk, "2026-11-01", "25"),
            (self.cuenta.pk, "2026-11-01", "-25"),
            (self.cuenta.pk, "0001-01-01", "25"),
        ]:
            with self.subTest(cuenta=cuenta, fecha=fecha, importe=importe):
                respuesta = self.client.post(reverse("tesoreria:comparar_banco"), {
                    "cuenta": cuenta, "fecha": fecha, "tipo": "EGRESO", "importe": importe,
                })
                self.assertEqual(respuesta.status_code, 200)
                self.assertIsNone(respuesta.context["candidatos"])

    def test_comparacion_sin_resultados_no_declara_ausencia(self):
        respuesta = self.client.post(reverse("tesoreria:comparar_banco"), {
            "cuenta": self.cuenta.pk, "fecha": "2026-11-01", "tipo": "EGRESO", "importe": "10",
        })
        self.assertEqual(respuesta.context["cantidad"], 0)
        self.assertContains(respuesta, "Esto no demuestra que el cargo o abono no exista")

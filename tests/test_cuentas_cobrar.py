from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria
from core.models import Empresa
from tesoreria.models import MovimientoTesoreria
from ventas.cuentas_cobrar import cuentas_por_cobrar
from ventas.models import CobroVenta, CuotaVenta, NotaCredito, NotaDebito, Venta


class CuentasPorCobrarTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20000000001")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20000000002")
        cls.cuenta = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco")
        cls.venta = Venta.objects.create(
            empresa=cls.empresa,
            fecha=date(2026, 1, 1),
            serie="F001",
            numero="1",
            estado="CONFIRMADA",
            condicion="CREDITO",
            total=118,
        )
        CuotaVenta.objects.create(venta=cls.venta, numero=1, vencimiento=date(2026, 2, 1), importe=118)
        for numero, cantidad in enumerate((30, 20), 1):
            CobroVenta.objects.create(
                venta=cls.venta, fecha=date(2026, 1, 2), importe=cantidad, cuenta=cls.cuenta, canal="TRANSFERENCIA"
            )
            NotaCredito.objects.create(
                venta=cls.venta, fecha=date(2026, 1, 2), serie="FC01", numero=numero, motivo="Prueba", total=numero * 5
            )
            NotaDebito.objects.create(
                venta=cls.venta, fecha=date(2026, 1, 2), serie="FD01", numero=numero, total=numero + 1
            )
        CobroVenta.objects.create(
            venta=cls.venta, fecha=date(2026, 1, 5), importe=10, cuenta=cls.cuenta, canal="TRANSFERENCIA"
        )
        cls.ajena = Venta.objects.create(
            empresa=cls.otra,
            fecha=date(2026, 1, 1),
            serie="F001",
            numero="2",
            estado="CONFIRMADA",
            condicion="CREDITO",
            total=100,
        )

    def test_sumas_independientes_y_corte_excluye_operaciones_posteriores(self):
        cuenta = cuentas_por_cobrar(empresa=self.empresa, fecha=date(2026, 1, 2)).get(pk=self.venta.pk)
        self.assertEqual(cuenta.cobrado, Decimal("50"))
        self.assertEqual(cuenta.credito, Decimal("15"))
        self.assertEqual(cuenta.debito, Decimal("5"))
        self.assertEqual(cuenta.saldo_documentado, Decimal("58"))
        self.assertEqual(cuenta.primer_vencimiento, date(2026, 2, 1))
        self.assertEqual(
            cuentas_por_cobrar(empresa=self.empresa, fecha=date(2026, 1, 5)).get().saldo_documentado, Decimal("48")
        )
        self.assertFalse(cuentas_por_cobrar(empresa=self.empresa, fecha=date(2025, 12, 31)).exists())
        self.assertFalse(
            cuentas_por_cobrar(empresa=self.empresa, fecha=date(2026, 1, 5)).filter(pk=self.ajena.pk).exists()
        )

    def test_pantalla_filtra_empresa_y_advierten_movimientos_anteriores(self):
        MovimientoTesoreria.objects.create(
            empresa=self.empresa,
            cuenta=self.cuenta,
            fecha=date(2026, 1, 3),
            tipo="INGRESO",
            importe=10,
            origen_tipo="VENTA",
            origen_id=self.venta.pk,
        )
        user = get_user_model().objects.create_superuser(username="admin", password="test")
        self.client.force_login(user)
        url = reverse("ventas:cuentas_cobrar")
        response = self.client.get(url, {"fecha": "2026-01-02"})
        self.assertContains(response, "58,00")
        self.assertNotContains(response, "Revisar cobro anterior")
        self.assertNotContains(response, "F001-2")
        response = self.client.get(url, {"fecha": "2026-01-05"})
        self.assertContains(response, "Revisar cobro anterior")
        CobroVenta.objects.create(
            venta=self.venta, fecha=date(2026, 1, 5), importe=48,
            cuenta=self.cuenta, canal="TRANSFERENCIA",
        )
        response = self.client.get(url, {"fecha": "2026-01-05"})
        self.assertContains(response, "Revisar cobro anterior")
        self.assertContains(self.client.get(url, {"fecha": "incorrecta"}), "fecha de corte válida")

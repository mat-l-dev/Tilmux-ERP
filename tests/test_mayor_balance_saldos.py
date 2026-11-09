from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contabilidad.models import Cuenta
from contabilidad.servicios import postear_lineas
from core.models import Empresa, Perfil


class SaldosReportesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.usuario = get_user_model().objects.create_user(username="saldos")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.caja = Cuenta.objects.create(version="2026", codigo="101", nombre="Caja", elemento=1, naturaleza="D")
        cls.capital = Cuenta.objects.create(version="2026", codigo="501", nombre="Capital", elemento=5, naturaleza="A")
        cls.banco = Cuenta.objects.create(version="2026", codigo="104", nombre="Banco", elemento=1, naturaleza="D")
        ajena = Cuenta.objects.create(
            version="2026", codigo="123", nombre="Solo otra empresa", elemento=1, naturaleza="D"
        )

        def asiento(empresa, fecha, cuenta, importe, numero):
            return postear_lineas(
                empresa=empresa, fecha=fecha, tipo="APORTE_CAPITAL", glosa="Prueba",
                lineas=[(cuenta, importe, Decimal("0"), ""), (cls.capital, Decimal("0"), importe, "")],
                origen_tipo="PRUEBA", origen_id=numero,
            )

        asiento(cls.empresa, date(2026, 9, 1), cls.caja, Decimal("100"), 1)
        asiento(cls.empresa, date(2026, 10, 1), cls.caja, Decimal("30"), 2)
        asiento(cls.empresa, date(2026, 11, 1), cls.caja, Decimal("200"), 3)
        asiento(cls.empresa, date(2026, 9, 1), cls.banco, Decimal("40"), 4)
        asiento(otra, date(2026, 9, 1), cls.caja, Decimal("500"), 5)
        asiento(otra, date(2026, 9, 1), ajena, Decimal("10"), 7)
        anulado = asiento(cls.empresa, date(2026, 9, 2), cls.caja, Decimal("900"), 6)
        anulado.estado = "ANULADO"
        anulado.save(update_fields=["estado"])

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_mayor_incluye_saldo_anterior_y_no_incluye_otras_fechas_o_empresas(self):
        respuesta = self.client.get(reverse("reportes:mayor"), {"periodo": "2026-10", "cuenta": "101"})
        self.assertEqual(respuesta.context["saldo_inicial"], Decimal("100"))
        self.assertEqual(respuesta.context["saldo"], Decimal("130"))
        self.assertEqual(list(respuesta.context["movimientos"])[0]["saldo"], Decimal("130"))
        self.assertContains(respuesta, "Saldo inicial")
        sin_movimiento = self.client.get(reverse("reportes:mayor"), {"periodo": "2026-10", "cuenta": "104"})
        self.assertEqual(sin_movimiento.context["saldo"], Decimal("40"))

    def test_mayor_permite_elegir_cuenta_sin_conocer_el_codigo(self):
        respuesta = self.client.get(reverse("reportes:mayor"), {"periodo": "2026-10"})
        self.assertContains(respuesta, 'name="cuenta"')
        self.assertContains(respuesta, "101 · Caja")
        self.assertContains(respuesta, "104 · Banco")
        self.assertNotContains(respuesta, "Solo otra empresa")
        self.assertContains(respuesta, '<input type="hidden" name="periodo" value="2026-10">', html=True)

    def test_mayor_conserva_fechas_al_cambiar_cuenta(self):
        respuesta = self.client.get(reverse("reportes:mayor"), {"desde": "2026-09-01", "hasta": "2026-10-15"})
        self.assertContains(respuesta, '<input type="hidden" name="desde" value="2026-09-01">', html=True)
        self.assertContains(respuesta, '<input type="hidden" name="hasta" value="2026-10-15">', html=True)

    def test_mayor_distingue_cuenta_desconocida_de_cuenta_sin_movimiento(self):
        respuesta = self.client.get(reverse("reportes:mayor"), {"periodo": "2026-10", "cuenta": "999999"})
        self.assertContains(respuesta, "No encontramos esa cuenta")
        sin_movimiento = self.client.get(reverse("reportes:mayor"), {"periodo": "2026-10", "cuenta": "104"})
        self.assertContains(sin_movimiento, "no tiene movimientos en el rango")

    def test_balance_arrastra_saldos_y_conserva_cuentas_sin_movimiento(self):
        respuesta = self.client.get(reverse("reportes:balance"), {"periodo": "2026-10"})
        filas = {fila.codigo: fila for fila in respuesta.context["filas"]}
        self.assertEqual(filas["101"].saldo_inicial, Decimal("100"))
        self.assertEqual(filas["101"].total_debe, Decimal("30"))
        self.assertEqual(filas["101"].saldo_deudor, Decimal("130"))
        self.assertEqual(filas["104"].saldo_deudor, Decimal("40"))
        self.assertEqual(filas["501"].saldo_acreedor, Decimal("170"))
        self.assertEqual(respuesta.context["total_debe"], Decimal("30"))
        self.assertEqual(respuesta.context["total_haber"], Decimal("30"))
        self.assertEqual(respuesta.context["total_deudor"], Decimal("170"))
        self.assertEqual(respuesta.context["total_acreedor"], Decimal("170"))
        url = reverse("reportes:mayor") + "?desde=2026-10-01&amp;hasta=2026-10-31&amp;cuenta=101"
        self.assertContains(respuesta, url)

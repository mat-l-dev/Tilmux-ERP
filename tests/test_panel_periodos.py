"""El panel respeta el período y presenta ventas netas coherentes."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contabilidad.models import Cuenta
from contabilidad.servicios import postear_lineas
from core.models import Empresa, Perfil
from ventas.models import NotaCredito, NotaDebito, Venta


class PanelPeriodosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.usuario = get_user_model().objects.create_user(username="panel")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.caja = Cuenta.objects.create(codigo="101", nombre="Caja", elemento=1, naturaleza="D")
        contraparte = Cuenta.objects.create(codigo="501", nombre="Capital", elemento=5, naturaleza="A")
        for numero, (fecha, monto) in enumerate([
            (date(2026, 10, 15), Decimal("100")),
            (date(2026, 11, 15), Decimal("30")),
            (date(2026, 12, 15), Decimal("70")),
        ]):
            postear_lineas(
                empresa=cls.empresa, fecha=fecha, tipo="APORTE_CAPITAL", glosa="Prueba",
                lineas=[(cls.caja, monto, Decimal("0"), ""), (contraparte, Decimal("0"), monto, "")],
                origen_tipo="PRUEBA", origen_id=numero,
            )

        def venta(fecha, numero, subtotal):
            return Venta.objects.create(
                empresa=cls.empresa, fecha=fecha, serie="E001", numero=numero,
                estado=Venta.Estado.CONFIRMADA, subtotal=subtotal, total=subtotal,
            )

        venta(date(2025, 11, 30), "1", Decimal("80"))
        anterior = venta(date(2026, 10, 15), "2", Decimal("60"))
        venta(date(2026, 11, 30), "3", Decimal("100"))
        NotaCredito.objects.create(
            venta=anterior, fecha=date(2026, 11, 30), serie="FC01", numero="1", motivo="Devolución", base=10,
        )
        NotaDebito.objects.create(venta=anterior, fecha=date(2026, 11, 30), serie="FD01", numero="1", base=5)

    def setUp(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()

    def test_corte_de_saldo_y_ventas_netas_en_ultimo_dia(self):
        respuesta = self.client.get(reverse("core:panel"), {"periodo": "2026-11"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["saldo_tesoreria"], "130,00")
        self.assertEqual(respuesta.context["ventas_mes"], "95,00")
        self.assertEqual(respuesta.context["ventas_acumulado"], "155,00")
        self.assertEqual(respuesta.context["ventas_anterior"], "80,00")
        self.assertEqual(respuesta.context["variacion"], Decimal("18.8"))
        self.assertEqual(respuesta.context["serie_meses"][-1]["valor"], Decimal("95"))
        self.assertContains(respuesta, "no es saldo bancario conciliado")
        self.assertContains(respuesta, "Verifica que los respaldos automáticos")
        self.assertNotContains(respuesta, "Respaldo diario programado")

    def test_pendientes_explica_alcance_de_la_revision(self):
        respuesta = self.client.get(reverse("core:pendientes"))
        self.assertContains(respuesta, "Esta lista revisa datos incompletos de compras")
        self.assertContains(respuesta, "consulta Compras y Tesorería")

    def test_octubre_no_incluye_movimientos_posteriores(self):
        respuesta = self.client.get(reverse("core:panel"), {"periodo": "2026-10"})
        self.assertEqual(respuesta.context["saldo_tesoreria"], "100,00")
        self.assertEqual(respuesta.context["ventas_mes"], "60,00")
        self.assertEqual(respuesta.context["serie_meses"][-1]["valor"], Decimal("60"))

    def test_periodo_invalido_no_produce_error(self):
        for periodo in ["2026-00", "2026-13", "0000-11", "99999-01"]:
            with self.subTest(periodo=periodo):
                respuesta = self.client.get(reverse("core:panel"), {"periodo": periodo})
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "período indicado no es válido")

    def test_neto_negativo_se_muestra_sin_barra_negativa(self):
        venta = Venta.objects.get(empresa=self.empresa, numero="3")
        NotaCredito.objects.create(
            venta=venta, fecha=date(2026, 12, 31), serie="FC01", numero="2", motivo="Devolución", base=100,
        )
        respuesta = self.client.get(reverse("core:panel"), {"periodo": "2026-12"})
        punto = respuesta.context["serie_meses"][-1]
        self.assertEqual(punto["valor"], Decimal("-100"))
        self.assertEqual(punto["altura"], 0)

"""La numeración de las notas pertenece a la empresa, no a cada venta."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, Perfil
from ventas.models import NotaCredito, NotaDebito, Venta
from ventas.servicios import VentaError, _validar_numeracion_nota, emitir_nota_credito, emitir_nota_debito


class NumeracionNotasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        cls.primera = Venta.objects.create(
            empresa=cls.empresa,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="E001",
            numero="1",
            estado=Venta.Estado.CONFIRMADA,
        )
        cls.segunda = Venta.objects.create(
            empresa=cls.empresa,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="E001",
            numero="2",
            estado=Venta.Estado.CONFIRMADA,
        )

    def test_rechaza_nota_credito_repetida_en_otra_venta(self):
        NotaCredito.objects.create(
            venta=self.primera, fecha=date(2026, 10, 2), serie="FC01", numero="00001", motivo="Devolución"
        )
        with self.assertRaisesRegex(VentaError, "registrada"):
            emitir_nota_credito(
                venta=self.segunda, fecha=date(2026, 10, 3), serie="fc01", numero="1", motivo_codigo="07"
            )

    def test_rechaza_nota_debito_repetida_en_otra_venta(self):
        NotaDebito.objects.create(
            venta=self.primera, fecha=date(2026, 10, 2), serie="FD01", numero="00001", motivo_codigo="01"
        )
        with self.assertRaisesRegex(VentaError, "registrada"):
            emitir_nota_debito(
                venta=self.segunda,
                fecha=date(2026, 10, 3),
                serie="fd01",
                numero="1",
                motivo_codigo="01",
                base=Decimal("10"),
                igv=Decimal("1.80"),
            )

    def test_puede_usarse_igual_numero_en_otra_empresa(self):
        NotaCredito.objects.create(
            venta=self.primera, fecha=date(2026, 10, 2), serie="FC01", numero="00001", motivo="Devolución"
        )
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra SAC", ruc="20123456780")
        venta = Venta.objects.create(
            empresa=otra,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="E001",
            numero="1",
            estado=Venta.Estado.CONFIRMADA,
        )
        self.assertEqual(_validar_numeracion_nota(venta, NotaCredito, "fc01", "1"), ("FC01", "1"))

    def test_no_se_permite_nota_sin_numero(self):
        with self.assertRaisesRegex(VentaError, "número"):
            emitir_nota_debito(
                venta=self.segunda,
                fecha=date(2026, 10, 3),
                serie="FD01",
                numero=" ",
                motivo_codigo="01",
                base=Decimal("10"),
                igv=Decimal("1.80"),
            )

    def test_formularios_no_inventan_la_serie_de_la_nota(self):
        usuario = get_user_model().objects.create_user(username="registro")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        for nombre in ("nota_credito", "nota_debito"):
            with self.subTest(tipo=nombre):
                respuesta = self.client.get(reverse(f"ventas:{nombre}", args=[self.primera.pk]))
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(respuesta, 'value="FC01"')
                self.assertNotContains(respuesta, 'value="FD01"')

    def test_admin_es_solo_consulta_para_ventas_y_notas(self):
        nota = NotaCredito.objects.create(
            venta=self.primera, fecha=date(2026, 10, 2), serie="FC01", numero="1", motivo="Devolución"
        )
        usuario = get_user_model().objects.create_superuser(username="administrador", password="prueba")
        self.client.force_login(usuario)
        for nombre, objeto in (("venta", self.primera), ("notacredito", nota)):
            with self.subTest(tipo=nombre):
                cambio = reverse(f"admin:ventas_{nombre}_change", args=[objeto.pk])
                self.assertEqual(self.client.get(cambio).status_code, 200)
                self.assertEqual(self.client.post(cambio, {"total": "999"}).status_code, 403)
                self.assertEqual(self.client.post(reverse(f"admin:ventas_{nombre}_add"), {}).status_code, 403)

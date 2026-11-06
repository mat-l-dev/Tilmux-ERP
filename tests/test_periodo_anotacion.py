"""El período tributario puede diferir de la fecha del comprobante."""

import csv
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Tercero
from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.models import Cuenta
from core.models import Empresa, HistorialDocumento, Periodo
from reportes.casillas import calcular


class PeriodoAnotacionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cls.cuenta = Cuenta.objects.create(codigo="6391", nombre="Gasto", elemento=6, naturaleza="D")
        cls.usuario = get_user_model().objects.create_user(username="periodo")
        cls.compra = Compra.objects.create(
            empresa=cls.empresa,
            proveedor=cls.proveedor,
            fecha=date(2026, 10, 15),
            serie="F001",
            numero="1",
            estado=Compra.Estado.CONFIRMADA,
            subtotal=Decimal("100"),
            igv=Decimal("18"),
            total=Decimal("118"),
        )
        cls.gasto = Gasto.objects.create(
            empresa=cls.empresa,
            proveedor=cls.proveedor,
            cuenta=cls.cuenta,
            fecha=date(2026, 10, 16),
            serie="F002",
            numero="2",
            base=Decimal("50"),
            igv=Decimal("9"),
            total=Decimal("59"),
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_periodo_explicito_cambia_621_y_registro_sin_cambiar_fecha_documento(self):
        for clase, documento in (("compra", self.compra), ("gasto", self.gasto)):
            respuesta = self.client.post(
                reverse("compras:anotacion", args=[clase, documento.pk]),
                {
                    "fecha_anotacion": "2026-11-10",
                },
            )
            self.assertEqual(respuesta.status_code, 302)
        self.compra.refresh_from_db()
        self.gasto.refresh_from_db()
        self.assertEqual(self.compra.fecha, date(2026, 10, 15))
        self.assertEqual(self.gasto.fecha, date(2026, 10, 16))
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_base"], Decimal("0"))
        self.assertEqual(calcular(self.empresa, 2026, 11)["compras_base"], Decimal("150"))
        self.assertEqual(calcular(self.empresa, 2026, 11)["compras_igv"], Decimal("27"))
        self.assertEqual(HistorialDocumento.objects.filter(empresa=self.empresa, accion="ANOTACION").count(), 2)
        registro = self.client.get(reverse("reportes:registro_compras"), {"periodo": "2026-11"})
        self.assertContains(registro, "F001-1")
        self.assertContains(registro, "F002-2")
        exportacion = self.client.get(reverse("reportes:exportar_compras"), {"periodo": "2026-11"})
        filas = list(csv.DictReader(io.StringIO(exportacion.content.decode("utf-8-sig"))))
        self.assertEqual({fila["periodo"] for fila in filas}, {"20261100"})
        self.assertEqual({fila["fecha"] for fila in filas}, {"2026-10-15", "2026-10-16"})
        self.client.post(
            reverse("compras:anotacion", args=["compra", self.compra.pk]),
            {
                "fecha_anotacion": "2026-11-10",
            },
        )
        self.assertEqual(HistorialDocumento.objects.filter(empresa=self.empresa, accion="ANOTACION").count(), 2)

    def test_por_defecto_estima_el_periodo_desde_emision(self):
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_base"], Decimal("150"))
        self.assertEqual(calcular(self.empresa, 2026, 11)["compras_base"], Decimal("0"))

    def test_no_permite_mover_anotacion_a_periodo_cerrado(self):
        Periodo.objects.create(empresa=self.empresa, anio=2026, mes=11, estado=Periodo.Estado.CERRADO)
        respuesta = self.client.post(
            reverse("compras:anotacion", args=["compra", self.compra.pk]),
            {
                "fecha_anotacion": "2026-11-10",
            },
            follow=True,
        )
        self.assertContains(respuesta, "cerrado")
        self.compra.refresh_from_db()
        self.assertIsNone(self.compra.fecha_anotacion)

    def test_no_permite_anotar_en_un_mes_anterior_a_emision(self):
        respuesta = self.client.post(
            reverse("compras:anotacion", args=["gasto", self.gasto.pk]),
            {
                "fecha_anotacion": "2026-09-30",
            },
            follow=True,
        )
        self.assertContains(respuesta, "anterior")
        self.gasto.refresh_from_db()
        self.assertIsNone(self.gasto.fecha_anotacion)

    def test_no_modifica_documentos_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra SAC", ruc="20123456780")
        compra = Compra.objects.create(
            empresa=otra,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            serie="F001",
            numero="55",
            estado=Compra.Estado.CONFIRMADA,
        )
        respuesta = self.client.post(
            reverse("compras:anotacion", args=["compra", compra.pk]),
            {
                "fecha_anotacion": "2026-11-10",
            },
        )
        self.assertEqual(respuesta.status_code, 404)
        compra.refresh_from_db()
        self.assertIsNone(compra.fecha_anotacion)

    def test_no_permite_cambiar_el_periodo_de_origen_cerrado(self):
        Periodo.objects.create(empresa=self.empresa, anio=2026, mes=10, estado=Periodo.Estado.CERRADO)
        respuesta = self.client.post(
            reverse("compras:anotacion", args=["gasto", self.gasto.pk]),
            {
                "fecha_anotacion": "2026-11-10",
            },
            follow=True,
        )
        self.assertContains(respuesta, "cerrado")
        self.gasto.refresh_from_db()
        self.assertIsNone(self.gasto.fecha_anotacion)

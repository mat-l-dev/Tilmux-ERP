import csv
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria, Tercero
from compras.models import Compra
from compras.models_gasto import Gasto
from compras.servicios import CompraError, confirmar, registrar_gasto
from contabilidad.models import Cuenta
from core.models import Empresa, Perfil
from reportes.casillas import calcular, casillas_documento


class RevisionTributariaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cls.cuenta = Cuenta.objects.create(codigo="6391", nombre="Gasto", elemento=6, naturaleza="D")
        cls.medio = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco")
        cls.usuario = get_user_model().objects.create_user(username="reporte")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.boleta = Compra.objects.create(
            empresa=cls.empresa, proveedor=cls.proveedor, fecha=date(2026, 10, 1), tipo_doc="BOLETA",
            serie="B001", numero="1", estado="CONFIRMADA", con_credito=False,
            subtotal=100, igv=18, total=118,
        )
        cls.factura = Gasto.objects.create(
            empresa=cls.empresa, proveedor=cls.proveedor, fecha=date(2026, 10, 2), tipo_doc="FACTURA",
            serie="F001", numero="2", estado="PAGADO", cuenta=cls.cuenta, con_credito=True,
            base=100, igv=18, total=118,
        )
        cls.inconsistente = Gasto.objects.create(
            empresa=cls.empresa, proveedor=cls.proveedor, fecha=date(2026, 10, 3), tipo_doc="BOLETA",
            serie="B001", numero="3", estado="PAGADO", cuenta=cls.cuenta, con_credito=True,
            base=50, igv=9, total=59,
        )

    def test_pantalla_csv_y_estimacion_coinciden_sin_marcar_boleta_completa_como_pendiente(self):
        self.client.force_login(self.usuario)
        periodo = {"periodo": "2026-10"}
        respuesta = self.client.get(reverse("reportes:registro_compras"), periodo)
        self.assertContains(respuesta, "Incluido en estimación")
        filas = {f["documento"]: f for f in respuesta.context["filas"]}
        self.assertFalse(filas["B001-1"]["credito"])
        self.assertFalse(filas["B001-1"]["pendiente"])
        self.assertTrue(filas["B001-3"]["pendiente"])
        self.assertFalse(filas["B001-3"]["credito"])
        self.assertTrue(filas["F001-2"]["credito"])
        exportacion = self.client.get(reverse("reportes:exportar_compras"), periodo)
        filas_csv = {f["numero"]: f for f in csv.DictReader(io.StringIO(exportacion.content.decode("utf-8-sig")))}
        self.assertEqual(filas_csv["1"]["pendiente"], "No")
        self.assertEqual(filas_csv["3"]["pendiente"], "Sí")
        self.assertEqual(filas_csv["3"]["credito"], "No")
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_igv"], Decimal("18"))
        self.assertEqual(casillas_documento(self.boleta)[0]["casilla"], "—")

    def test_servicios_no_aceptan_boleta_marcada_con_credito(self):
        compra = Compra.objects.create(
            empresa=self.empresa, proveedor=self.proveedor, fecha=date(2026, 10, 4),
            tipo_doc="BOLETA", serie="B002", numero="4", con_credito=True,
        )
        with self.assertRaisesMessage(CompraError, "solo admite crédito fiscal en facturas"):
            confirmar(compra)
        with self.assertRaisesMessage(CompraError, "solo admite crédito fiscal en facturas"):
            registrar_gasto(
                empresa=self.empresa, proveedor=self.proveedor, fecha=date(2026, 10, 4), tipo_doc="BOLETA",
                serie="B002", numero="5", base=100, igv=18, total=118, cuenta=self.cuenta,
                medio=self.medio, con_credito=True,
            )
        self.assertFalse(Gasto.objects.filter(serie="B002", numero="5").exists())

    def test_ruc_con_caracteres_no_numericos_no_se_considera_valido(self):
        self.proveedor.numero_doc = "2010000000X"
        self.proveedor.save(update_fields=["numero_doc"])
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_igv"], Decimal("0"))

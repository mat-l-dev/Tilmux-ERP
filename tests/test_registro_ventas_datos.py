import csv
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Tercero
from core.models import Empresa, Perfil
from ventas.models import NotaCredito, NotaDebito, Venta


class RegistroVentasDatosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        usuario = get_user_model().objects.create_user(username="registro_ventas")
        Perfil.objects.create(usuario=usuario, empresa=cls.empresa)
        cls.usuario = usuario
        cliente_ce = Tercero.objects.create(rol="CLIENTE", tipo_doc="CE", numero_doc="X12345", nombre="Cliente CE")
        cliente_pas = Tercero.objects.create(rol="CLIENTE", tipo_doc="PAS", numero_doc="P12345", nombre="Cliente PAS")
        cls.venta_pen = Venta.objects.create(
            empresa=cls.empresa, fecha=date(2026, 10, 1), serie="B001", numero="1", estado="CONFIRMADA",
            cliente=cliente_ce, moneda="PEN", subtotal=100, igv=18, total=118,
        )
        cls.venta_usd = Venta.objects.create(
            empresa=cls.empresa, fecha=date(2026, 10, 2), serie="B001", numero="2", estado="CONFIRMADA",
            cliente=cliente_pas, moneda="USD", subtotal=50, igv=9, total=59,
        )
        Venta.objects.create(empresa=cls.empresa, fecha=date(2026, 10, 3), serie="B001", numero="3",
                             estado="CONFIRMADA", subtotal=0, igv=0, total=0)
        NotaCredito.objects.create(venta=cls.venta_pen, fecha=date(2026, 10, 4), serie="BC01", numero="1",
                                   motivo="Devolución", base=10, igv=Decimal("1.80"), total=Decimal("11.80"))
        NotaDebito.objects.create(venta=cls.venta_usd, fecha=date(2026, 10, 4), serie="BD01", numero="1",
                                  base=5, igv=Decimal("0.90"), total=Decimal("5.90"))

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_reporte_separa_monedas_y_muestra_cliente_en_ventas_y_notas(self):
        respuesta = self.client.get(reverse("reportes:registro_ventas"), {"periodo": "2026-10"})
        totales = {f["moneda"]: f for f in respuesta.context["totales_por_moneda"]}
        self.assertEqual(totales["PEN"]["total"], Decimal("106.20"))
        self.assertEqual(totales["USD"]["total"], Decimal("64.90"))
        self.assertContains(respuesta, "Cliente CE", count=2)
        self.assertContains(respuesta, "Cliente PAS", count=2)
        self.assertContains(respuesta, "sin convertirlos")

    def test_csv_identifica_ce_pasaporte_y_cliente_no_identificado(self):
        respuesta = self.client.get(reverse("reportes:exportar_ventas"), {"periodo": "2026-10"})
        filas = list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8-sig"))))
        documentos = {(f["serie"], f["numero"]): f for f in filas}
        self.assertEqual(documentos[("B001", "1")]["tipo_doc_cliente"], "04")
        self.assertEqual(documentos[("BC01", "1")]["tipo_doc_cliente"], "04")
        self.assertEqual(documentos[("B001", "2")]["tipo_doc_cliente"], "07")
        self.assertEqual(documentos[("BD01", "1")]["tipo_doc_cliente"], "07")
        self.assertEqual(documentos[("B001", "3")]["tipo_doc_cliente"], "")
        self.assertEqual(documentos[("B001", "1")]["cliente"], "Cliente CE")

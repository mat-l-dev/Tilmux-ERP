from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Tercero
from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.models import Cuenta
from core.models import Empresa, Perfil
from reportes.casillas import calcular
from ventas.models import NotaCredito, Venta


class ConciliacionBoletasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cuenta = Cuenta.objects.create(codigo="6391", nombre="Gasto", elemento=6, naturaleza="D")
        cls.usuario = get_user_model().objects.create_user(username="sire")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        Gasto.objects.create(
            empresa=cls.empresa,
            proveedor=cls.proveedor,
            cuenta=cuenta,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="1",
            base=43,
            igv=0,
            total=43,
            con_credito=True,
        )
        Gasto.objects.create(
            empresa=cls.empresa,
            proveedor=cls.proveedor,
            cuenta=cuenta,
            fecha=date(2026, 10, 31),
            tipo_doc="BOLETA",
            serie="B001",
            numero="00393302",
            base=Decimal("198.04"),
            igv=0,
            total=Decimal("198.04"),
            con_credito=False,
            deducible=False,
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def conciliar(self, texto, registro="compras"):
        archivo = SimpleUploadedFile("propuesta.csv", texto.encode("utf-8"))
        return self.client.post(
            reverse("reportes:conciliacion_archivo"),
            {
                "anio": "2026",
                "mes": "10",
                "registro": registro,
                "archivo": archivo,
            },
        )

    def test_boleta_en_documentos_no_aumenta_credito_igv(self):
        cabecera = "RUC,Periodo,BI Gravada,IGV,Importe Total\n"
        factura = "20123456789,202610,0,0,43.00\n"
        boleta = "20123456789,202610,0,0,198.04\n"
        respuesta = self.conciliar(cabecera + factura)
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["sistema_total"], Decimal("241.04"))
        self.assertEqual(resultado["documentos_sin_credito"], Decimal("198.04"))
        self.assertEqual(resultado["dif_total"], Decimal("198.04"))
        self.assertEqual(resultado["dif_igv"], 0)
        respuesta = self.conciliar(cabecera + factura + boleta)
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["dif_total"], 0)
        self.assertEqual(resultado["dif_igv"], 0)
        self.assertTrue(resultado["cuadra"])
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_igv"], 0)

    def test_sin_columna_de_total_no_afirma_conciliacion_documental(self):
        contenido = "RUC,Periodo,BI Gravada,IGV\n20123456789,202610,0,0\n"
        respuesta = self.conciliar(contenido)
        self.assertFalse(respuesta.context["resultado"]["cuadra"])
        self.assertContains(respuesta, "No comparable")

    def test_otra_moneda_no_se_compara_como_soles(self):
        Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 5),
            tipo_doc="FACTURA",
            serie="F002",
            numero="4",
            estado="CONFIRMADA",
            moneda="USD",
            subtotal=50,
            igv=9,
            total=59,
        )
        contenido = "RUC,Periodo,BI Gravada,IGV,Importe Total\n20123456789,202610,0,0,241.04\n"
        respuesta = self.conciliar(contenido)
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["otras_monedas"], 1)
        self.assertIsNone(resultado["dif_total"])
        self.assertIsNone(resultado["dif_igv"])
        self.assertFalse(resultado["cuadra"])

    def test_nota_de_venta_de_otro_periodo_se_descuenta_en_la_comparacion(self):
        venta = Venta.objects.create(
            empresa=self.empresa,
            fecha=date(2026, 9, 1),
            tipo_doc="BOLETA",
            serie="B001",
            numero="9",
            estado="CONFIRMADA",
            subtotal=100,
            igv=18,
            total=118,
        )
        NotaCredito.objects.create(
            venta=venta,
            fecha=date(2026, 10, 1),
            serie="BC01",
            numero="1",
            motivo="Devolución",
            base=10,
            igv=Decimal("1.80"),
            total=Decimal("11.80"),
        )
        contenido = "RUC,Periodo,BI Gravada,IGV,Importe Total\n20123456789,202610,-10,-1.80,-11.80\n"
        respuesta = self.conciliar(contenido, registro="ventas")
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["dif_base"], 0)
        self.assertEqual(resultado["dif_igv"], 0)
        self.assertEqual(resultado["dif_total"], 0)
        self.assertTrue(resultado["cuadra"])

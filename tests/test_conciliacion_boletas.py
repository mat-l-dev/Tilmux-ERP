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
        cabecera = "RUC,Periodo,Moneda,BI Gravada,IGV,Importe Total\n"
        factura = "20123456789,202610,PEN,0,0,43.00\n"
        boleta = "20123456789,202610,PEN,0,0,198.04\n"
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

    def test_compara_identidad_aunque_los_totales_coincidan(self):
        cabecera = ("RUC,Periodo,Tipo CP/Doc.,Serie del CDP,Nro CP o Doc. Nro Inicial (Rango),"
                    "Nro Final (Rango),Tipo Doc Identidad,Nro Doc Identidad,Fecha de emisión,"
                    "BI Gravado DG,IGV / IPM DG,Total CP,Moneda\n")
        factura = "20123456789,202610,01,F001,00000001,,6,20100000001,01/10/2026,0,0,43.00,PEN\n"
        otra_boleta = "20123456789,202610,03,B002,00393302,,6,20100000001,31/10/2026,0,0,198.04,PEN\n"
        respuesta = self.conciliar(cabecera + factura + otra_boleta)
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["dif_total"], 0)
        self.assertFalse(resultado["cuadra"])
        self.assertEqual(resultado["documentos"]["coinciden"], 1)
        self.assertEqual(len(resultado["documentos"]["solo_sistema"]), 1)
        self.assertEqual(len(resultado["documentos"]["solo_archivo"]), 1)
        self.assertContains(respuesta, "B001-393302")
        self.assertContains(respuesta, "B002-393302")
        self.assertEqual(calcular(self.empresa, 2026, 10)["compras_igv"], 0)

    def test_comparacion_detecta_fecha_importe_y_duplicados(self):
        cabecera = ("RUC,Periodo,Tipo CP/Doc.,Serie del CDP,Nro CP o Doc. Nro Inicial (Rango),"
                    "Nro Final (Rango),Tipo Doc Identidad,Nro Doc Identidad,Fecha de emisión,"
                    "BI Gravado DG,IGV / IPM DG,Total CP,Moneda\n")
        factura = "20123456789,202610,01,F001,1,,6,20100000001,02/10/2026,0,0,42.00,PEN\n"
        boleta = "20123456789,202610,03,B001,393302,,6,20100000001,31/10/2026,0,0,198.04,PEN\n"
        respuesta = self.conciliar(cabecera + factura + boleta + boleta)
        documentos = respuesta.context["resultado"]["documentos"]
        self.assertEqual(len(documentos["diferentes"]), 1)
        self.assertEqual(len(documentos["ambiguos"]), 1)
        self.assertFalse(respuesta.context["resultado"]["cuadra"])
        self.assertContains(respuesta, "Identificación duplicada")

    def test_tipo_no_admitido_no_se_da_por_comparado(self):
        cabecera = ("RUC,Periodo,Tipo CP/Doc.,Serie del CDP,Nro CP o Doc. Nro Inicial (Rango),"
                    "Nro Final (Rango),Tipo Doc Identidad,Nro Doc Identidad,Fecha de emisión,"
                    "BI Gravado DG,IGV / IPM DG,Total CP,Moneda\n")
        nota = "20123456789,202610,07,FC01,1,,6,20100000001,02/10/2026,0,0,10.00,PEN\n"
        sin_ruc = "20123456789,202610,03,B001,1,,1,20100000001,02/10/2026,0,0,10.00,PEN\n"
        rango = "20123456789,202610,03,B001,2,5,6,20100000001,02/10/2026,0,0,10.00,PEN\n"
        respuesta = self.conciliar(cabecera + nota + sin_ruc + rango)
        self.assertEqual(respuesta.context["resultado"]["documentos"]["omitidos_archivo"], 3)
        self.assertContains(respuesta, "Comparación incompleta")

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
        contenido = "RUC,Periodo,Moneda,BI Gravada,IGV,Importe Total\n20123456789,202610,PEN,0,0,241.04\n"
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
        contenido = "RUC,Periodo,Moneda,BI Gravada,IGV,Importe Total\n20123456789,202610,PEN,-10,-1.80,-11.80\n"
        respuesta = self.conciliar(contenido, registro="ventas")
        resultado = respuesta.context["resultado"]
        self.assertEqual(resultado["dif_base"], 0)
        self.assertEqual(resultado["dif_igv"], 0)
        self.assertEqual(resultado["dif_total"], 0)
        self.assertTrue(resultado["cuadra"])

    def test_moneda_ausente_o_dolar_no_se_presenta_como_conciliada(self):
        for contenido in (
            "RUC,Periodo,BI Gravada,IGV,Importe Total\n20123456789,202610,0,0,241.04\n",
            "RUC,Periodo,Moneda,BI Gravada,IGV,Importe Total\n20123456789,202610,USD,0,0,241.04\n",
        ):
            with self.subTest(contenido=contenido):
                respuesta = self.conciliar(contenido)
                self.assertFalse(respuesta.context["resultado"]["cuadra"])
                self.assertIsNone(respuesta.context["resultado"]["dif_total"])
                self.assertContains(respuesta, "No se pudo verificar")

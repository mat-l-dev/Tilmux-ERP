from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto, Tercero, UnidadMedida
from compras.models import Compra
from core.models import Empresa, Perfil
from ventas.models import Venta


class LineasDocumentosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.usuario = get_user_model().objects.create_user(username="lineas")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        cls.producto = Producto.objects.create(sku="TEST", nombre="Producto", unidad=unidad, activo=True)

    def setUp(self):
        self.client.force_login(self.usuario)

    def compra(self):
        return {
            "fecha": "2026-10-01", "tipo_doc": "FACTURA", "serie": "F001", "numero": "1",
            "proveedor_ruc": "20100000001", "proveedor_nombre": "Proveedor nuevo",
            "linea_producto": [str(self.producto.pk)], "linea_cantidad": ["1"], "linea_precio": ["100"],
            "linea_descripcion": ["Equipo"],
        }

    def venta(self):
        return {
            "fecha": "2026-10-01", "tipo_doc": "BOLETA", "serie": "B001", "numero": "1",
            "condicion": "CREDITO", "linea_producto": [str(self.producto.pk)],
            "linea_cantidad": ["1"], "linea_precio": ["100"], "linea_descripcion": ["Equipo"],
        }

    def test_lineas_incompletas_no_crean_documento_ni_proveedor(self):
        for ruta, datos in (("compras:nueva", self.compra()), ("ventas:nueva", self.venta())):
            datos["linea_producto"].append(str(self.producto.pk))
            respuesta = self.client.post(reverse(ruta), datos)
            self.assertContains(respuesta, "líneas están incompletas")
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(Venta.objects.exists())
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())

    def test_numeros_invalidos_no_rompen_el_formulario_ni_guardan(self):
        for ruta, fabrica in (("compras:nueva", self.compra), ("ventas:nueva", self.venta)):
            for valor in ("NaN", "Infinity", "0.00001", "99999999999999999999"):
                datos = fabrica()
                datos["linea_cantidad"] = [valor]
                respuesta = self.client.post(reverse(ruta), datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "revisa producto, cantidad y precio")
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(Venta.objects.exists())
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())

    def test_costo_con_datos_incompletos_no_se_omite(self):
        datos = self.compra() | {"costo_concepto": [""], "costo_base": [""], "costo_igv": ["10"]}
        respuesta = self.client.post(reverse("compras:nueva"), datos)
        self.assertContains(respuesta, "importes inválidos")
        self.assertFalse(Compra.objects.exists())
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())

    def test_conserva_datos_para_corregir_y_rechaza_descripcion_huerfana(self):
        datos = self.compra() | {"costo_concepto": ["Flete"], "costo_base": ["incorrecto"], "costo_igv": ["1"]}
        respuesta = self.client.post(reverse("compras:nueva"), datos)
        self.assertContains(respuesta, 'value="incorrecto"')
        self.assertContains(respuesta, 'value="Proveedor nuevo"')
        venta = self.venta()
        venta["linea_descripcion"].append("Descripción sin línea")
        respuesta = self.client.post(reverse("ventas:nueva"), venta)
        self.assertContains(respuesta, "descripciones sin una línea")
        self.assertFalse(Venta.objects.exists())

    def test_una_compra_valida_crea_proveedor_y_borrador(self):
        respuesta = self.client.post(reverse("compras:nueva"), self.compra())
        self.assertEqual(respuesta.status_code, 302)
        compra = Compra.objects.get()
        self.assertEqual(compra.proveedor.numero_doc, "20100000001")
        self.assertEqual(compra.lineas.count(), 1)

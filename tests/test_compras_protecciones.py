"""Protecciones de compras entre empresas y períodos contables."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto, Tercero, UnidadMedida
from compras.models import Compra
from contabilidad.models import Asiento
from core.models import Empresa, HistorialDocumento, Perfil, Periodo
from inventario.models import CapaFIFO, MovimientoStock


class ProteccionesCompraTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A SAC", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B SAC", ruc="20123456780")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor")
        cls.usuario = get_user_model().objects.create_user(username="compras")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.compra = Compra.objects.create(
            empresa=cls.empresa, proveedor=cls.proveedor, fecha=date(2026, 10, 15),
            serie="F001", numero="1", estado=Compra.Estado.CONFIRMADA, glosa="Original",
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_acciones_rechazan_compra_de_otra_empresa(self):
        compra = Compra.objects.create(
            empresa=self.otra, proveedor=self.proveedor, fecha=date(2026, 10, 15),
            estado=Compra.Estado.CONFIRMADA,
        )
        for nombre, metodo in [("pagar", "get"), ("pagar", "post"), ("confirmar", "post"),
                               ("corregir", "get"), ("corregir", "post"), ("anular", "post")]:
            with self.subTest(accion=nombre, metodo=metodo):
                respuesta = getattr(self.client, metodo)(reverse(f"compras:{nombre}", args=[compra.pk]))
                self.assertEqual(respuesta.status_code, 404)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, Compra.Estado.CONFIRMADA)

    def test_anulacion_no_borra_historial_de_inventario(self):
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        producto = Producto.objects.create(sku="PRUEBA", nombre="Producto", unidad=unidad)
        capa = CapaFIFO.objects.create(
            empresa=self.empresa, producto=producto, fecha=self.compra.fecha,
            cantidad_inicial=1, cantidad_restante=1, costo_unitario=10,
            origen_tipo="COMPRA", origen_id=self.compra.pk,
        )
        movimiento = MovimientoStock.objects.create(
            empresa=self.empresa, producto=producto, fecha=self.compra.fecha, tipo="ENTRADA",
            cantidad=1, costo_unitario=10, costo_total=10, origen_tipo="COMPRA", origen_id=self.compra.pk,
        )
        respuesta = self.client.post(reverse("compras:anular", args=[self.compra.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.CONFIRMADA)
        self.assertTrue(CapaFIFO.objects.filter(pk=capa.pk).exists())
        self.assertTrue(MovimientoStock.objects.filter(pk=movimiento.pk).exists())

    def test_no_corrige_compra_si_periodo_de_anotacion_esta_cerrado(self):
        self.compra.fecha_anotacion = date(2026, 11, 1)
        self.compra.save(update_fields=["fecha_anotacion"])
        Periodo.objects.create(empresa=self.empresa, anio=2026, mes=11, estado=Periodo.Estado.CERRADO)
        respuesta = self.client.post(reverse("compras:corregir", args=[self.compra.pk]), {"glosa": "Alterada"})
        self.assertEqual(respuesta.status_code, 302)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.glosa, "Original")
        self.assertFalse(HistorialDocumento.objects.filter(documento_id=self.compra.pk, accion="CORRECCION").exists())

    def test_no_modifica_glosa_de_pago_en_periodo_cerrado(self):
        periodo = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=12, estado=Periodo.Estado.CERRADO)
        asiento = Asiento.objects.create(
            empresa=self.empresa, periodo=periodo, numero=1, fecha=date(2026, 12, 1),
            tipo_operacion="PAGO_PROVEEDOR", glosa="Pago original", origen_tipo="COMPRA_PAGO",
            origen_id=self.compra.pk,
        )
        self.client.post(reverse("compras:corregir", args=[self.compra.pk]), {"glosa": "Alterada"})
        self.compra.refresh_from_db()
        asiento.refresh_from_db()
        self.assertEqual(self.compra.glosa, "Original")
        self.assertEqual(asiento.glosa, "Pago original")

    def test_corrige_en_periodo_abierto_y_deja_historial(self):
        Periodo.objects.create(empresa=self.empresa, anio=2026, mes=10)
        self.client.post(reverse("compras:corregir", args=[self.compra.pk]), {"glosa": "Actualizada"})
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.glosa, "Actualizada")
        self.assertTrue(HistorialDocumento.objects.filter(documento_id=self.compra.pk, accion="CORRECCION").exists())

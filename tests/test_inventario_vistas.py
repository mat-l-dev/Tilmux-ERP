from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Empresa, Perfil
from inventario.models import CapaFIFO
from inventario.servicios import entrar, salir

from .test_invariantes import BaseContable


class InventarioVistaTest(BaseContable):
    def setUp(self):
        usuario = get_user_model().objects.create_user(username="inventario_vista")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        self.fecha = date(2026, 11, 1)

    def test_agotado_conserva_acceso_al_kardex_y_busqueda(self):
        entrar(empresa=self.empresa, producto=self.producto, fecha=self.fecha,
               cantidad=Decimal("2"), costo_unitario=Decimal("10"))
        salir(empresa=self.empresa, producto=self.producto, fecha=self.fecha, cantidad=Decimal("2"))
        respuesta = self.client.get(reverse("reportes:inventario"), {"q": self.producto.sku})
        fila = next(f for f in respuesta.context["filas"] if f["producto"] == self.producto)
        self.assertEqual(fila["cantidad"], 0)
        self.assertFalse(fila["diferencia"])
        self.assertContains(respuesta, "Agotado")
        self.assertContains(respuesta, reverse("reportes:kardex", args=[self.producto.pk]))
        self.assertEqual(respuesta.context["total_valor"], 0)

    def test_advierte_diferencia_y_aisla_movimientos_de_otra_empresa(self):
        capa = entrar(empresa=self.empresa, producto=self.producto, fecha=self.fecha,
                      cantidad=Decimal("2"), costo_unitario=Decimal("10"))
        CapaFIFO.objects.filter(pk=capa.pk).update(cantidad_restante=Decimal("1"))
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra", ruc="20123456780")
        entrar(empresa=otra, producto=self.producto, fecha=self.fecha,
               cantidad=Decimal("10"), costo_unitario=Decimal("10"))
        respuesta = self.client.get(reverse("reportes:inventario"), {"q": self.producto.sku})
        fila = next(f for f in respuesta.context["filas"] if f["producto"] == self.producto)
        self.assertEqual(fila["cantidad"], Decimal("1"))
        self.assertEqual(fila["saldo_kardex"], Decimal("2"))
        self.assertEqual(respuesta.context["total_valor"], Decimal("10"))
        self.assertTrue(fila["diferencia"])
        self.assertContains(respuesta, "requieren revisión")

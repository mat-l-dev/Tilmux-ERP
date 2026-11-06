"""Protecciones para el orden cronológico de las capas PEPS."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from catalogo.models import Producto, UnidadMedida
from core.models import Empresa
from inventario.models import CapaFIFO, MovimientoStock
from inventario.servicios import StockError, entrar, salir


class InventarioFechasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        cls.producto = Producto.objects.create(sku="TEST", nombre="Producto", unidad=unidad)

    def setUp(self):
        entrar(
            empresa=self.empresa,
            producto=self.producto,
            fecha=date(2026, 10, 1),
            cantidad=Decimal("3"),
            costo_unitario=Decimal("100"),
        )
        salir(empresa=self.empresa, producto=self.producto, fecha=date(2026, 10, 20), cantidad=Decimal("1"))

    def test_entrada_antes_de_salida_posterior_no_altera_peps(self):
        with self.assertRaises(StockError):
            entrar(
                empresa=self.empresa,
                producto=self.producto,
                fecha=date(2026, 10, 10),
                cantidad=Decimal("1"),
                costo_unitario=Decimal("10"),
            )
        self.assertEqual(CapaFIFO.objects.count(), 1)
        self.assertEqual(MovimientoStock.objects.count(), 2)

    def test_salida_antes_de_salida_posterior_no_altera_peps(self):
        with self.assertRaises(StockError):
            salir(empresa=self.empresa, producto=self.producto, fecha=date(2026, 10, 10), cantidad=Decimal("1"))
        self.assertEqual(CapaFIFO.objects.get().cantidad_restante, Decimal("2"))
        self.assertEqual(MovimientoStock.objects.count(), 2)

    def test_movimientos_posteriores_a_la_salida_siguen_permitidos(self):
        salir(empresa=self.empresa, producto=self.producto, fecha=date(2026, 10, 21), cantidad=Decimal("1"))
        self.assertEqual(CapaFIFO.objects.get().cantidad_restante, Decimal("1"))

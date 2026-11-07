"""La administración no debe alterar movimientos contables directamente."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria, Producto, UnidadMedida
from contabilidad.models import Asiento
from core.models import Empresa, Periodo
from inventario.models import CapaFIFO, ConsumoCapa, MovimientoStock
from tesoreria.models import MovimientoTesoreria


class AdminContableTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        periodo = Periodo.objects.create(empresa=empresa, anio=2026, mes=10)
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        producto = Producto.objects.create(sku="TEST", nombre="Producto", unidad=unidad)
        cuenta = CuentaTesoreria.objects.create(empresa=empresa, nombre="Caja")
        asiento = Asiento.objects.create(
            empresa=empresa,
            periodo=periodo,
            fecha=date(2026, 10, 1),
            numero=1,
            tipo_operacion="COMPRA",
            glosa="Prueba",
        )
        capa = CapaFIFO.objects.create(
            empresa=empresa,
            producto=producto,
            fecha=date(2026, 10, 1),
            cantidad_inicial=1,
            cantidad_restante=1,
            costo_unitario=10,
        )
        movimiento = MovimientoStock.objects.create(
            empresa=empresa,
            producto=producto,
            fecha=date(2026, 10, 1),
            tipo="ENTRADA",
            cantidad=1,
            costo_unitario=10,
            costo_total=10,
        )
        consumo = ConsumoCapa.objects.create(
            movimiento=movimiento, capa=capa, cantidad=1, costo_unitario=10, costo_total=10
        )
        tesoreria = MovimientoTesoreria.objects.create(
            empresa=empresa, cuenta=cuenta, fecha=date(2026, 10, 1), tipo="EGRESO", importe=Decimal("10")
        )
        cls.documentos = [
            ("core", "periodo", periodo),
            ("contabilidad", "asiento", asiento),
            ("inventario", "capafifo", capa),
            ("inventario", "movimientostock", movimiento),
            ("inventario", "consumocapa", consumo),
            ("tesoreria", "movimientotesoreria", tesoreria),
        ]
        cls.usuario = get_user_model().objects.create_superuser(username="admin_prueba", password="prueba")

    def test_solo_consulta_y_no_se_pueden_borrar(self):
        self.client.force_login(self.usuario)
        for app, nombre, objeto in self.documentos:
            with self.subTest(modelo=nombre):
                self.assertEqual(
                    self.client.get(reverse(f"admin:{app}_{nombre}_change", args=[objeto.pk])).status_code, 200
                )
                self.assertEqual(
                    self.client.post(reverse(f"admin:{app}_{nombre}_change", args=[objeto.pk]), {}).status_code, 403
                )
                self.assertEqual(
                    self.client.post(
                        reverse(f"admin:{app}_{nombre}_delete", args=[objeto.pk]), {"post": "yes"}
                    ).status_code,
                    403,
                )
                self.assertEqual(self.client.post(reverse(f"admin:{app}_{nombre}_add"), {}).status_code, 403)

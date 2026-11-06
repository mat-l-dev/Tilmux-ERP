"""Las devoluciones parciales conservan los importes de la venta."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.db.models import Sum
from django.test import TestCase

from catalogo.models import Producto, UnidadMedida
from core.models import Empresa
from inventario.models import MovimientoStock
from ventas.models import NotaCredito, NotaCreditoLinea, Venta, VentaLinea
from ventas.servicios import emitir_nota_credito


class RedondeoNotasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        producto = Producto.objects.create(sku="TEST", nombre="Producto", unidad=unidad)
        cls.venta = Venta.objects.create(
            empresa=cls.empresa,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="E001",
            numero="1",
            estado=Venta.Estado.CONFIRMADA,
        )
        cls.linea = VentaLinea.objects.create(
            venta=cls.venta,
            producto=producto,
            cantidad=Decimal("3"),
            precio_unitario=Decimal("39.336667"),
            base=Decimal("100.00"),
            igv=Decimal("18.01"),
            total=Decimal("118.01"),
            costo_total=Decimal("10.00"),
            costo_unitario=Decimal("3.3333333333"),
        )

    def _notas(self, reingresos):
        notas = []
        with patch("ventas.servicios.postear") as postear:
            for indice, reingresa in enumerate(reingresos, start=1):
                notas.append(
                    emitir_nota_credito(
                        venta=self.venta,
                        fecha=date(2026, 10, 2),
                        serie="FC01",
                        numero=str(indice),
                        motivo_codigo="07",
                        cantidades={self.linea.pk: Decimal("1")},
                        reingresa_stock=reingresa,
                    )
                )
        return notas, postear

    def test_tres_devoluciones_conservan_importes_y_costo(self):
        notas, postear = self._notas([True, True, True])
        self.assertEqual(sum(nota.base for nota in notas), Decimal("100.00"))
        self.assertEqual(sum(nota.igv for nota in notas), Decimal("18.01"))
        self.assertEqual(sum(nota.costo for nota in notas), Decimal("10.00"))
        costo_stock = MovimientoStock.objects.filter(origen_tipo="NOTA_CREDITO").aggregate(s=Sum("costo_total"))["s"]
        self.assertEqual(costo_stock, Decimal("10.00"))
        self.assertEqual(sum(llamada.kwargs["montos"].costo for llamada in postear.call_args_list), costo_stock)

    def test_unidades_sin_reingreso_no_revierte_su_costo(self):
        notas, _ = self._notas([False, True, True])
        self.assertEqual(sum(nota.base for nota in notas), Decimal("100.00"))
        self.assertEqual(notas[0].costo, Decimal("0"))
        self.assertEqual(sum(nota.costo for nota in notas), Decimal("6.67"))
        costo_stock = MovimientoStock.objects.filter(origen_tipo="NOTA_CREDITO").aggregate(s=Sum("costo_total"))["s"]
        self.assertEqual(costo_stock, Decimal("6.67"))

    def test_ultima_devolucion_ajusta_redondeos_previos(self):
        for numero in ("1", "2"):
            nota = NotaCredito.objects.create(
                venta=self.venta,
                fecha=date(2026, 10, 2),
                serie="FC01",
                numero=numero,
                motivo="Devolución",
                motivo_codigo="07",
                reingresa_stock=True,
                base=Decimal("33.33"),
                igv=Decimal("6.00"),
                total=Decimal("39.33"),
                costo=Decimal("3.33"),
            )
            NotaCreditoLinea.objects.create(
                nota=nota,
                venta_linea=self.linea,
                cantidad=1,
                base=Decimal("33.33"),
                igv=Decimal("6.00"),
                total=Decimal("39.33"),
                costo_total=Decimal("3.33"),
            )
        with patch("ventas.servicios.postear"):
            nota = emitir_nota_credito(
                venta=self.venta,
                fecha=date(2026, 10, 3),
                serie="FC01",
                numero="3",
                motivo_codigo="07",
                cantidades={self.linea.pk: Decimal("1")},
                reingresa_stock=True,
            )
        self.assertEqual((nota.base, nota.igv, nota.costo), (Decimal("33.34"), Decimal("6.01"), Decimal("3.34")))
        movimiento = MovimientoStock.objects.get(origen_tipo="NOTA_CREDITO", origen_id=nota.pk)
        self.assertEqual(movimiento.costo_total, Decimal("3.34"))

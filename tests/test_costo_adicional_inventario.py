from datetime import date
from decimal import Decimal

from django.db.models import Sum

from compras.models import Compra, CompraLinea, CostoAdicional
from compras.servicios import CompraError, confirmar
from contabilidad.models import Asiento
from inventario.models import MovimientoStock

from .test_invariantes import BaseContable


class CostoAdicionalInventarioTest(BaseContable):
    def crear_compra(self, *, con_credito, lineas):
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 10),
            tipo_doc="FACTURA" if con_credito else "BOLETA",
            serie="F001" if con_credito else "B001",
            numero="1",
            con_credito=con_credito,
        )
        for orden, (base, igv) in enumerate(lineas, 1):
            CompraLinea.objects.create(
                compra=compra,
                producto=self.producto,
                orden=orden,
                cantidad=1,
                precio_unitario=base,
                base=base,
                igv=igv,
                total=base + igv,
            )
        return compra

    def test_costo_no_recuperable_coincide_con_asiento_e_inventario(self):
        compra = self.crear_compra(con_credito=False, lineas=[(Decimal("100"), Decimal("18"))])
        CostoAdicional.objects.create(
            compra=compra, concepto="Flete", base=10, igv=Decimal("1.80"), total=Decimal("11.80")
        )
        confirmar(compra)
        movimiento = MovimientoStock.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        self.assertEqual(movimiento.costo_total, Decimal("129.80"))
        self.assertEqual(asiento.lineas.aggregate(suma=Sum("debe"))["suma"], Decimal("129.80"))

    def test_costo_gravado_con_credito_no_incluye_igv_en_inventario(self):
        compra = self.crear_compra(con_credito=True, lineas=[(Decimal("100"), Decimal("18"))])
        CostoAdicional.objects.create(
            compra=compra, concepto="Flete", base=10, igv=Decimal("1.80"), total=Decimal("11.80")
        )
        confirmar(compra)
        movimiento = MovimientoStock.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        self.assertEqual(movimiento.costo_total, Decimal("110"))

    def test_prorrateo_no_genera_costos_negativos_y_distribuye_todos_los_centimos(self):
        compra = self.crear_compra(con_credito=True, lineas=[(Decimal("1"), Decimal("0"))] * 4)
        CostoAdicional.objects.create(
            compra=compra, concepto="Flete", base=Decimal("0.02"), igv=0, total=Decimal("0.02")
        )
        confirmar(compra)
        movimientos = MovimientoStock.objects.filter(origen_tipo="COMPRA", origen_id=compra.pk)
        self.assertEqual(movimientos.aggregate(suma=Sum("costo_total"))["suma"], Decimal("4.02"))
        self.assertTrue(all(m.costo_total >= 1 for m in movimientos))

    def test_costos_inconsistentes_no_generan_stock_ni_asiento(self):
        compra = self.crear_compra(con_credito=True, lineas=[(Decimal("100"), Decimal("18"))])
        CostoAdicional.objects.create(compra=compra, concepto="Flete", base=10, igv=2, total=13)
        with self.assertRaisesMessage(CompraError, "costos adicionales"):
            confirmar(compra)
        self.assertFalse(MovimientoStock.objects.filter(origen_tipo="COMPRA", origen_id=compra.pk).exists())
        self.assertFalse(Asiento.objects.filter(origen_tipo="COMPRA", origen_id=compra.pk).exists())

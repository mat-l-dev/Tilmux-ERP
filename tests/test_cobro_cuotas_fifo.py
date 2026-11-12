from datetime import date
from decimal import Decimal

from contabilidad.models import Asiento
from tesoreria.models import MovimientoTesoreria
from ventas.models import CuotaVenta, Venta, VentaLinea
from ventas.servicios import VentaError, confirmar
from ventas.servicios_cobro import cobrar_venta, saldo_pendiente

from .test_invariantes import BaseContable


class CobroCuotasFifoTest(BaseContable):
    def setUp(self):
        self.comprar("1", "50")
        self.venta = Venta.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            cliente_nombre=self.cliente.nombre,
            fecha=date(2026, 11, 20),
            tipo_doc="FACTURA",
            serie="E001",
            numero="1",
            condicion="CREDITO",
        )
        VentaLinea.objects.create(
            venta=self.venta,
            producto=self.producto,
            cantidad=1,
            precio_unitario=118,
            base=100,
            igv=18,
            total=118,
        )
        for numero, (vencimiento, importe) in enumerate(
            ((date(2026, 12, 20), "30"), (date(2027, 1, 20), "40"), (date(2027, 2, 20), "48")),
            start=1,
        ):
            CuotaVenta.objects.create(
                venta=self.venta,
                numero=numero,
                vencimiento=vencimiento,
                importe=Decimal(importe),
            )
        self.venta = confirmar(self.venta)

    def cobrar(self, importe, **opciones):
        datos = dict(
            venta=self.venta,
            fecha=date(2026, 11, 21),
            importe=Decimal(importe),
            cuenta=self.bbva,
            canal="TRANSFERENCIA",
        )
        datos.update(opciones)
        return cobrar_venta(**datos)

    def test_reparte_el_cobro_entre_cuotas_en_orden_fifo(self):
        cobro = self.cobrar("80")

        filas = list(self.venta.cobros.order_by("cuota__numero"))
        self.assertEqual([fila.cuota.numero for fila in filas], [1, 2, 3])
        self.assertEqual([fila.importe for fila in filas], [Decimal("30"), Decimal("40"), Decimal("10")])
        self.assertEqual(sum(fila.importe for fila in filas), Decimal("80"))
        self.assertEqual(saldo_pendiente(self.venta), Decimal("38"))
        self.assertEqual(cobro.pk, filas[0].pk)

        movimientos = MovimientoTesoreria.objects.filter(origen_tipo="COBRO_VENTA", origen_id=cobro.pk)
        self.assertEqual(movimientos.count(), 1)
        self.assertEqual(movimientos.get().importe, Decimal("80"))

    def test_cobro_exacto_en_una_cuota_sigue_igual(self):
        cuota = self.venta.cuotas.get(numero=1)
        cobro = self.cobrar("30", cuota=cuota)

        self.assertEqual(cobro.cuota_id, cuota.pk)
        self.assertEqual(cobro.importe, Decimal("30"))
        self.assertEqual(self.venta.cobros.count(), 1)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("88"))

    def test_sobrecobro_rechazado_sin_efectos(self):
        with self.assertRaisesMessage(VentaError, "excede el saldo pendiente"):
            self.cobrar("119")

        self.assertFalse(self.venta.cobros.exists())
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="COBRO_VENTA").exists())
        self.assertEqual(Asiento.objects.filter(origen_tipo="COBRO_VENTA").count(), 0)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("118"))

    def test_movimiento_historico_cuenta_como_cobrado_y_no_bloquea(self):
        MovimientoTesoreria.objects.create(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=self.venta.fecha,
            tipo="INGRESO",
            importe=Decimal("10"),
            origen_tipo="VENTA",
            origen_id=self.venta.pk,
        )
        self.assertEqual(saldo_pendiente(self.venta), Decimal("108"))

        self.cobrar("108")

        self.assertEqual(saldo_pendiente(self.venta), Decimal("0"))
        self.assertEqual(
            sum((fila.importe for fila in self.venta.cobros.all()), Decimal("0")),
            Decimal("108"),
        )
        with self.assertRaisesMessage(VentaError, "excede el saldo pendiente"):
            self.cobrar("1")

    def test_no_autoasigna_si_hay_cobros_sin_cuota_previos(self):
        self.cobrar("10", asignar_automaticamente=False)

        self.cobrar("20")

        ultimo = self.venta.cobros.order_by("pk").last()
        self.assertIsNone(ultimo.cuota_id)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("88"))

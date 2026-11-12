from datetime import date
from decimal import Decimal

from contabilidad.models import Asiento
from inventario.servicios import entrar
from ventas.models import NotaCreditoLinea, RestitucionCapa, VentaLinea
from ventas.servicios import VentaError, emitir_nota_credito

from .test_invariantes import BaseContable


class NotaCreditoPepsTest(BaseContable):
    """La NC de venta devuelve las capas originales, no el promedio."""

    def capa(self, cantidad, costo, fecha):
        return entrar(
            empresa=self.empresa,
            producto=self.producto,
            fecha=fecha,
            cantidad=Decimal(cantidad),
            costo_unitario=Decimal(costo),
            origen_tipo="COMPRA",
            origen_id=1,
        )

    def vender_dos_capas(self):
        self.capa("1", "274.58", date(2026, 11, 1))
        self.capa("1", "338.14", date(2026, 11, 2))
        venta = self.vender("2", "700", fecha=date(2026, 11, 20))
        linea = venta.lineas.get()
        self.assertEqual(linea.costo_total, Decimal("612.72"))
        self.assertEqual(linea.costo_unitario, Decimal("306.3600000000"))
        return venta, linea

    def test_la_venta_guarda_que_capas_consumio(self):
        venta, linea = self.vender_dos_capas()

        self.assertIsNotNone(linea.movimiento_stock)
        consumos = list(linea.movimiento_stock.consumos.order_by("id"))
        self.assertEqual([consumo.cantidad for consumo in consumos], [Decimal("1"), Decimal("1")])
        self.assertEqual(
            [consumo.costo_unitario for consumo in consumos],
            [Decimal("274.5800000000"), Decimal("338.1400000000")],
        )

    def test_devolucion_de_una_unidad_reingresa_a_la_primera_capa(self):
        venta, linea = self.vender_dos_capas()

        nota = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )

        linea_nota = nota.lineas.get()
        restitucion = RestitucionCapa.objects.get(nota_linea=linea_nota)
        self.assertEqual(nota.costo, Decimal("274.58"))
        self.assertNotEqual(nota.costo, Decimal("306.36"))
        self.assertEqual(linea_nota.costo_total, Decimal("274.58"))
        self.assertEqual(linea_nota.origen_costo, NotaCreditoLinea.OrigenCosto.PEPS)
        self.assertEqual(restitucion.cantidad, Decimal("1"))
        self.assertEqual(restitucion.costo_unitario, Decimal("274.5800000000"))
        self.assertEqual(restitucion.capa_restaurada.costo_unitario, Decimal("274.5800000000"))
        self.assertEqual(restitucion.capa_restaurada.cantidad_inicial, Decimal("1"))

        asiento = Asiento.objects.get(origen_tipo="NOTA_CREDITO", origen_id=nota.pk)
        self.assertEqual(asiento.lineas.get(cuenta__codigo="20111").debe, Decimal("274.58"))
        self.assertEqual(asiento.lineas.get(cuenta__codigo="69121").haber, Decimal("274.58"))

    def test_segunda_devolucion_restaura_la_segunda_capa(self):
        venta, linea = self.vender_dos_capas()

        primera = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )
        segunda = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 26),
            serie="FC01",
            numero="2",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )

        self.assertEqual(primera.costo, Decimal("274.58"))
        self.assertEqual(segunda.costo, Decimal("338.14"))
        self.assertEqual(primera.costo + segunda.costo, Decimal("612.72"))
        self.assertEqual(
            list(
                RestitucionCapa.objects.filter(nota_linea__venta_linea=linea)
                .order_by("id")
                .values_list("costo_unitario", flat=True)
            ),
            [Decimal("274.5800000000"), Decimal("338.1400000000")],
        )

    def test_devolucion_total_restaura_todas_las_capas(self):
        venta, linea = self.vender_dos_capas()

        nota = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="1",
            motivo_codigo="06",
            cantidades={linea.pk: Decimal("2")},
        )

        self.assertEqual(nota.costo, Decimal("612.72"))
        self.assertEqual(nota.lineas.get().origen_costo, NotaCreditoLinea.OrigenCosto.PEPS)
        self.assertEqual(RestitucionCapa.objects.filter(nota_linea__nota=nota).count(), 2)

    def test_devolucion_parcial_recorre_las_capas_en_orden(self):
        self.capa("2", "100.00", date(2026, 11, 1))
        self.capa("1", "200.00", date(2026, 11, 2))
        venta = self.vender("3", "700", fecha=date(2026, 11, 20))
        linea = venta.lineas.get()

        costos = []
        for numero in ("1", "2", "3"):
            nota = emitir_nota_credito(
                venta=venta,
                fecha=date(2026, 11, 25 + int(numero)),
                serie="FC01",
                numero=numero,
                motivo_codigo="07",
                cantidades={linea.pk: Decimal("1")},
            )
            costos.append(nota.costo)

        self.assertEqual(costos, [Decimal("100.00"), Decimal("100.00"), Decimal("200.00")])
        self.assertEqual(sum(costos), Decimal("400.00"))

    def test_una_sola_capa_mantiene_el_costo_original(self):
        self.capa("2", "100.00", date(2026, 11, 1))
        venta = self.vender("2", "700", fecha=date(2026, 11, 20))
        linea = venta.lineas.get()

        nota = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )

        self.assertEqual(nota.costo, Decimal("100.00"))
        self.assertEqual(nota.costo, linea.costo_unitario * Decimal("1"))

    def test_venta_sin_detalle_usa_promedio_y_lo_marca_como_respaldo(self):
        venta, linea = self.vender_dos_capas()
        VentaLinea.objects.filter(pk=linea.pk).update(movimiento_stock=None)

        nota = emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )

        linea_nota = nota.lineas.get()
        self.assertEqual(nota.costo, Decimal("306.36"))
        self.assertEqual(linea_nota.origen_costo, NotaCreditoLinea.OrigenCosto.PROMEDIO)
        self.assertFalse(RestitucionCapa.objects.exists())

    def test_no_puede_devolver_mas_de_lo_vendido(self):
        venta, linea = self.vender_dos_capas()

        with self.assertRaisesMessage(VentaError, "solo quedan 2"):
            emitir_nota_credito(
                venta=venta,
                fecha=date(2026, 11, 25),
                serie="FC01",
                numero="1",
                motivo_codigo="07",
                cantidades={linea.pk: Decimal("3")},
            )

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from compras.devoluciones import registrar_devolucion
from compras.models import Compra, CompraLinea, CostoAdicional
from compras.servicios import CompraError, confirmar, pagar, revaluar
from contabilidad.models import Asiento
from contabilidad.moneda import tipo_cambio_de, tipo_cambio_para
from core.models import TipoCambio
from inventario.models import CapaFIFO
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class MonedaExtranjeraTest(BaseContable):
    """Compra en dólares: costo en soles, saldo en USD y diferencia de cambio."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        TipoCambio.objects.create(fecha=date(2026, 11, 10), compra=Decimal("3.447"), venta=Decimal("3.452"))
        TipoCambio.objects.create(fecha=date(2026, 11, 30), compra=Decimal("3.447"), venta=Decimal("3.500"))

    def crear_borrador(
        self,
        *,
        fecha=date(2026, 11, 10),
        tc=Decimal("3.452"),
        lineas=((Decimal("84.75"), Decimal("15.25"), Decimal("100.00")),),
        tipo_doc="FACTURA",
        con_credito=True,
        numero="0001",
    ):
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=fecha,
            tipo_doc=tipo_doc,
            serie="F009",
            numero=numero,
            moneda="USD",
            tipo_cambio=tc,
            con_credito=con_credito,
            creado_por=None,
        )
        for orden, (base, igv, total) in enumerate(lineas, start=1):
            CompraLinea.objects.create(
                compra=compra,
                orden=orden,
                producto=self.producto,
                cantidad=Decimal("1"),
                precio_unitario=total,
                base=base,
                igv=igv,
                total=total,
            )
        return compra

    def confirmada(self, **kwargs):
        compra = self.crear_borrador(**kwargs)
        return confirmar(compra)

    def test_confirma_factura_en_dolares_con_costo_en_soles(self):
        compra = self.confirmada()

        self.assertEqual(compra.estado, Compra.Estado.CONFIRMADA)
        self.assertEqual(compra.total_moneda_origen, Decimal("100.00"))
        self.assertEqual(compra.subtotal, Decimal("292.54"))
        self.assertEqual(compra.igv, Decimal("52.66"))
        self.assertEqual(compra.total, Decimal("345.20"))
        self.assertEqual(compra.saldo_moneda_origen, Decimal("100.00"))

        capa = CapaFIFO.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        self.assertEqual(capa.costo_unitario, Decimal("292.5400000000"))

        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        importes = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(importes["20111"], (Decimal("292.54"), Decimal("0.00")))
        self.assertEqual(importes["40111"], (Decimal("52.66"), Decimal("0.00")))
        self.assertEqual(importes["4212"], (Decimal("0.00"), Decimal("345.20")))

    def test_pago_total_con_diferencia_de_cambio(self):
        compra = self.confirmada()

        pagado, diferencia = pagar(
            compra,
            cuenta=self.bbva,
            fecha=date(2026, 11, 20),
            tipo_cambio_pago=Decimal("3.500"),
        )

        self.assertEqual(pagado, Decimal("350.00"))
        self.assertEqual(diferencia, Decimal("4.80"))
        compra.refresh_from_db()
        self.assertEqual(compra.monto_pagado, Decimal("345.20"))
        self.assertEqual(compra.pagado_moneda_origen, Decimal("100.0000"))
        self.assertEqual(compra.saldo_moneda_origen, Decimal("0"))
        self.assertTrue(compra.pagada)

        asiento = Asiento.objects.get(origen_tipo="COMPRA_PAGO", origen_id=compra.pk)
        importes = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(importes["4212"], (Decimal("345.20"), Decimal("0.00")))
        self.assertEqual(importes["6761"], (Decimal("4.80"), Decimal("0.00")))
        self.assertEqual(importes["1061"], (Decimal("0.00"), Decimal("350.00")))

    def test_pago_parcial_en_dolares_y_segundo_pago(self):
        compra = self.confirmada()

        pagado, diferencia = pagar(
            compra,
            cuenta=self.bbva,
            fecha=date(2026, 11, 20),
            importe=Decimal("50"),
            tipo_cambio_pago=Decimal("3.500"),
        )
        compra.refresh_from_db()
        self.assertEqual(pagado, Decimal("175.00"))
        self.assertEqual(diferencia, Decimal("2.40"))
        self.assertEqual(compra.pagado_moneda_origen, Decimal("50.0000"))
        self.assertEqual(compra.saldo_moneda_origen, Decimal("50.00"))
        self.assertEqual(compra.monto_pagado, Decimal("172.60"))
        self.assertFalse(compra.pagada)

        pagado, diferencia = pagar(
            compra,
            cuenta=self.bbva,
            fecha=date(2026, 11, 21),
            importe=Decimal("50"),
            tipo_cambio_pago=Decimal("3.520"),
        )
        compra.refresh_from_db()
        self.assertEqual(pagado, Decimal("176.00"))
        self.assertEqual(diferencia, Decimal("3.40"))
        self.assertEqual(compra.monto_pagado, Decimal("345.20"))
        self.assertEqual(compra.pagado_moneda_origen, Decimal("100.0000"))
        self.assertEqual(compra.saldo_moneda_origen, Decimal("0"))
        self.assertTrue(compra.pagada)

        movimientos = MovimientoTesoreria.objects.filter(origen_tipo="COMPRA_PAGO", origen_id=compra.pk)
        self.assertEqual(movimientos.count(), 2)
        self.assertEqual(sum(m.importe for m in movimientos), Decimal("351.00"))

    def test_revaluacion_con_pago_parcial(self):
        compra = self.confirmada()
        pagar(
            compra,
            cuenta=self.bbva,
            fecha=date(2026, 11, 20),
            importe=Decimal("50"),
            tipo_cambio_pago=Decimal("3.500"),
        )

        ajustadas, total = revaluar(self.empresa, 2026, 11)

        self.assertEqual(ajustadas, 1)
        self.assertEqual(total, Decimal("2.40"))
        compra.refresh_from_db()
        self.assertEqual(compra.revaluacion, Decimal("2.40"))

        asiento = Asiento.objects.get(origen_tipo="REVALUACION", origen_id=compra.pk)
        importes = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(importes["6761"], (Decimal("2.40"), Decimal("0.00")))
        self.assertEqual(importes["4212"], (Decimal("0.00"), Decimal("2.40")))

        pagado, diferencia = pagar(
            compra,
            cuenta=self.bbva,
            fecha=date(2026, 12, 2),
            importe=Decimal("50"),
            tipo_cambio_pago=Decimal("3.500"),
        )
        self.assertEqual(pagado, Decimal("175.00"))
        self.assertEqual(diferencia, Decimal("0.00"))
        compra.refresh_from_db()
        self.assertTrue(compra.pagada)

    def test_no_permite_pagar_mas_que_el_saldo_en_dolares(self):
        compra = self.confirmada()

        with self.assertRaisesMessage(CompraError, "saldo pendiente"):
            pagar(
                compra,
                cuenta=self.bbva,
                fecha=date(2026, 11, 20),
                importe=Decimal("150"),
                tipo_cambio_pago=Decimal("3.500"),
            )
        compra.refresh_from_db()
        self.assertEqual(compra.pagado_moneda_origen, Decimal("0"))
        self.assertFalse(Asiento.objects.filter(origen_tipo="COMPRA_PAGO", origen_id=compra.pk).exists())

    def test_tc_de_fecha_anterior_avisa_y_expone_la_fecha(self):
        with self.assertLogs("core.models", level="WARNING") as registro:
            tasa = tipo_cambio_de(date(2026, 11, 15))

        self.assertEqual(tasa.venta, Decimal("3.452"))
        self.assertEqual(tasa.fecha, date(2026, 11, 10))
        self.assertIn("2026-11-15", registro.output[0])
        self.assertIsNone(TipoCambio.de_la_fecha(date(2026, 11, 15)))

        registro_tc, anterior = tipo_cambio_para(date(2026, 11, 15))
        self.assertTrue(anterior)
        self.assertEqual(registro_tc.fecha, date(2026, 11, 10))

        exacto, anterior = tipo_cambio_para(date(2026, 11, 10))
        self.assertFalse(anterior)
        self.assertEqual(exacto.fecha, date(2026, 11, 10))

    def test_sin_tipo_cambio_es_error_de_dominio_y_no_posta(self):
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F008",
            numero="0001",
            moneda="USD",
            tipo_cambio=Decimal("3.450"),
            estado=Compra.Estado.CONFIRMADA,
            subtotal=Decimal("292.54"),
            igv=Decimal("52.66"),
            total=Decimal("345.20"),
            total_moneda_origen=Decimal("100.00"),
        )

        with self.assertRaisesMessage(CompraError, "tipo de cambio"):
            pagar(compra, cuenta=self.bbva, fecha=date(2026, 10, 2))
        self.assertFalse(Asiento.objects.filter(origen_tipo="COMPRA_PAGO", origen_id=compra.pk).exists())

    def test_confirmar_sin_tc_ni_manual_no_crea_compra_varada(self):
        compra = self.crear_borrador(fecha=date(2026, 10, 1), tc=Decimal("1"))

        with self.assertRaisesMessage(CompraError, "tipo de cambio"):
            confirmar(compra)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, Compra.Estado.BORRADOR)
        self.assertFalse(CapaFIFO.objects.filter(origen_tipo="COMPRA", origen_id=compra.pk).exists())

    def test_compra_fx_con_costos_de_internamiento_se_bloquea(self):
        compra = self.crear_borrador()
        CostoAdicional.objects.create(
            compra=compra,
            concepto="Flete",
            base=Decimal("20.00"),
            igv=Decimal("0.00"),
            total=Decimal("20.00"),
        )

        with self.assertRaisesMessage(CompraError, "costos de internamiento"):
            confirmar(compra)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, Compra.Estado.BORRADOR)

    def test_devolucion_al_proveedor_en_moneda_extranjera_sigue_bloqueada(self):
        compra = self.confirmada()
        linea = compra.lineas.get()

        with self.assertRaisesMessage(CompraError, "moneda extranjera"):
            registrar_devolucion(
                compra=compra,
                fecha=date(2026, 11, 25),
                serie="FC10",
                numero="1",
                motivo_codigo="07",
                cantidades={linea.pk: Decimal("1")},
            )
        self.assertFalse(compra.notas_credito.exists())
        self.assertEqual(
            CapaFIFO.objects.get(origen_tipo="COMPRA", origen_id=compra.pk).cantidad_restante,
            Decimal("1"),
        )

    def test_pantalla_nueva_registra_compra_en_dolares_y_confirma(self):
        usuario = get_user_model().objects.create_superuser(username="fx", password="test")
        self.client.force_login(usuario)

        respuesta = self.client.post(
            reverse("compras:nueva"),
            {
                "fecha": "2026-11-10",
                "tipo_doc": "FACTURA",
                "serie": "F009",
                "numero": "0002",
                "proveedor": self.proveedor.pk,
                "moneda": "USD",
                "tipo_cambio": "3.452",
                "con_igv": "on",
                "linea_producto": [self.producto.pk],
                "linea_cantidad": ["1"],
                "linea_precio": ["100"],
                "linea_descripcion": [""],
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        compra = Compra.objects.get(numero="0002")
        self.assertEqual(compra.moneda, "USD")
        self.assertEqual(compra.tipo_cambio, Decimal("3.452000"))
        self.assertEqual(compra.subtotal, Decimal("292.54"))
        self.assertEqual(compra.igv, Decimal("52.66"))
        self.assertEqual(compra.total, Decimal("345.20"))
        self.assertEqual(compra.total_moneda_origen, Decimal("100.00"))

        self.assertEqual(compra.lineas.get().total, Decimal("100.00"))
        respuesta = self.client.post(reverse("compras:confirmar", args=[compra.pk]), follow=True)
        self.assertEqual(respuesta.status_code, 200)
        compra.refresh_from_db()
        self.assertEqual(compra.estado, Compra.Estado.CONFIRMADA)


class TipoCambioTest(TestCase):
    def test_de_la_fecha_no_arrastra_el_anterior(self):
        TipoCambio.objects.create(fecha=date(2026, 11, 10), compra=Decimal("3.447"), venta=Decimal("3.452"))
        self.assertEqual(TipoCambio.de_la_fecha(date(2026, 11, 10)).venta, Decimal("3.452"))
        self.assertIsNone(TipoCambio.de_la_fecha(date(2026, 11, 11)))

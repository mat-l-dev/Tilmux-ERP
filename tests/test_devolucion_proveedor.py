from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.devoluciones import (
    registrar_devolucion,
    registrar_reembolso,
    saldo_4212,
)
from compras.models import Compra, NotaCreditoCompra
from compras.servicios import CompraError, pagar
from contabilidad.models import Asiento
from core.models import HistorialDocumento
from inventario.models import CapaFIFO, ConsumoCapa, MovimientoStock
from reportes.casillas import calcular
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class DevolucionProveedorTest(BaseContable):
    """Devolución real al proveedor: deuda, IGV, PEPS y reembolso."""

    def setUp(self):
        self.compra = self.comprar("2", "100")  # base 200, IGV 36, total 236
        self.linea = self.compra.lineas.get()
        pagar(self.compra, cuenta=self.bbva, fecha=date(2026, 11, 10))
        self.compra.refresh_from_db()

    def devolver(self, cantidad="1", **extra):
        datos = {
            "compra": self.compra,
            "fecha": date(2026, 11, 12),
            "serie": "FC01",
            "numero": "1",
            "motivo_codigo": "07",
            "cantidades": {self.linea.pk: Decimal(cantidad)},
        }
        datos.update(extra)
        return registrar_devolucion(**datos)

    def test_devolucion_parcial_baja_deuda_revierte_igv_saca_peps_y_registra_reembolso(self):
        nota = self.devolver(cuenta_reembolso=self.bbva)

        self.assertEqual(nota.base, Decimal("100.00"))
        self.assertEqual(nota.igv, Decimal("18.00"))
        self.assertEqual(nota.total, Decimal("118.00"))
        self.assertEqual(nota.costo, Decimal("100.00"))

        # 1) El asiento revierte deuda, inventario e IGV, y no es una reversión interna.
        asiento = Asiento.objects.get(origen_tipo="DEVOLUCION_COMPRA", origen_id=nota.pk)
        importes = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(importes["4212"], (Decimal("118.00"), Decimal("0.00")))
        self.assertEqual(importes["20111"], (Decimal("0.00"), Decimal("100.00")))
        self.assertEqual(importes["40111"], (Decimal("0.00"), Decimal("18.00")))
        self.assertFalse(Asiento.objects.filter(origen_tipo="REV_COMPRA", origen_id=self.compra.pk).exists())

        # 2) La salida sale de la capa de ESA compra, a costo original.
        capa = CapaFIFO.objects.get(origen_tipo="COMPRA", origen_id=self.compra.pk)
        self.assertEqual(capa.cantidad_restante, Decimal("1"))
        salida = MovimientoStock.objects.get(origen_tipo="DEVOLUCION_COMPRA", origen_id=nota.pk)
        self.assertEqual(salida.costo_total, Decimal("100.00"))
        self.assertEqual(ConsumoCapa.objects.get(movimiento=salida).capa, capa)

        # 3) El reembolso entra a tesorería y deja la deuda en cero.
        movimiento = MovimientoTesoreria.objects.get(origen_tipo="DEVOLUCION_PROVEEDOR", origen_id=nota.pk)
        self.assertEqual(movimiento.tipo, MovimientoTesoreria.Tipo.INGRESO)
        self.assertEqual(movimiento.cuenta, self.bbva)
        self.assertEqual(movimiento.importe, Decimal("118.00"))
        self.assertEqual(saldo_4212(self.compra), Decimal("0.00"))
        nota.refresh_from_db()
        self.assertTrue(nota.reembolsado)
        self.assertEqual(nota.importe_reembolsado, Decimal("118.00"))
        self.assertTrue(
            HistorialDocumento.objects.filter(tipo="COMPRA", documento_id=self.compra.pk, accion="DEVOLUCION").exists()
        )
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.CONFIRMADA)

    def test_usa_el_costo_de_la_capa_original_y_no_el_promedio(self):
        # Venta que consume 1 unidad de la compra original y compra posterior más cara.
        self.vender("1", "300", fecha=date(2026, 11, 20))
        self.comprar("1", "200", fecha=date(2026, 11, 21))

        nota = self.devolver(cantidad="1", fecha=date(2026, 11, 22))

        self.assertEqual(nota.costo, Decimal("100.00"))
        self.assertEqual(nota.base, Decimal("100.00"))
        salida = MovimientoStock.objects.get(origen_tipo="DEVOLUCION_COMPRA", origen_id=nota.pk)
        self.assertEqual(salida.costo_total, Decimal("100.00"))

    def test_no_registra_reembolso_si_la_compra_no_esta_pagada(self):
        compra = self.comprar("1", "100")
        linea = compra.lineas.get()
        nota = registrar_devolucion(
            compra=compra,
            fecha=date(2026, 11, 12),
            serie="FC02",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )
        self.assertFalse(nota.reembolsado)
        self.assertEqual(saldo_4212(compra), Decimal("0.00"))
        self.assertFalse(
            MovimientoTesoreria.objects.filter(origen_tipo="DEVOLUCION_PROVEEDOR", origen_id=nota.pk).exists()
        )

    def test_rechaza_reembolso_cuando_no_hay_pago_en_exceso(self):
        compra = self.comprar("1", "100")
        linea = compra.lineas.get()
        with self.assertRaisesMessage(CompraError, "no hay reembolso"):
            registrar_devolucion(
                compra=compra,
                fecha=date(2026, 11, 12),
                serie="FC03",
                numero="1",
                motivo_codigo="07",
                cantidades={linea.pk: Decimal("1")},
                cuenta_reembolso=self.bbva,
            )
        self.assertFalse(NotaCreditoCompra.objects.filter(compra=compra).exists())
        capa = CapaFIFO.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        self.assertEqual(capa.cantidad_restante, Decimal("1"))

    def test_no_permite_devolver_mas_de_lo_comprado_ni_compras_con_flete(self):
        with self.assertRaisesMessage(CompraError, "solo quedan"):
            self.devolver(cantidad="3")
        self.assertFalse(NotaCreditoCompra.objects.filter(compra=self.compra).exists())

        con_flete = self.comprar("1", "100", flete="50")
        linea = con_flete.lineas.get()
        with self.assertRaisesMessage(CompraError, "costos de internamiento"):
            registrar_devolucion(
                compra=con_flete,
                fecha=date(2026, 11, 12),
                serie="FC04",
                numero="1",
                motivo_codigo="07",
                cantidades={linea.pk: Decimal("1")},
            )

    def test_devolucion_total_exige_todas_las_unidades_y_no_admite_notas_previas(self):
        with self.assertRaisesMessage(CompraError, "devolución total"):
            self.devolver(cantidad="1", motivo_codigo="06")

        self.devolver(cantidad="1")
        with self.assertRaisesMessage(CompraError, ""):
            registrar_devolucion(
                compra=self.compra,
                fecha=date(2026, 11, 13),
                serie="FC01",
                numero="2",
                motivo_codigo="06",
                cantidades={self.linea.pk: Decimal("1")},
            )

    def test_la_nota_reduce_el_saldo_que_pagar_permite_pagar(self):
        compra = self.comprar("2", "100")
        linea = compra.lineas.get()
        registrar_devolucion(
            compra=compra,
            fecha=date(2026, 11, 12),
            serie="FC05",
            numero="1",
            motivo_codigo="07",
            cantidades={linea.pk: Decimal("1")},
        )
        pagar(compra, cuenta=self.bbva, fecha=date(2026, 11, 13))
        compra.refresh_from_db()
        self.assertEqual(compra.monto_pagado, Decimal("118.00"))
        self.assertTrue(compra.pagada)
        with self.assertRaisesMessage(CompraError, "cubierta por notas"):
            pagar(compra, cuenta=self.bbva, fecha=date(2026, 11, 14), importe=Decimal("1"))

    def test_reembolso_posterior_parcial_y_sin_doble_cobro(self):
        nota = self.devolver()  # queda pendiente de reembolso
        self.assertFalse(nota.reembolsado)

        registrar_reembolso(nota=nota, cuenta=self.bbva, fecha=date(2026, 11, 13), importe="50")
        nota.refresh_from_db()
        self.assertEqual(nota.importe_reembolsado, Decimal("50.00"))
        self.assertEqual(saldo_4212(self.compra), Decimal("-68.00"))

        registrar_reembolso(nota=nota, cuenta=self.bbva, fecha=date(2026, 11, 14))
        self.assertEqual(saldo_4212(self.compra), Decimal("0.00"))
        with self.assertRaisesMessage(CompraError, "No hay reembolso pendiente"):
            registrar_reembolso(nota=nota, cuenta=self.bbva, fecha=date(2026, 11, 15))

    def test_la_reversion_interna_no_borra_una_devolucion_registrada(self):
        self.devolver()
        from compras.reversion import revertir_registro

        with self.assertRaisesMessage(CompraError, "notas de crédito"):
            revertir_registro(
                empresa=self.empresa,
                compra_id=self.compra.pk,
                motivo="Intento de corrección posterior",
                usuario=None,
            )

    def test_casillas_y_registro_de_compras_revierten_el_igv(self):
        self.devolver()

        datos = calcular(self.empresa, 2026, 11)
        self.assertEqual(datos["compras_base"], Decimal("100.00"))
        self.assertEqual(datos["compras_igv"], Decimal("18.00"))

        usuario = get_user_model().objects.create_superuser(username="devoluciones", password="test")
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("reportes:registro_compras"), {"periodo": "2026-11"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "FC01-1")
        self.assertContains(respuesta, "-118,00")

        exportado = self.client.get(reverse("reportes:exportar_compras"), {"periodo": "2026-11"})
        texto = exportado.content.decode("utf-8-sig")
        self.assertIn("07,FC01,1", texto)
        self.assertIn("-118.00", texto)

    def test_la_anotacion_ubica_la_reversion_del_igv_en_el_periodo_del_rce(self):
        self.devolver(fecha_anotacion=date(2026, 12, 5))

        noviembre = calcular(self.empresa, 2026, 11)
        self.assertEqual(noviembre["compras_igv"], Decimal("36.00"))
        diciembre = calcular(self.empresa, 2026, 12)
        self.assertEqual(diciembre["compras_base"], Decimal("-100.00"))
        self.assertEqual(diciembre["compras_igv"], Decimal("-18.00"))

    def test_no_permite_registrar_dos_veces_la_misma_nota(self):
        self.devolver(cantidad="1")
        with self.assertRaisesMessage(CompraError, "ya está registrada"):
            self.devolver(cantidad="1")

    def test_pantalla_de_devolucion_registra_la_nota(self):
        usuario = get_user_model().objects.create_superuser(username="registrador", password="test")
        self.client.force_login(usuario)
        url = reverse("compras:devolucion", args=[self.compra.pk])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)

        respuesta = self.client.post(
            url,
            {
                "fecha": "2026-11-12",
                "serie": "FC01",
                "numero": "1",
                "motivo_codigo": "07",
                "descripcion": "Devolución de una unidad dañada",
                f"cantidad_{self.linea.pk}": "1",
                "cuenta_reembolso": self.bbva.pk,
                "canal": "TRANSFERENCIA",
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        nota = NotaCreditoCompra.objects.get(compra=self.compra)
        self.assertEqual(nota.total, Decimal("118.00"))
        self.assertContains(respuesta, "FC01-1")

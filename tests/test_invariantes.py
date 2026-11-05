"""Invariantes que no pueden fallar en un libro contable.

Si alguno de estos tests se rompe, el sistema dejó de ser confiable para
llevar contabilidad. No son tests de cobertura: son el contrato del motor.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.db.models import Sum
from django.test import TestCase

from catalogo.models import CuentaTesoreria, Producto, Tercero
from compras.models import Compra, CompraLinea, CostoAdicional
from compras.models_gasto import Gasto
from compras.servicios import confirmar as confirmar_compra
from compras.servicios import registrar_gasto
from contabilidad.calculos import calcular_linea
from contabilidad.models import Asiento, AsientoLinea, Cuenta
from contabilidad.moneda import a_soles
from core.models import Empresa, Periodo, TipoCambio
from inventario.models import CapaFIFO, ConsumoCapa, MovimientoStock
from ventas.models import Venta, VentaLinea
from ventas.models_guia import GuiaRemision
from ventas.servicios import VentaError, confirmar as confirmar_venta
from ventas.servicios import emitir_nota_credito

CENT = Decimal("0.01")


class BaseContable(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        call_command("cargar_pcge", verbosity=0)
        call_command("sembrar_tilmux", verbosity=0)
        call_command("sembrar_base", verbosity=0)
        call_command("sembrar_reglas", verbosity=0)
        call_command("sembrar_productos", verbosity=0)

        cls.empresa = Empresa.objects.get(ruc="20615841961")
        cls.producto = Producto.objects.get(sku="TIL-000001")
        cls.proveedor = Tercero.objects.create(
            rol="PROVEEDOR",
            tipo_doc="RUC",
            numero_doc="20100000001",
            nombre="Proveedor de prueba",
        )
        cls.cliente = Tercero.objects.create(
            rol="CLIENTE",
            tipo_doc="RUC",
            numero_doc="20200000002",
            nombre="Cliente de prueba",
        )
        cls.bbva = CuentaTesoreria.objects.get(empresa=cls.empresa, nombre="BBVA")
        cls.pasarela = CuentaTesoreria.objects.get(
            empresa=cls.empresa, nombre="Mercado Pago"
        )

    # --- ayudas -------------------------------------------------------

    def comprar(
        self,
        cantidad: str,
        costo_unitario: str,
        *,
        fecha: date = date(2026, 11, 10),
        flete: str = "0",
        con_credito: bool = True,
    ) -> Compra:
        cantidad_d = Decimal(cantidad)
        costo_d = Decimal(costo_unitario)
        base = (cantidad_d * costo_d).quantize(CENT)
        igv = (base * Decimal("0.18")).quantize(CENT)

        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=fecha,
            tipo_doc="FACTURA",
            serie="F001",
            numero=f"{Compra.objects.count() + 1:04d}",
            con_credito=con_credito,
        )
        CompraLinea.objects.create(
            compra=compra,
            orden=1,
            producto=self.producto,
            cantidad=cantidad_d,
            precio_unitario=costo_d,
            base=base,
            igv=igv,
            total=base + igv,
        )
        if Decimal(flete) > 0:
            CostoAdicional.objects.create(
                compra=compra,
                concepto="Flete",
                base=Decimal(flete),
                igv=Decimal("0"),
                total=Decimal(flete),
            )
        confirmar_compra(compra)
        return Compra.objects.get(pk=compra.pk)

    def vender(
        self,
        cantidad: str,
        precio_con_igv: str,
        *,
        fecha: date = date(2026, 11, 20),
    ) -> Venta:
        base, igv, total = calcular_linea(
            Decimal(cantidad), Decimal(precio_con_igv), True
        )
        venta = Venta.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            cliente_nombre=self.cliente.nombre,
            fecha=fecha,
            tipo_doc="FACTURA",
            serie="E001",
            numero=f"{Venta.objects.count() + 1:04d}",
            condicion="CONTADO",
            cuenta=self.pasarela,
            canal="TARJETA",
        )
        VentaLinea.objects.create(
            venta=venta,
            orden=1,
            producto=self.producto,
            cantidad=Decimal(cantidad),
            precio_unitario=Decimal(precio_con_igv),
            base=base,
            igv=igv,
            total=total,
        )
        confirmar_venta(venta)
        return Venta.objects.get(pk=venta.pk)

    def capas(self):
        return CapaFIFO.objects.filter(empresa=self.empresa, producto=self.producto)


class InvarianteAsiento(BaseContable):
    def test_el_asiento_de_compra_cuadra(self):
        compra = self.comprar("10", "100")
        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)

        debe = asiento.lineas.aggregate(s=Sum("debe"))["s"]
        haber = asiento.lineas.aggregate(s=Sum("haber"))["s"]

        self.assertEqual(debe, haber)
        self.assertEqual(debe, Decimal("1180.00"))

    def test_el_asiento_de_venta_cuadra(self):
        self.comprar("10", "100")
        venta = self.vender("2", "250")
        asiento = Asiento.objects.get(
            origen_tipo="VENTA", origen_id=venta.pk, tipo_operacion="VENTA"
        )

        debe = asiento.lineas.aggregate(s=Sum("debe"))["s"]
        haber = asiento.lineas.aggregate(s=Sum("haber"))["s"]

        self.assertEqual(debe, haber)

    def test_la_base_rechaza_un_asiento_descuadrado(self):
        periodo = Periodo.objects.get(empresa=self.empresa, anio=2026, mes=11)
        cuenta = Cuenta.objects.get(version="2026", codigo="101")
        asiento = Asiento.objects.create(
            empresa=self.empresa,
            periodo=periodo,
            numero=999,
            fecha=date(2026, 11, 25),
            tipo_operacion="COMPRA",
            glosa="Asiento descuadrado a propósito",
        )

        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                AsientoLinea.objects.create(
                    asiento=asiento,
                    orden=1,
                    cuenta=cuenta,
                    debe=Decimal("100.00"),
                    haber=Decimal("0.00"),
                    monto_contable=Decimal("100.00"),
                    monto_tributario=Decimal("100.00"),
                )
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class InvarianteCosto(BaseContable):
    def test_el_costo_incluye_los_costos_de_internamiento(self):
        compra = self.comprar("10", "100", flete="100")
        linea = compra.lineas.get()

        self.assertEqual(linea.costo_unitario_final, Decimal("110.0000000000"))
        self.assertEqual(self.capas().get().costo_unitario, Decimal("110.0000000000"))

    def test_fifo_consume_la_capa_mas_antigua(self):
        self.comprar("1", "100", fecha=date(2026, 11, 1))
        self.comprar("1", "200", fecha=date(2026, 11, 2))
        venta = self.vender("2", "500", fecha=date(2026, 11, 20))

        self.assertEqual(venta.costo_venta, Decimal("300.00"))

        consumos = ConsumoCapa.objects.filter(movimiento__origen_id=venta.pk)
        self.assertEqual(consumos.count(), 2)
        self.assertEqual(
            [c.costo_unitario for c in consumos.order_by("capa__fecha")],
            [Decimal("100.0000000000"), Decimal("200.0000000000")],
        )

    def test_el_stock_se_conserva(self):
        self.comprar("10", "100")
        self.vender("4", "250")

        restante = self.capas().aggregate(s=Sum("cantidad_restante"))["s"]
        salidas = MovimientoStock.objects.filter(
            empresa=self.empresa,
            producto=self.producto,
            tipo=MovimientoStock.Tipo.SALIDA,
        ).aggregate(s=Sum("cantidad"))["s"]

        self.assertEqual(restante, Decimal("6.0000"))
        self.assertEqual(salidas, Decimal("4.0000"))
        self.assertEqual(restante + salidas, Decimal("10.0000"))

    def test_la_nota_de_credito_reingresa_al_costo_original(self):
        self.comprar("1", "100")
        venta = self.vender("1", "300")
        self.assertEqual(self.capas().aggregate(s=Sum("cantidad_restante"))["s"], Decimal("0"))

        emitir_nota_credito(
            venta=venta,
            fecha=date(2026, 11, 25),
            serie="FC01",
            numero="0001",
            motivo="Devolución",
        )

        capa = self.capas().filter(cantidad_restante__gt=0).get()
        self.assertEqual(capa.cantidad_restante, Decimal("1"))
        self.assertEqual(capa.costo_unitario, Decimal("100.0000000000"))


class InvarianteIgv(BaseContable):
    def test_precio_con_igv_se_descompone(self):
        base, igv, total = calcular_linea(Decimal("1"), Decimal("118"), True)

        self.assertEqual(base, Decimal("100.00"))
        self.assertEqual(igv, Decimal("18.00"))
        self.assertEqual(total, Decimal("118.00"))

    def test_precio_sin_igv_se_compone(self):
        base, igv, total = calcular_linea(Decimal("1"), Decimal("100"), False)

        self.assertEqual(base, Decimal("100.00"))
        self.assertEqual(igv, Decimal("18.00"))
        self.assertEqual(total, Decimal("118.00"))

    def test_la_venta_registra_base_e_igv_que_suman_el_total(self):
        self.comprar("10", "100")
        venta = self.vender("1", "706")

        self.assertEqual(venta.subtotal, Decimal("598.31"))
        self.assertEqual(venta.igv, Decimal("107.69"))
        self.assertEqual(venta.subtotal + venta.igv, venta.total)


class InvarianteComprobantes(BaseContable):
    def test_la_boleta_no_genera_credito_fiscal(self):
        cuenta = Cuenta.objects.get(version="2026", codigo="6391")
        gasto = registrar_gasto(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 5),
            tipo_doc="BOLETA",
            serie="B001",
            numero="00000001",
            base=Decimal("167.83"),
            igv=Decimal("30.21"),
            total=Decimal("198.04"),
            cuenta=cuenta,
            medio=self.bbva,
            con_credito=False,
            deducible=False,
        )

        asiento = Asiento.objects.get(origen_tipo="GASTO", origen_id=gasto.pk)
        importes = {linea.cuenta.codigo: linea.debe for linea in asiento.lineas.all()}

        self.assertEqual(gasto.base, Decimal("167.83"))
        self.assertEqual(gasto.igv, Decimal("30.21"))
        self.assertFalse(gasto.con_credito)
        self.assertFalse(gasto.deducible)
        self.assertNotIn("40111", importes)
        self.assertEqual(importes["6391"], Decimal("198.04"))

    def test_la_factura_separa_el_igv(self):
        cuenta = Cuenta.objects.get(version="2026", codigo="6391")
        gasto = registrar_gasto(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 5),
            tipo_doc="FACTURA",
            serie="F001",
            numero="00000002",
            base=Decimal("167.83"),
            igv=Decimal("30.21"),
            total=Decimal("198.04"),
            cuenta=cuenta,
            medio=self.bbva,
            con_credito=True,
        )

        asiento = Asiento.objects.get(origen_tipo="GASTO", origen_id=gasto.pk)
        importes = {linea.cuenta.codigo: linea.debe for linea in asiento.lineas.all()}

        self.assertTrue(gasto.con_credito)
        self.assertEqual(importes["40111"], Decimal("30.21"))
        self.assertEqual(importes["6391"], Decimal("167.83"))


    def test_la_compra_con_boleta_mete_el_igv_al_costo(self):
        compra = self.comprar("1", "100", con_credito=False)

        capa = self.capas().get()
        self.assertEqual(capa.costo_unitario, Decimal("118.0000000000"))

        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        importes = {linea.cuenta.codigo: linea.debe for linea in asiento.lineas.all()}

        self.assertNotIn("40111", importes)
        self.assertEqual(importes["20111"], Decimal("118.00"))


class InvarianteMoneda(BaseContable):
    def test_convierte_dolares_con_el_tipo_de_cambio_de_sunat(self):
        TipoCambio.objects.create(
            fecha=date(2026, 11, 5),
            compra=Decimal("3.447"),
            venta=Decimal("3.452"),
        )

        soles, tasa = a_soles(Decimal("100"), "USD", date(2026, 11, 5))

        self.assertEqual(soles, Decimal("345.20"))
        self.assertEqual(tasa, Decimal("3.452"))

    def test_un_importe_en_soles_no_se_convierte(self):
        soles, tasa = a_soles(Decimal("198.04"), "PEN", date(2026, 11, 5))

        self.assertEqual(soles, Decimal("198.04"))
        self.assertEqual(tasa, Decimal("1"))

    def test_la_guia_se_vincula_a_su_venta(self):
        self.comprar("10", "100")
        venta = self.vender("1", "250")

        guia = GuiaRemision.objects.create(
            empresa=self.empresa,
            venta=venta,
            tipo="GRE_REMITENTE",
            serie="EG07",
            numero="1",
            fecha=date(2026, 11, 20),
            documento_referencia=f"{venta.serie}-{venta.numero}",
        )

        self.assertEqual(venta.guias.count(), 1)
        self.assertEqual(venta.guias.first(), guia)


class InvarianteInmutabilidad(BaseContable):
    def test_una_venta_confirmada_no_se_confirma_dos_veces(self):
        self.comprar("10", "100")
        venta = self.vender("1", "250")

        with self.assertRaises(VentaError):
            confirmar_venta(venta)

        self.assertEqual(
            MovimientoStock.objects.filter(
                empresa=self.empresa,
                producto=self.producto,
                tipo=MovimientoStock.Tipo.SALIDA,
            ).count(),
            1,
        )

"""Documentos incompletos, PDT 621 y confirmación."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from compras.models import Compra, CompraLinea
from compras.servicios import CompraError
from compras.servicios import confirmar as confirmar_compra
from reportes.casillas import calcular, casillas_documento
from tests.test_invariantes import BaseContable


class InvarianteDocumentos(BaseContable):
    def test_una_compra_valida_aporta_107_y_108(self):
        compra = self.comprar("1", "100")

        filas = casillas_documento(compra)

        self.assertEqual([f["casilla"] for f in filas], ["107", "108"])
        self.assertEqual(filas[0]["importe"], Decimal("100.00"))
        self.assertEqual(filas[1]["importe"], Decimal("18.00"))

    def test_una_venta_aporta_100_y_101(self):
        self.comprar("1", "100")
        venta = self.vender("1", "118")

        filas = casillas_documento(venta)

        self.assertEqual([f["casilla"] for f in filas], ["100", "101"])
        self.assertEqual(filas[0]["importe"], Decimal("100.00"))
        self.assertEqual(filas[1]["importe"], Decimal("18.00"))

    def test_una_compra_pendiente_no_se_confirma_ni_va_al_621(self):
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 10),
            tipo_doc="FACTURA",
            serie="F001",
            numero="9999",
            estado=Compra.Estado.PENDIENTE,
            con_credito=True,
        )
        CompraLinea.objects.create(
            compra=compra,
            orden=1,
            producto=self.producto,
            cantidad=Decimal("1"),
            precio_unitario=Decimal("100"),
            base=Decimal("100"),
            igv=Decimal("18"),
            total=Decimal("118"),
        )
        compra.subtotal = Decimal("100")
        compra.igv = Decimal("18")
        compra.total = Decimal("118")
        compra.save()

        with self.assertRaises(CompraError):
            confirmar_compra(compra)
        self.assertEqual(casillas_documento(compra)[0]["casilla"], "—")
        self.assertEqual(
            calcular(self.empresa, 2026, 11)["compras_igv"],
            Decimal("0"),
        )

    def test_una_factura_sin_numero_no_se_confirma(self):
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 10),
            tipo_doc="FACTURA",
            serie="F001",
            numero="",
            estado=Compra.Estado.BORRADOR,
            con_credito=True,
        )
        CompraLinea.objects.create(
            compra=compra,
            orden=1,
            producto=self.producto,
            cantidad=Decimal("1"),
            precio_unitario=Decimal("100"),
            base=Decimal("100"),
            igv=Decimal("18"),
            total=Decimal("118"),
        )

        with self.assertRaises(CompraError):
            confirmar_compra(compra)

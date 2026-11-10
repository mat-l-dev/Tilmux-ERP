"""Siembra las reglas contables del MVP."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from contabilidad.models import Cuenta, Regla, ReglaLinea

D = ReglaLinea.Lado.DEBE
H = ReglaLinea.Lado.HABER
BASE = ReglaLinea.ImporteRef.BASE
IGV = ReglaLinea.ImporteRef.IGV
TOTAL = ReglaLinea.ImporteRef.TOTAL
COSTO = ReglaLinea.ImporteRef.COSTO
MEDIO = ReglaLinea.ImporteRef.MEDIO
MEDIO_DESTINO = ReglaLinea.ImporteRef.MEDIO_DESTINO
GASTO = ReglaLinea.ImporteRef.GASTO

REGLAS = {
    "COMPRA": (
        "Compra de mercadería",
        [("20111", D, BASE, "Ingreso a inventario"), ("40111", D, IGV, "IGV"), ("4212", H, TOTAL, "Por pagar")],
    ),
    "VENTA": (
        "Venta de mercadería",
        [("1212", D, TOTAL, "Por cobrar"), ("70121", H, BASE, "Ingreso"), ("40111", H, IGV, "IGV"), ("69121", D, COSTO, "Costo de venta"), ("20111", H, COSTO, "Salida de inventario")],  # noqa: E501
    ),
    "PAGO_PROVEEDOR": (
        "Pago a proveedor",
        [("4212", D, TOTAL, "Obligación"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "COBRO_CLIENTE": (
        "Cobro de cliente",
        [(None, D, MEDIO, "Ingreso de dinero"), ("1212", H, TOTAL, "Cobranza")],
    ),
    "GASTO_CON_IGV": (
        "Gasto con IGV",
        [(None, D, GASTO, "Gasto"), ("40111", D, IGV, "IGV"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "GASTO_SIN_IGV": (
        "Gasto sin IGV",
        [(None, D, GASTO, "Gasto"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "PROVISION_GASTO": (
        "Provisión de gasto",
        [(None, D, GASTO, "Gasto"), ("4212", H, TOTAL, "Por pagar")],
    ),
    "NOTA_CREDITO": (
        "Nota de crédito de venta",
        [("70911", D, BASE, "Devolución"), ("40111", D, IGV, "IGV"), ("1212", H, TOTAL, "Cobranza revertida"), ("69121", H, COSTO, "Costo revertido"), ("20111", D, COSTO, "Reingreso de inventario")],  # noqa: E501
    ),
    "NOTA_DEBITO": (
        "Nota de débito de venta",
        [("1212", D, TOTAL, "Por cobrar"), ("7599", H, BASE, "Otros ingresos"), ("40111", H, IGV, "IGV")],
    ),
    "DEVOLUCION_COMPRA": (
        "Nota de crédito de compra (devolución al proveedor)",
        [("4212", D, TOTAL, "Deuda revertida"), ("40111", H, IGV, "IGV devuelto"), ("20111", H, COSTO, "Salida de inventario")],  # noqa: E501
    ),
    "REEMBOLSO_PROVEEDOR": (
        "Reembolso de proveedor por devolución",
        [(None, D, MEDIO, "Ingreso del reembolso"), ("4212", H, TOTAL, "Deuda revertida")],
    ),
    "APORTE_CAPITAL": (
        "Aporte de capital",
        [(None, D, MEDIO, "Ingreso de dinero"), ("1421", H, TOTAL, "Capital suscrito por cobrar")],
    ),
    "PRESTAMO_SOCIO": (
        "Préstamo de socio",
        [(None, D, MEDIO, "Ingreso de dinero"), ("4411", H, TOTAL, "Obligación")],
    ),
    "IGV_MENSUAL": (
        "Pago de IGV mensual",
        [("40111", D, TOTAL, "IGV del periodo"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "RENTA_MENSUAL": (
        "Renta RER del mes",
        [("881", D, TOTAL, "Impuesto corriente"), ("40171", H, TOTAL, "Por pagar")],
    ),
    "PAGO_RENTA": (
        "Pago de renta RER",
        [("40171", D, TOTAL, "Renta por pagar"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "CAPITAL_SUSCRITO": (
        "Capital suscrito en la constitución",
        [("1421", D, TOTAL, "Por cobrar a socios"), ("5011", H, TOTAL, "Capital")],
    ),
    "REEMBOLSO_SOCIO": (
        "Dinero de socio por reembolsar",
        [(None, D, MEDIO, "Ingreso de dinero"), ("4419", H, TOTAL, "Por reembolsar")],
    ),
    "TRANSFERENCIA": (
        "Transferencia entre cuentas propias",
        [(None, H, MEDIO, "Sale de"), (None, D, MEDIO_DESTINO, "Entra a")],
    ),
    "COMISION_PASARELA": (
        "Comisión de pasarela de pagos",
        [("6311", D, BASE, "Comisión"), ("40111", D, IGV, "IGV"), (None, H, MEDIO, "Salida de dinero")],
    ),
}


class Command(BaseCommand):
    help = "Crea o actualiza las reglas contables del MVP."

    @transaction.atomic
    def handle(self, *args, **options):
        cuentas = {c.codigo: c for c in Cuenta.objects.filter(version="2026")}
        creadas = 0

        for tipo, (nombre, lineas) in REGLAS.items():
            regla, Nueva = Regla.objects.update_or_create(
                tipo=tipo, defaults={"nombre": nombre}
            )
            regla.lineas.all().delete()
            faltantes = []
            for orden, (codigo, lado, ref, glosa) in enumerate(lineas, start=1):
                cuenta = cuentas.get(codigo) if codigo else None
                if codigo and cuenta is None:
                    faltantes.append(codigo)
                    continue
                ReglaLinea.objects.create(
                    regla=regla,
                    orden=orden,
                    cuenta=cuenta,
                    lado=lado,
                    importe_ref=ref,
                    glosa=glosa,
                )
            creadas += 1
            if faltantes:
                self.stdout.write(
                    self.style.WARNING(f"{tipo}: faltan cuentas {faltantes}")
                )

        self.stdout.write(self.style.SUCCESS(f"{creadas} reglas contables listas."))

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

REGLAS = {
    "COMPRA": (
        "Compra de mercadería",
        [("20111", D, BASE, "Ingreso a inventario"), ("40111", D, IGV, "IGV"), ("4212", H, TOTAL, "Por pagar")],
    ),
    "VENTA": (
        "Venta de mercadería",
        [("1212", D, TOTAL, "Por cobrar"), ("70121", H, BASE, "Ingreso"), ("40111", H, IGV, "IGV"), ("69121", D, COSTO, "Costo de venta"), ("20111", H, COSTO, "Salida de inventario")],
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
        [("6593", D, BASE, "Gasto"), ("40111", D, IGV, "IGV"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "GASTO_SIN_IGV": (
        "Gasto sin IGV",
        [("6391", D, TOTAL, "Gasto"), (None, H, MEDIO, "Salida de dinero")],
    ),
    "NOTA_CREDITO": (
        "Nota de crédito de venta",
        [("70911", D, BASE, "Devolución"), ("40111", D, IGV, "IGV"), ("1212", H, TOTAL, "Cobranza revertida"), ("69121", H, COSTO, "Costo revertido"), ("20111", D, COSTO, "Reingreso de inventario")],
    ),
    "APORTE_CAPITAL": (
        "Aporte de capital",
        [(None, D, MEDIO, "Ingreso de dinero"), ("5011", H, TOTAL, "Capital")],
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

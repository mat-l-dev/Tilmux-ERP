"""Siembra unidades, series y cuentas de tesorería de TILMUX."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import CuentaTesoreria, Serie, UnidadMedida
from contabilidad.models import Cuenta
from core.models import Empresa

UNIDADES = [
    ("NIU", "Unidad", 0),
    ("MTR", "Metro", 2),
    ("KGM", "Kilogramo", 2),
    ("ZZ", "Servicio", 0),
]

CUENTAS = {
    "BBVA": ("1061", CuentaTesoreria.Tipo.BANCO),
    "BCP": ("1061", CuentaTesoreria.Tipo.BANCO),
    "Mercado Pago": ("1031", CuentaTesoreria.Tipo.BILLETERA),
    "Caja": ("101", CuentaTesoreria.Tipo.CAJA),
}


class Command(BaseCommand):
    help = "Crea unidades, series y cuentas de tesorería."

    @transaction.atomic
    def handle(self, *args, **options):
        for codigo, nombre, decimales in UNIDADES:
            UnidadMedida.objects.update_or_create(
                codigo=codigo, defaults={"nombre": nombre, "decimales": decimales}
            )

        empresa = Empresa.objects.filter(ruc="20615841961").first()
        if empresa is None:
            self.stdout.write(self.style.ERROR("Falta la empresa TILMUX."))
            return

        for tipo, serie in (
            (Serie.Tipo.FACTURA, "E001"),
            (Serie.Tipo.BOLETA, "B001"),
            (Serie.Tipo.NOTA_CREDITO, "FC01"),
        ):
            Serie.objects.update_or_create(
                empresa=empresa, tipo=tipo, serie=serie, defaults={"activa": True}
            )

        cuentas = {c.codigo: c for c in Cuenta.objects.filter(version="2026")}
        for nombre, (codigo, tipo) in CUENTAS.items():
            CuentaTesoreria.objects.update_or_create(
                empresa=empresa,
                nombre=nombre,
                defaults={
                    "tipo": tipo,
                    "cuenta_contable": cuentas.get(codigo),
                    "activa": True,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Base lista: {UnidadMedida.objects.count()} unidades, "
                f"{Serie.objects.count()} series, "
                f"{CuentaTesoreria.objects.count()} cuentas de tesorería."
            )
        )

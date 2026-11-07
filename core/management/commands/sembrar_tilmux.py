"""Crea la empresa TILMUX y activa las cuentas que usa."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from contabilidad.models import Cuenta
from core.models import Empresa

CUENTAS_EN_USO = [
    "101", "1031", "1041", "1061", "1212", "122", "1421", "1699", "20111",
    "40111", "40171", "4211", "4212", "422", "4411", "4419", "4699", "5011", "5911",
    "5921", "6011", "6111", "6311", "63111", "6322", "6323", "6352", "6361",
    "6364", "6365", "6371", "6391", "6419", "653", "656", "6592", "6593",
    "6731", "6761", "69121", "70121", "70911", "7599", "7761", "881",
]


class Command(BaseCommand):
    help = "Siembra la empresa TILMUX y activa las cuentas que usa."

    @transaction.atomic
    def handle(self, *args, **options):
        empresa, creada = Empresa.objects.get_or_create(
            ruc="20615841961",
            defaults={
                "nombre": "TILMUX",
                "razon_social": "TILMUX S.A.C.",
                "regimen": Empresa.Regimen.RER,
                "moneda": "PEN",
                "activa": True,
            },
        )
        self.stdout.write(f"Empresa {'creada' if creada else 'existente'}: {empresa}")

        existentes = set(
            Cuenta.objects.filter(version="2026").values_list("codigo", flat=True)
        )
        activadas = Cuenta.objects.filter(
            version="2026", codigo__in=CUENTAS_EN_USO
        ).update(activa=True)
        faltantes = sorted(set(CUENTAS_EN_USO) - existentes)

        self.stdout.write(f"Cuentas activadas: {activadas} de {len(CUENTAS_EN_USO)}")
        if faltantes:
            self.stdout.write(
                self.style.WARNING(
                    "No existen en el PCGE 2026: " + ", ".join(faltantes)
                )
            )

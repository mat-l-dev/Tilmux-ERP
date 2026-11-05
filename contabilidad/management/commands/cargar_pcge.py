"""Carga el catálogo del PCGE desde el archivo oficial descargado."""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from contabilidad.models import Cuenta


def naturaleza_de(elemento: int) -> str:
    return "A" if elemento in (4, 5, 7) else "D"


def categoria_de(codigo: str) -> str:
    """Clasificación financiera (NIIF 18). Solo aplica a resultados."""
    if codigo.startswith(("67", "77")):
        return "FINANCIACION"
    if codigo.startswith("88") or codigo.startswith("891"):
        return "IMPUESTO"
    if codigo.startswith("655"):
        return "DISCONTINUADAS"
    if codigo[0] in {"6", "7", "8"}:
        return "OPERACION"
    return ""


class Command(BaseCommand):
    help = "Carga el catálogo PCGE 2026 en la tabla de cuentas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            default=str(Path(settings.BASE_DIR) / "data" / "pcge_2026.json"),
        )
        parser.add_argument("--pcge", default="2026")

    @transaction.atomic
    def handle(self, *args, **options):
        ruta = Path(options["archivo"])
        version = options["pcge"]
        if not ruta.exists():
            raise CommandError(f"No existe el archivo {ruta}")

        entradas = json.loads(ruta.read_text(encoding="utf-8"))
        padres = {e["parent_code"] for e in entradas if e["parent_code"]}

        filas = []
        for e in entradas:
            codigo = str(e["code"])
            elemento = int(codigo[0])
            filas.append(
                Cuenta(
                    version=version,
                    codigo=codigo,
                    nombre=e["name"][:255],
                    padre=(e["parent_code"] or "")[:6],
                    elemento=elemento,
                    naturaleza=naturaleza_de(elemento),
                    admite_movimiento=codigo not in padres,
                    categoria_financiera=categoria_de(codigo),
                )
            )

        Cuenta.objects.bulk_create(
            filas,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["version", "codigo"],
            update_fields=[
                "nombre",
                "padre",
                "elemento",
                "naturaleza",
                "admite_movimiento",
                "categoria_financiera",
            ],
        )

        total = Cuenta.objects.filter(version=version).count()
        movimientos = Cuenta.objects.filter(
            version=version, admite_movimiento=True
        ).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"PCGE {version}: {total} cuentas cargadas, {movimientos} admiten movimiento."
            )
        )

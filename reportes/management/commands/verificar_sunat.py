"""Compara los registros del sistema con las casillas de la vista preliminar."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import Empresa
from reportes.casillas import calcular


class Command(BaseCommand):
    help = "Muestra los totales del periodo con el número de casilla del formulario."

    def add_arguments(self, parser):
        parser.add_argument("--anio", type=int, required=True)
        parser.add_argument("--mes", type=int, required=True)
        parser.add_argument("--ruc", default="20615841961")

    def handle(self, *args, **options):
        empresa = Empresa.objects.filter(ruc=options["ruc"]).first()
        if empresa is None:
            raise CommandError("No existe la empresa indicada.")

        datos = calcular(empresa, options["anio"], options["mes"])

        self.stdout.write(f"Periodo {datos['anio']}-{datos['mes']:02d}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Ventas"))
        self.stdout.write(f"  100  Ventas netas gravadas (base)   {datos['ventas_base']:>12.2f}")
        self.stdout.write(f"  101  IGV de ventas                  {datos['ventas_igv']:>12.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Compras"))
        self.stdout.write(f"  107  Compras gravadas (base)        {datos['compras_base']:>12.2f}")
        self.stdout.write(f"  108  IGV de compras                 {datos['compras_igv']:>12.2f}")
        self.stdout.write(f"  120  Compras no gravadas            {datos['no_gravado']:>12.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resultado"))
        self.stdout.write(f"  140  Saldo a favor / por pagar      {datos['resultado']:>12.2f}")

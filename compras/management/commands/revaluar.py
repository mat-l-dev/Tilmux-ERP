"""Revalúa al cierre los saldos por pagar en moneda extranjera."""

from django.core.management.base import BaseCommand, CommandError

from compras.servicios import revaluar
from core.models import Empresa


class Command(BaseCommand):
    help = "Ajusta por tipo de cambio los saldos pendientes en dólares."

    def add_arguments(self, parser):
        parser.add_argument("--anio", type=int, required=True)
        parser.add_argument("--mes", type=int, required=True)
        parser.add_argument("--ruc", default="20615841961")

    def handle(self, *args, **options):
        empresa = Empresa.objects.filter(ruc=options["ruc"]).first()
        if empresa is None:
            raise CommandError("No existe la empresa indicada.")

        ajustadas, total = revaluar(empresa, options["anio"], options["mes"])
        self.stdout.write(
            self.style.SUCCESS(
                f"{ajustadas} compra(s) revaluada(s). Ajuste total: S/ {total}."
            )
        )

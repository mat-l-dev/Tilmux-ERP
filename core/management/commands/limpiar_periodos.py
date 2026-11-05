"""Elimina periodos que no tienen ningún movimiento."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.models import Asiento
from core.models import Empresa, Periodo
from tesoreria.models import MovimientoTesoreria
from ventas.models import Venta
from ventas.models_guia import GuiaRemision


def _vacio(empresa: Empresa, periodo: Periodo) -> bool:
    filtro = {
        "empresa": empresa,
        "fecha__year": periodo.anio,
        "fecha__month": periodo.mes,
    }
    if Asiento.objects.filter(**filtro).exists():
        return False
    if Venta.objects.filter(**filtro).exists():
        return False
    if Compra.objects.filter(**filtro).exists():
        return False
    if Gasto.objects.filter(**filtro).exists():
        return False
    if MovimientoTesoreria.objects.filter(**filtro).exists():
        return False
    if GuiaRemision.objects.filter(**filtro).exists():
        return False
    return True


class Command(BaseCommand):
    help = "Elimina periodos vacíos (sin asientos, ventas, compras ni gastos)."

    def add_arguments(self, parser):
        parser.add_argument("--empresa", help="RUC de la empresa (si hay varias)")
        parser.add_argument(
            "--si",
            action="store_true",
            help="No pide confirmación.",
        )

    def handle(self, *args, **options):
        consulta = Empresa.objects.filter(activa=True)
        if options["empresa"]:
            consulta = consulta.filter(ruc=options["empresa"])
        empresas = list(consulta)
        if not empresas:
            raise CommandError("No encontré la empresa.")

        vacios = [
            periodo
            for empresa in empresas
            for periodo in Periodo.objects.filter(empresa=empresa)
            if _vacio(empresa, periodo)
        ]
        if not vacios:
            self.stdout.write("No hay periodos vacíos.")
            return

        for periodo in vacios:
            self.stdout.write(f"  {periodo.empresa.razon_social} · {periodo.etiqueta}")

        if not options["si"]:
            try:
                respuesta = input(f"¿Eliminar {len(vacios)} periodo(s) vacío(s)? [s/N] ")
            except EOFError as exc:
                raise CommandError(
                    "Usa --si para confirmar sin preguntas."
                ) from exc
            if respuesta.strip().lower() not in {"s", "si", "sí"}:
                raise CommandError("Cancelado.")

        total = Periodo.objects.filter(pk__in=[p.pk for p in vacios]).delete()[0]
        self.stdout.write(self.style.SUCCESS(f"{total} periodo(s) eliminados."))

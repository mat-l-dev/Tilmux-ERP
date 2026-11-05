"""Cierra el ejercicio anual y transfiere el resultado a 59."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from contabilidad.cierre import cerrar, estado, revertir
from contabilidad.servicios import ContabilidadError
from core.models import Empresa


class Command(BaseCommand):
    help = "Cierra el ejercicio: cuentas de resultado a 89 y luego a 59."

    def add_arguments(self, parser):
        parser.add_argument("--anio", type=int, required=True)
        parser.add_argument("--empresa", help="RUC de la empresa (si hay varias)")
        parser.add_argument(
            "--revertir",
            action="store_true",
            help="Anula los asientos de cierre del ejercicio.",
        )
        parser.add_argument(
            "--si",
            action="store_true",
            help="No pide confirmación.",
        )

    def handle(self, *args, **options):
        anio = options["anio"]
        consulta = Empresa.objects.filter(activa=True)
        if options["empresa"]:
            consulta = consulta.filter(ruc=options["empresa"])

        empresas = list(consulta)
        if not empresas:
            raise CommandError("No encontré la empresa.")
        if len(empresas) > 1 and not options["empresa"]:
            raise CommandError(
                "Hay varias empresas activas. Indica --empresa con el RUC."
            )
        empresa = empresas[0]

        if options["revertir"]:
            if not options["si"]:
                try:
                    respuesta = input(
                        f"¿Anular el cierre {anio} de {empresa.razon_social}? [s/N] "
                    )
                except EOFError as exc:
                    raise CommandError(
                        "Usa --si para confirmar sin preguntas."
                    ) from exc
                if respuesta.strip().lower() not in {"s", "si", "sí"}:
                    raise CommandError("Cancelado.")
            try:
                total = revertir(empresa, anio)
            except ContabilidadError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(f"{total} asiento(s) de cierre anulados.")
            )
            return

        datos = estado(empresa, anio)
        self.stdout.write(f"{empresa.razon_social} · ejercicio {anio}")
        self.stdout.write(f"Ingresos: S/ {datos['ingresos']}")
        self.stdout.write(f"Gastos:   S/ {datos['gastos']}")
        self.stdout.write(f"Resultado: S/ {datos['resultado']}")
        if datos["abiertos"]:
            etiquetas = ", ".join(p.etiqueta for p in datos["abiertos"])
            raise CommandError(f"Cierra primero los periodos abiertos: {etiquetas}.")
        if datos["borradores"]:
            raise CommandError(
                f"Quedan {datos['borradores']} comprobante(s) en borrador."
            )
        if datos["cerrado"]:
            raise CommandError(f"El ejercicio {anio} ya está cerrado.")

        if not options["si"]:
            try:
                respuesta = input(f"¿Cerrar el ejercicio {anio}? [s/N] ")
            except EOFError as exc:
                raise CommandError(
                    "Usa --si para confirmar sin preguntas."
                ) from exc
            if respuesta.strip().lower() not in {"s", "si", "sí"}:
                raise CommandError("Cancelado.")

        try:
            asientos = cerrar(empresa, anio)
        except ContabilidadError as exc:
            raise CommandError(str(exc)) from exc

        numeros = ", ".join(str(a.numero) for a in asientos)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ejercicio {anio} cerrado. Asientos: {numeros}."
            )
        )

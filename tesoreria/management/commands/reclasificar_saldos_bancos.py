"""Reclasifica el saldo histórico de la 1061 a las subcuentas por banco."""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Empresa
from tesoreria.subcuentas import reclasificar_historico


class Command(BaseCommand):
    help = (
        "Mueve el saldo histórico de la 1061 a la subcuenta de cada banco. "
        "Sin --aplicar solo muestra lo que haría (dry-run)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fecha", required=True, help="Fecha del asiento (AAAA-MM-DD).")
        parser.add_argument("--aplicar", action="store_true", help="Registra los asientos.")
        parser.add_argument("--empresa", type=int, default=None, help="Solo esta empresa.")

    def handle(self, *args, **opciones):
        try:
            fecha = date.fromisoformat(opciones["fecha"])
        except ValueError:
            raise CommandError("Indica una fecha válida (AAAA-MM-DD).") from None
        empresas = Empresa.objects.all()
        if opciones["empresa"]:
            empresas = empresas.filter(pk=opciones["empresa"])
        for empresa in empresas:
            with transaction.atomic():
                movimientos = reclasificar_historico(empresa, fecha)
                if not opciones["aplicar"]:
                    transaction.set_rollback(True)
            if not movimientos:
                self.stdout.write(f"{empresa.nombre}: sin diferencias por reclasificar.")
                continue
            for movimiento in movimientos:
                self.stdout.write(
                    f"{empresa.nombre}: {movimiento['cuenta'].nombre} → "
                    f"{movimiento['subcuenta'].codigo} por S/ {movimiento['importe']} "
                    f"{'registrado' if opciones['aplicar'] else '(dry-run)'}."
                )
        if not opciones["aplicar"]:
            self.stdout.write(self.style.WARNING("Dry-run: no se guardó ningún asiento. Usa --aplicar."))

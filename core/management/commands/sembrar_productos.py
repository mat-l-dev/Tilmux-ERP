"""Carga los productos iniciales de TILMUX."""

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Producto, UnidadMedida

PRODUCTOS = [
    ("TIL-000001", "Starlink Mini Kit"),
    ("TIL-000002", "Starlink Standard 4 X Kit"),
]


class Command(BaseCommand):
    help = "Crea los dos productos iniciales."

    @transaction.atomic
    def handle(self, *args, **options):
        unidad = UnidadMedida.objects.get(codigo="NIU")
        for sku, nombre in PRODUCTOS:
            Producto.objects.update_or_create(
                sku=sku,
                defaults={"nombre": nombre, "unidad": unidad, "tipo": "BIEN"},
            )
        self.stdout.write(
            self.style.SUCCESS(f"{Producto.objects.count()} productos en catálogo.")
        )

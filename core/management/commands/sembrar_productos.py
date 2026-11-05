"""Carga los productos iniciales de TILMUX."""

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Producto, UnidadMedida

PRODUCTOS = [
    ("TIL-000001", "Starlink Mini Kit (histórico)", False),
    ("TIL-000002", 'Monitor Gamer Samsung 25" 240Hz', False),
    ("TIL-000003", "Starlink Mini X", True),
]


class Command(BaseCommand):
    help = "Crea los productos iniciales de TILMUX."

    @transaction.atomic
    def handle(self, *args, **options):
        unidad = UnidadMedida.objects.get(codigo="NIU")
        for sku, nombre, activo in PRODUCTOS:
            Producto.objects.update_or_create(
                sku=sku,
                defaults={
                    "nombre": nombre,
                    "unidad": unidad,
                    "tipo": "BIEN",
                    "activo": activo,
                },
            )
        self.stdout.write(
            self.style.SUCCESS(f"{Producto.objects.count()} productos en catálogo.")
        )

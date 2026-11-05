"""Reasigna todas las referencias de un producto a otro SKU.

Sirve para corregir un producto mal creado sin romper el historial: las
compras, ventas, notas, cotizaciones, capas PEPS y movimientos de stock pasan
al producto correcto. No toca cantidades, costos ni asientos.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Producto
from compras.models import Compra, CompraLinea
from core.models import HistorialDocumento
from inventario.models import CapaFIFO, MovimientoStock
from ventas.models import CotizacionLinea, Venta, VentaLinea


class Command(BaseCommand):
    help = "Reasigna compras, ventas, capas y movimientos de un SKU a otro."

    def add_arguments(self, parser):
        parser.add_argument("--desde", required=True, help="SKU actual, por ejemplo TIL-000001")
        parser.add_argument("--hacia", required=True, help="SKU correcto, por ejemplo TIL-000003")
        parser.add_argument(
            "--desactivar",
            action="store_true",
            help="Desactiva el SKU de origen después de reasignar.",
        )
        parser.add_argument("--si", action="store_true", help="No pide confirmación.")

    def handle(self, *args, **options):
        desde = Producto.objects.filter(sku=options["desde"]).first()
        hacia = Producto.objects.filter(sku=options["hacia"]).first()
        if desde is None:
            raise CommandError(f"No existe el SKU {options['desde']}.")
        if hacia is None:
            raise CommandError(f"No existe el SKU {options['hacia']}.")
        if desde.pk == hacia.pk:
            raise CommandError("El SKU de origen y destino son el mismo.")
        if desde.unidad_id != hacia.unidad_id:
            raise CommandError(
                "Los productos tienen unidades distintas; no se pueden mezclar."
            )

        compras = list(
            CompraLinea.objects.filter(producto=desde)
            .values_list("compra_id", flat=True)
            .distinct()
        )
        ventas = list(
            VentaLinea.objects.filter(producto=desde)
            .values_list("venta_id", flat=True)
            .distinct()
        )
        empresas_compra = dict(
            Compra.objects.filter(pk__in=compras).values_list("pk", "empresa_id")
        )
        empresas_venta = dict(
            Venta.objects.filter(pk__in=ventas).values_list("pk", "empresa_id")
        )
        resumen = {
            "compras": CompraLinea.objects.filter(producto=desde).count(),
            "ventas": VentaLinea.objects.filter(producto=desde).count(),
            "cotizaciones": CotizacionLinea.objects.filter(producto=desde).count(),
            "capas": CapaFIFO.objects.filter(producto=desde).count(),
            "movimientos": MovimientoStock.objects.filter(producto=desde).count(),
        }
        self.stdout.write(
            f"{desde.sku} → {hacia.sku}: "
            + ", ".join(f"{clave} {valor}" for clave, valor in resumen.items())
        )

        if not options["si"]:
            try:
                respuesta = input("¿Reasignar todas las referencias? [s/N] ")
            except EOFError as exc:
                raise CommandError("Usa --si para confirmar sin preguntas.") from exc
            if respuesta.strip().lower() not in {"s", "si", "sí"}:
                raise CommandError("Cancelado.")

        with transaction.atomic():
            CompraLinea.objects.filter(producto=desde).update(producto=hacia)
            VentaLinea.objects.filter(producto=desde).update(producto=hacia)
            CotizacionLinea.objects.filter(producto=desde).update(producto=hacia)
            CapaFIFO.objects.filter(producto=desde).update(producto=hacia)
            MovimientoStock.objects.filter(producto=desde).update(producto=hacia)

            for compra_id in compras:
                empresa_id = empresas_compra.get(compra_id)
                if empresa_id:
                    HistorialDocumento.objects.create(
                        empresa_id=empresa_id,
                        tipo="COMPRA",
                        documento_id=compra_id,
                        accion="REASIGNACION",
                        detalle=f"Producto {desde.sku} → {hacia.sku}",
                    )
            for venta_id in ventas:
                empresa_id = empresas_venta.get(venta_id)
                if empresa_id:
                    HistorialDocumento.objects.create(
                        empresa_id=empresa_id,
                        tipo="VENTA",
                        documento_id=venta_id,
                        accion="REASIGNACION",
                        detalle=f"Producto {desde.sku} → {hacia.sku}",
                    )

            if options["desactivar"]:
                desde.activo = False
                desde.save(update_fields=["activo"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {resumen['compras']} líneas de compra, "
                f"{resumen['ventas']} de venta, {resumen['capas']} capas y "
                f"{resumen['movimientos']} movimientos pasaron a {hacia.sku}."
            )
        )

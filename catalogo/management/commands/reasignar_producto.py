"""Reasigna referencias de un producto a otro SKU, con filtro opcional por fecha.

Sirve para corregir un producto mal creado sin romper el historial: las
compras, ventas, cotizaciones, capas PEPS y movimientos de stock pasan al
producto correcto. No toca cantidades, costos ni asientos.

Para cambios de modelo por lote, usa ``--desde-fecha`` para mover solo las
compras/ventas del periodo nuevo y deja el historial anterior en el SKU viejo.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Producto
from compras.models import Compra, CompraLinea
from core.models import HistorialDocumento
from inventario.models import CapaFIFO, MovimientoStock
from ventas.models import CotizacionLinea, Venta, VentaLinea


def _filtrar(consulta, campo: str, desde: date | None, hasta: date | None):
    if desde is not None:
        consulta = consulta.filter(**{f"{campo}__gte": desde})
    if hasta is not None:
        consulta = consulta.filter(**{f"{campo}__lte": hasta})
    return consulta


class Command(BaseCommand):
    help = "Reasigna compras, ventas, capas y movimientos de un SKU a otro."

    def add_arguments(self, parser):
        parser.add_argument("--desde", required=True, help="SKU actual, por ejemplo TIL-000001")
        parser.add_argument("--hacia", required=True, help="SKU correcto, por ejemplo TIL-000003")
        parser.add_argument(
            "--desde-fecha",
            help="Mueve solo referencias desde esta fecha (AAAA-MM-DD).",
        )
        parser.add_argument(
            "--hasta-fecha",
            help="Mueve solo referencias hasta esta fecha (AAAA-MM-DD).",
        )
        parser.add_argument(
            "--desactivar",
            action="store_true",
            help="Desactiva el SKU de origen si ya no le queda ninguna referencia.",
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

        try:
            fecha_desde = (
                date.fromisoformat(options["desde_fecha"])
                if options["desde_fecha"]
                else None
            )
            fecha_hasta = (
                date.fromisoformat(options["hasta_fecha"])
                if options["hasta_fecha"]
                else None
            )
        except ValueError as exc:
            raise CommandError(
                "Las fechas deben tener formato AAAA-MM-DD."
            ) from exc

        compras_qs = _filtrar(
            CompraLinea.objects.filter(producto=desde),
            "compra__fecha",
            fecha_desde,
            fecha_hasta,
        )
        ventas_qs = _filtrar(
            VentaLinea.objects.filter(producto=desde),
            "venta__fecha",
            fecha_desde,
            fecha_hasta,
        )
        cotizaciones_qs = _filtrar(
            CotizacionLinea.objects.filter(producto=desde),
            "cotizacion__fecha",
            fecha_desde,
            fecha_hasta,
        )
        capas_qs = _filtrar(
            CapaFIFO.objects.filter(producto=desde),
            "fecha",
            fecha_desde,
            fecha_hasta,
        )
        movimientos_qs = _filtrar(
            MovimientoStock.objects.filter(producto=desde),
            "fecha",
            fecha_desde,
            fecha_hasta,
        )

        compras = list(compras_qs.values_list("compra_id", flat=True).distinct())
        ventas = list(ventas_qs.values_list("venta_id", flat=True).distinct())
        empresas_compra = dict(
            Compra.objects.filter(pk__in=compras).values_list("pk", "empresa_id")
        )
        empresas_venta = dict(
            Venta.objects.filter(pk__in=ventas).values_list("pk", "empresa_id")
        )
        resumen = {
            "compras": compras_qs.count(),
            "ventas": ventas_qs.count(),
            "cotizaciones": cotizaciones_qs.count(),
            "capas": capas_qs.count(),
            "movimientos": movimientos_qs.count(),
        }
        total_origen = sum(
            modelo.objects.filter(producto=desde).count()
            for modelo in (CompraLinea, VentaLinea, CotizacionLinea, CapaFIFO, MovimientoStock)
        )
        total_mover = sum(resumen.values())
        desactivar = options["desactivar"] and total_mover == total_origen
        if options["desactivar"] and not desactivar:
            self.stdout.write(
                self.style.WARNING(
                    "El SKU de origen todavía tiene referencias fuera del filtro; "
                    "no se desactivará."
                )
            )

        self.stdout.write(
            f"{desde.sku} → {hacia.sku}: "
            + ", ".join(f"{clave} {valor}" for clave, valor in resumen.items())
        )

        if not options["si"]:
            try:
                respuesta = input("¿Reasignar las referencias seleccionadas? [s/N] ")
            except EOFError as exc:
                raise CommandError("Usa --si para confirmar sin preguntas.") from exc
            if respuesta.strip().lower() not in {"s", "si", "sí"}:
                raise CommandError("Cancelado.")

        with transaction.atomic():
            compras_qs.update(producto=hacia)
            ventas_qs.update(producto=hacia)
            cotizaciones_qs.update(producto=hacia)
            capas_qs.update(producto=hacia)
            movimientos_qs.update(producto=hacia)

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

            if desactivar:
                desde.activo = False
                desde.save(update_fields=["activo"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Listo: {resumen['compras']} líneas de compra, "
                f"{resumen['ventas']} de venta, {resumen['capas']} capas y "
                f"{resumen['movimientos']} movimientos pasaron a {hacia.sku}."
            )
        )

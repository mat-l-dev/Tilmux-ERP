"""Entradas y salidas de stock valorizadas por PEPS."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from catalogo.models import Producto
from core.models import Empresa

from .models import CapaFIFO, ConsumoCapa, MovimientoStock

CENT = Decimal("0.01")
DIEZ = Decimal("0.0000000001")


class StockError(Exception):
    pass


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def entrar(
    *,
    empresa: Empresa,
    producto: Producto,
    fecha: date,
    cantidad: Decimal,
    costo_unitario: Decimal,
    origen_tipo: str = "",
    origen_id: int | None = None,
    glosa: str = "",
) -> CapaFIFO:
    cantidad = Decimal(cantidad)
    if cantidad <= 0:
        raise StockError("La cantidad de entrada debe ser mayor que cero.")

    capa = CapaFIFO.objects.create(
        empresa=empresa,
        producto=producto,
        fecha=fecha,
        cantidad_inicial=cantidad,
        cantidad_restante=cantidad,
        costo_unitario=Decimal(costo_unitario),
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )
    MovimientoStock.objects.create(
        empresa=empresa,
        producto=producto,
        fecha=fecha,
        tipo=MovimientoStock.Tipo.ENTRADA,
        cantidad=cantidad,
        costo_unitario=Decimal(costo_unitario),
        costo_total=_cent(cantidad * Decimal(costo_unitario)),
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        glosa=glosa[:255],
    )
    return capa


@transaction.atomic
def salir(
    *,
    empresa: Empresa,
    producto: Producto,
    fecha: date,
    cantidad: Decimal,
    origen_tipo: str = "",
    origen_id: int | None = None,
    glosa: str = "",
) -> MovimientoStock:
    cantidad = Decimal(cantidad)
    if cantidad <= 0:
        raise StockError("La cantidad de salida debe ser mayor que cero.")

    capas = (
        CapaFIFO.objects.select_for_update()
        .filter(empresa=empresa, producto=producto, cantidad_restante__gt=0)
        .order_by("fecha", "id")
    )

    pendiente = cantidad
    total = Decimal("0")
    tomas: list[tuple[CapaFIFO, Decimal, Decimal]] = []

    for capa in capas:
        if pendiente <= 0:
            break
        toma = min(capa.cantidad_restante, pendiente)
        costo = _cent(toma * capa.costo_unitario)
        capa.cantidad_restante -= toma
        capa.save(update_fields=["cantidad_restante"])
        tomas.append((capa, toma, costo))
        total += costo
        pendiente -= toma

    if pendiente > 0:
        raise StockError(
            f"Stock insuficiente de {producto.sku}: faltan {pendiente} {producto.unidad.codigo}."
        )

    costo_unitario = (total / cantidad).quantize(DIEZ, rounding=ROUND_HALF_UP)

    movimiento = MovimientoStock.objects.create(
        empresa=empresa,
        producto=producto,
        fecha=fecha,
        tipo=MovimientoStock.Tipo.SALIDA,
        cantidad=cantidad,
        costo_unitario=costo_unitario,
        costo_total=_cent(total),
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        glosa=glosa[:255],
    )

    ConsumoCapa.objects.bulk_create(
        [
            ConsumoCapa(
                movimiento=movimiento,
                capa=capa,
                cantidad=toma,
                costo_unitario=capa.costo_unitario,
                costo_total=costo,
            )
            for capa, toma, costo in tomas
        ]
    )
    return movimiento

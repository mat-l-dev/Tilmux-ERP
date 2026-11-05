"""Confirmación de compras: stock, costo y asiento en una sola transacción."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from contabilidad.servicios import Montos, postear
from inventario.servicios import entrar

from .models import Compra

CENT = Decimal("0.01")
DIEZ = Decimal("0.0000000001")


class CompraError(Exception):
    pass


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def confirmar(compra: Compra) -> Compra:
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.BORRADOR:
        raise CompraError("Solo se confirma una compra en borrador.")

    lineas = list(compra.lineas.select_related("producto", "producto__unidad"))
    if not lineas:
        raise CompraError("La compra no tiene líneas.")

    costos = list(compra.costos.all())
    asignado = {linea.pk: Decimal("0") for linea in lineas}

    for costo in costos:
        if costo.base <= 0:
            continue
        pesos = [
            linea.base if costo.criterio == costo.Criterio.VALOR else linea.cantidad
            for linea in lineas
        ]
        suma = sum(pesos, Decimal("0"))
        if suma <= 0:
            raise CompraError(
                f"No se puede prorratear «{costo.concepto}»: base cero."
            )
        acumulado = Decimal("0")
        for indice, linea in enumerate(lineas):
            if indice == len(lineas) - 1:
                parte = _cent(costo.base) - acumulado
            else:
                parte = _cent(costo.base * pesos[indice] / suma)
                acumulado += parte
            asignado[linea.pk] += parte

    for linea in lineas:
        if linea.cantidad <= 0:
            raise CompraError("Hay una línea con cantidad cero.")
        costo_total_linea = Decimal(linea.base) + asignado[linea.pk]
        costo_unitario = (costo_total_linea / linea.cantidad).quantize(
            DIEZ, rounding=ROUND_HALF_UP
        )
        linea.costo_unitario_final = costo_unitario
        linea.save(update_fields=["costo_unitario_final"])
        entrar(
            empresa=compra.empresa,
            producto=linea.producto,
            fecha=compra.fecha,
            cantidad=linea.cantidad,
            costo_unitario=costo_unitario,
            origen_tipo="COMPRA",
            origen_id=compra.pk,
            glosa=f"Compra {compra.serie}-{compra.numero}".strip(" -"),
        )

    base = _cent(sum((l.base for l in lineas), Decimal("0")) + sum((c.base for c in costos), Decimal("0")))
    igv = _cent(sum((l.igv for l in lineas), Decimal("0")) + sum((c.igv for c in costos), Decimal("0")))
    total = base + igv

    compra.subtotal = base
    compra.igv = igv
    compra.total = total
    compra.estado = Compra.Estado.CONFIRMADA
    compra.confirmado_en = timezone.now()
    compra.save(
        update_fields=["subtotal", "igv", "total", "estado", "confirmado_en"]
    )

    postear(
        empresa=compra.empresa,
        fecha=compra.fecha,
        tipo="COMPRA",
        glosa=f"Compra {compra.serie}-{compra.numero}".strip(" -"),
        montos=Montos(base=base, igv=igv, total=total),
        origen_tipo="COMPRA",
        origen_id=compra.pk,
    )
    return compra

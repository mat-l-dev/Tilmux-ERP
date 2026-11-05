"""Casillas del formulario IGV calculadas desde los registros del sistema."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from compras.models import Compra
from compras.models_gasto import Gasto
from ventas.models import NotaCredito, NotaDebito, Venta

CERO = Decimal("0")
TASA_RENTA_RER = Decimal("0.015")


def calcular(empresa, anio: int, mes: int) -> dict:
    desde = date(anio, mes, 1)
    hasta = date(anio, mes, calendar.monthrange(anio, mes)[1])

    ventas = Venta.objects.filter(
        empresa=empresa, estado=Venta.Estado.CONFIRMADA, fecha__range=(desde, hasta)
    )
    base_ventas = ventas.aggregate(s=Sum("subtotal"))["s"] or CERO
    igv_ventas = ventas.aggregate(s=Sum("igv"))["s"] or CERO

    creditos = NotaCredito.objects.filter(
        venta__empresa=empresa, fecha__range=(desde, hasta)
    ).aggregate(b=Sum("base"), i=Sum("igv"))
    base_ventas -= creditos["b"] or CERO
    igv_ventas -= creditos["i"] or CERO

    debitos = NotaDebito.objects.filter(
        venta__empresa=empresa, fecha__range=(desde, hasta)
    ).aggregate(b=Sum("base"), i=Sum("igv"))
    base_ventas += debitos["b"] or CERO
    igv_ventas += debitos["i"] or CERO

    compras = Compra.objects.filter(
        empresa=empresa,
        estado=Compra.Estado.CONFIRMADA,
        fecha__range=(desde, hasta),
        con_credito=True,
    )
    compras_gravadas = compras.filter(igv__gt=0)
    base_compras = compras_gravadas.aggregate(s=Sum("subtotal"))["s"] or CERO
    igv_compras = compras_gravadas.aggregate(s=Sum("igv"))["s"] or CERO

    # Compras con factura pero exoneradas o inafectas: van a la casilla 120.
    no_gravado = (
        compras.filter(igv=0).aggregate(s=Sum("subtotal"))["s"] or CERO
    )

    gastos = Gasto.objects.filter(
        empresa=empresa, fecha__range=(desde, hasta), con_credito=True
    ).exclude(tipo_doc="OTRO")
    gastos_gravados = gastos.filter(igv__gt=0)
    base_compras += gastos_gravados.aggregate(s=Sum("base"))["s"] or CERO
    igv_compras += gastos_gravados.aggregate(s=Sum("igv"))["s"] or CERO

    no_gravado += gastos.filter(igv=0).aggregate(s=Sum("base"))["s"] or CERO

    return {
        "anio": anio,
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "ventas_base": base_ventas,
        "ventas_igv": igv_ventas,
        "compras_base": base_compras,
        "compras_igv": igv_compras,
        "no_gravado": no_gravado,
        "resultado": igv_ventas - igv_compras,
        "renta": (base_ventas * TASA_RENTA_RER).quantize(Decimal("0.01")),
    }

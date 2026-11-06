"""Casillas del formulario IGV calculadas desde los registros del sistema."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce

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

    descuentos_base = CERO
    descuentos_igv = CERO
    for nota in NotaCredito.objects.filter(
        venta__empresa=empresa, fecha__range=(desde, hasta)
    ).select_related("venta"):
        if nota.venta.fecha.year == anio and nota.venta.fecha.month == mes:
            base_ventas -= nota.base
            igv_ventas -= nota.igv
        else:
            descuentos_base += nota.base
            descuentos_igv += nota.igv

    debitos = NotaDebito.objects.filter(
        venta__empresa=empresa, fecha__range=(desde, hasta)
    ).aggregate(b=Sum("base"), i=Sum("igv"))
    base_ventas += debitos["b"] or CERO
    igv_ventas += debitos["i"] or CERO

    compras = list(
        Compra.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha_tributaria__range=(desde, hasta),
            con_credito=True,
        ).select_related("proveedor")
    )
    # Sin RUC, serie o número no hay comprobante válido para el RCE.
    compras = [
        c
        for c in compras
        if c.serie.strip()
        and c.numero.strip()
        and len(c.proveedor.numero_doc) == 11
    ]
    compras_gravadas = [c for c in compras if c.igv > 0]
    base_compras = sum((c.subtotal for c in compras_gravadas), CERO)
    igv_compras = sum((c.igv for c in compras_gravadas), CERO)

    # Compras con factura pero exoneradas o inafectas: van a la casilla 120.
    no_gravado = sum((c.subtotal for c in compras if c.igv == 0), CERO)

    gastos = list(
        Gasto.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            con_credito=True,
            provision=False,
            fecha_tributaria__range=(desde, hasta),
        )
        .exclude(estado=Gasto.Estado.ANULADO)
        .exclude(tipo_doc="OTRO")
        .select_related("proveedor")
    )
    gastos = [
        g
        for g in gastos
        if g.serie.strip()
        and g.numero.strip()
        and len(g.proveedor.numero_doc) == 11
    ]
    gastos_gravados = [g for g in gastos if g.igv > 0]
    base_compras += sum((g.base for g in gastos_gravados), CERO)
    igv_compras += sum((g.igv for g in gastos_gravados), CERO)

    no_gravado += sum((g.base for g in gastos if g.igv == 0), CERO)

    base_renta = base_ventas - descuentos_base
    return {
        "anio": anio,
        "mes": mes,
        "desde": desde,
        "hasta": hasta,
        "ventas_base": base_ventas,
        "ventas_igv": igv_ventas,
        "descuentos_base": descuentos_base,
        "descuentos_igv": descuentos_igv,
        "compras_base": base_compras,
        "compras_igv": igv_compras,
        "no_gravado": no_gravado,
        "base_renta": base_renta,
        "resultado": igv_ventas - descuentos_igv - igv_compras,
        "renta": (base_renta * TASA_RENTA_RER).quantize(Decimal("0.01")),
    }


def casillas_documento(documento) -> list[dict]:
    """Casillas del PDT 621 a las que aporta una compra o una venta."""
    if isinstance(documento, Compra):
        if documento.estado != Compra.Estado.CONFIRMADA:
            return [
                {
                    "casilla": "—",
                    "concepto": "No va al 621 hasta confirmar la compra",
                    "importe": None,
                }
            ]
        if not documento.con_credito:
            return [
                {
                    "casilla": "—",
                    "concepto": "No otorga crédito fiscal (boleta u otro)",
                    "importe": None,
                }
            ]
        if not (
            documento.serie.strip()
            and documento.numero.strip()
            and len(documento.proveedor.numero_doc) == 11
        ):
            return [
                {
                    "casilla": "—",
                    "concepto": "Pendiente de RUC, serie o número: no va al 621",
                    "importe": None,
                }
            ]
        if documento.igv > 0:
            return [
                {
                    "casilla": "107",
                    "concepto": "Compras netas gravadas (base)",
                    "importe": documento.subtotal,
                },
                {
                    "casilla": "108",
                    "concepto": "IGV de compras",
                    "importe": documento.igv,
                },
            ]
        return [
            {
                "casilla": "120",
                "concepto": "Compras no gravadas",
                "importe": documento.subtotal,
            }
        ]

    if isinstance(documento, Venta):
        if documento.estado != Venta.Estado.CONFIRMADA:
            return [
                {
                    "casilla": "—",
                    "concepto": "No va al 621 hasta confirmar la venta",
                    "importe": None,
                }
            ]
        return [
            {
                "casilla": "100",
                "concepto": "Ventas netas gravadas (base)",
                "importe": documento.subtotal,
            },
            {
                "casilla": "101",
                "concepto": "IGV de ventas",
                "importe": documento.igv,
            },
        ]

    return []

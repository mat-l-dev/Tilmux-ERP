"""Totales documentales para comparar con propuestas SIRE, sin calcular crédito fiscal."""

import calendar
from datetime import date
from decimal import Decimal

from django.db.models.functions import Coalesce

from compras.comprobantes import evaluar_tributacion
from compras.models import Compra
from compras.models_gasto import Gasto
from ventas.models import NotaCredito, NotaDebito, Venta


def totales_documentales(*, empresa, anio, mes, registro):
    desde = date(anio, mes, 1)
    hasta = date(anio, mes, calendar.monthrange(anio, mes)[1])
    cero = Decimal("0")
    if registro == "ventas":
        ventas = Venta.objects.filter(empresa=empresa, estado=Venta.Estado.CONFIRMADA, fecha__range=(desde, hasta))
        creditos = NotaCredito.objects.filter(venta__empresa=empresa, fecha__range=(desde, hasta))
        debitos = NotaDebito.objects.filter(venta__empresa=empresa, fecha__range=(desde, hasta))
        monedas = (
            ventas.exclude(moneda="PEN").count()
            + creditos.exclude(venta__moneda="PEN").count()
            + (debitos.exclude(venta__moneda="PEN").count())
        )
        total = (
            sum((v.total for v in ventas.filter(moneda="PEN")), cero)
            - sum((n.total for n in creditos.filter(venta__moneda="PEN")), cero)
            + sum((n.total for n in debitos.filter(venta__moneda="PEN")), cero)
        )
        return {"total": total, "sin_credito": cero, "incompletos": 0, "otras_monedas": monedas}

    compras = (
        Compra.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha"))
        .filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha_tributaria__range=(desde, hasta),
            tipo_doc__in=["FACTURA", "BOLETA"],
        )
        .select_related("proveedor")
    )
    gastos = (
        Gasto.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha"))
        .filter(
            empresa=empresa,
            provision=False,
            fecha_tributaria__range=(desde, hasta),
            tipo_doc__in=["FACTURA", "BOLETA"],
        )
        .exclude(estado=Gasto.Estado.ANULADO)
        .select_related("proveedor")
    )
    total, sin_credito, incompletos, otras_monedas = cero, cero, 0, 0
    for documento in (*compras, *gastos):
        if isinstance(documento, Compra) and documento.moneda != "PEN":
            otras_monedas += 1
            continue
        evaluacion = evaluar_tributacion(documento)
        if evaluacion.requiere_revision:
            incompletos += 1
        if not documento.serie.strip() or not documento.numero.strip():
            continue
        total += documento.total
        if not evaluacion.incluido:
            sin_credito += documento.total
    return {"total": total, "sin_credito": sin_credito, "incompletos": incompletos, "otras_monedas": otras_monedas}

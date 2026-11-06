"""Ventas netas por fecha de los documentos, antes de IGV."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from ventas.models import NotaCredito, NotaDebito, Venta


def ventas_netas_por_mes(empresa, desde: date, hasta: date):
    valores = defaultdict(lambda: Decimal("0"))
    fuentes = (
        (Venta.objects.filter(empresa=empresa, estado=Venta.Estado.CONFIRMADA), "subtotal", 1),
        (NotaCredito.objects.filter(venta__empresa=empresa), "base", -1),
        (NotaDebito.objects.filter(venta__empresa=empresa), "base", 1),
    )
    for consulta, campo, signo in fuentes:
        filas = (
            consulta.filter(fecha__range=(desde, hasta)).order_by()
            .values("fecha__year", "fecha__month").annotate(importe=Sum(campo))
        )
        for fila in filas:
            valores[(fila["fecha__year"], fila["fecha__month"])] += signo * (fila["importe"] or 0)
    return valores

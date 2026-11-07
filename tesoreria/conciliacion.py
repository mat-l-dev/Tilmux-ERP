"""Búsqueda de candidatos, sin conciliar ni escribir en la base de datos."""

from datetime import timedelta

from .models import MovimientoTesoreria


def buscar_candidatos(*, empresa, cuenta, fecha, tipo, importe):
    """Los candidatos coinciden en cuenta, importe, tipo y fechas cercanas."""
    return MovimientoTesoreria.objects.filter(
        empresa=empresa, cuenta=cuenta, cuenta__empresa=empresa,
        fecha__range=(fecha - timedelta(days=3), fecha + timedelta(days=3)),
        tipo=tipo, importe=importe,
    ).order_by("fecha", "pk")

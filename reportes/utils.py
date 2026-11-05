"""Utilidades compartidas por los reportes."""

from __future__ import annotations

from datetime import date

from django.http import HttpRequest


def rango(request: HttpRequest) -> tuple[date, date]:
    """Rango de fechas del filtro; por defecto, el año en curso."""
    hoy = date.today()
    desde = request.GET.get("desde") or date(hoy.year, 1, 1).isoformat()
    hasta = request.GET.get("hasta") or hoy.isoformat()
    return date.fromisoformat(desde), date.fromisoformat(hasta)

"""Utilidades compartidas por los reportes."""

from __future__ import annotations

import calendar
from datetime import date

from django.http import HttpRequest


def rango(request: HttpRequest) -> tuple[date, date]:
    """Rango del reporte: por mes elegido o por fechas; si no, el año en curso."""
    periodo = request.GET.get("periodo")
    if periodo and "-" in periodo:
        anio, mes = (int(parte) for parte in periodo.split("-", 1))
        desde = date(anio, mes, 1)
        hasta = date(anio, mes, calendar.monthrange(anio, mes)[1])
        return desde, hasta

    hoy = date.today()
    desde = request.GET.get("desde") or date(hoy.year, 1, 1).isoformat()
    hasta = request.GET.get("hasta") or hoy.isoformat()
    return date.fromisoformat(desde), date.fromisoformat(hasta)

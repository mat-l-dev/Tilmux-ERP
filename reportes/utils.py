"""Utilidades compartidas por los reportes."""

from __future__ import annotations

import calendar
from datetime import date
from functools import wraps

from django.http import HttpRequest
from django.shortcuts import render
from django.utils import timezone

from core.filtros import periodo_mes


class FiltroReporteError(ValueError):
    pass


def filtros_seguros(vista):
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        try:
            return vista(request, *args, **kwargs)
        except FiltroReporteError as exc:
            return render(request, "reportes/filtro_invalido.html", {"error": str(exc)}, status=400)
    return protegida


def rango(request: HttpRequest) -> tuple[date, date]:
    """Rango del reporte: por mes elegido o por fechas; si no, el año en curso."""
    periodo = request.GET.get("periodo", "")
    desde_texto, hasta_texto = request.GET.get("desde", ""), request.GET.get("hasta", "")
    if periodo and (desde_texto or hasta_texto):
        raise FiltroReporteError("Elige un mes o un rango de fechas, no ambos.")
    if periodo:
        try:
            desde = periodo_mes(periodo)
        except ValueError as exc:
            raise FiltroReporteError(str(exc)) from None
        hasta = date(desde.year, desde.month, calendar.monthrange(desde.year, desde.month)[1])
        return desde, hasta

    hoy = timezone.localdate()
    try:
        desde = date.fromisoformat(desde_texto) if desde_texto else date(hoy.year, 1, 1)
        hasta = date.fromisoformat(hasta_texto) if hasta_texto else hoy
        if (desde_texto and desde.isoformat() != desde_texto) or (hasta_texto and hasta.isoformat() != hasta_texto):
            raise ValueError
    except ValueError:
        raise FiltroReporteError("Indica fechas válidas en formato AAAA-MM-DD.") from None
    if desde > hasta:
        raise FiltroReporteError("La fecha inicial no puede ser posterior a la fecha final.")
    return desde, hasta

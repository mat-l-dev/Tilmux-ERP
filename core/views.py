"""Vistas del núcleo."""

from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from contabilidad.models import Cuenta

from .context import empresa_actual
from .models import Empresa, Periodo


@login_required
def panel(request: HttpRequest) -> HttpResponse:
    empresa = empresa_actual(request)
    hoy = date.today()

    contexto = {
        "hoy": hoy,
        "cuentas_activas": Cuenta.objects.filter(activa=True).count(),
        "periodos_abiertos": (
            Periodo.objects.filter(empresa=empresa, estado=Periodo.Estado.ABIERTO).count()
            if empresa
            else 0
        ),
        # Los importes se llenan cuando existan los módulos de hechos.
        "saldo_tesoreria": "0.00",
        "ventas_mes": "0.00",
        "igv_por_pagar": "0.00",
        "renta_mes": "0.00",
        "periodo_actual": (
            Periodo.objects.filter(empresa=empresa, anio=hoy.year, mes=hoy.month).first()
            if empresa
            else None
        ),
    }
    return render(request, "core/panel.html", contexto)


@login_required
@require_POST
def cambiar_empresa(request: HttpRequest) -> HttpResponse:
    empresa_id = request.POST.get("empresa_id")
    if Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        request.session["empresa_id"] = int(empresa_id)
    return redirect(request.POST.get("siguiente") or "core:panel")


@login_required
def proximamente(request: HttpRequest) -> HttpResponse:
    messages.info(request, "Este módulo se construye en la siguiente sesión.")
    return redirect("core:panel")

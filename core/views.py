"""Vistas del núcleo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from compras.models import Compra
from contabilidad.models import AsientoLinea, Cuenta
from ventas.models import Venta

from .context import empresa_actual
from .models import Empresa, Periodo

TASA_RENTA_RER = Decimal("0.015")
MESES_CORTOS = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic")


def _meses_atras(anio: int, mes: int, pasos: int) -> tuple[int, int]:
    total = anio * 12 + (mes - 1) - pasos
    return total // 12, total % 12 + 1


def soles(valor) -> str:
    numero = Decimal(valor or 0).quantize(Decimal("0.01"))
    return f"{numero:,.2f}"


@login_required
def panel(request: HttpRequest) -> HttpResponse:
    empresa = empresa_actual(request)
    hoy = date.today()

    saldo = Decimal("0")
    ventas_base = Decimal("0")
    igv_ventas = Decimal("0")
    igv_compras = Decimal("0")

    if empresa:
        saldos = AsientoLinea.objects.filter(
            asiento__empresa=empresa,
            asiento__estado="CONFIRMADO",
            cuenta__codigo__in=["101", "1031", "1061"],
        ).aggregate(d=Sum("debe"), h=Sum("haber"))
        saldo = Decimal(saldos["d"] or 0) - Decimal(saldos["h"] or 0)

        ventas_mes = Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        )
        ventas_base = ventas_mes.aggregate(s=Sum("subtotal"))["s"] or 0
        igv_ventas = ventas_mes.aggregate(s=Sum("igv"))["s"] or 0

        compras_mes = Compra.objects.filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha__year=hoy.year,
            fecha__month=hoy.month,
        )
        igv_compras = compras_mes.aggregate(s=Sum("igv"))["s"] or 0

    igv = Decimal(igv_ventas) - Decimal(igv_compras)
    renta = Decimal(ventas_base) * TASA_RENTA_RER

    serie_meses = []
    maximo = Decimal("0")
    if empresa:
        inicio_anio, inicio_mes = _meses_atras(hoy.year, hoy.month, 5)
        acumulado = {
            (fila["fecha__year"], fila["fecha__month"]): fila["total"]
            for fila in Venta.objects.filter(
                empresa=empresa,
                estado=Venta.Estado.CONFIRMADA,
                fecha__gte=date(inicio_anio, inicio_mes, 1),
            )
            .values("fecha__year", "fecha__month")
            .annotate(total=Sum("total"))
        }
        for paso in range(5, -1, -1):
            anio, mes = _meses_atras(hoy.year, hoy.month, paso)
            valor = Decimal(acumulado.get((anio, mes), 0))
            maximo = max(maximo, valor)
            serie_meses.append(
                {"etiqueta": MESES_CORTOS[mes - 1], "valor": valor, "actual": paso == 0}
            )
    for punto in serie_meses:
        punto["altura"] = (
            int(punto["valor"] * 100 / maximo) if maximo > 0 else 0
        )
        punto["texto"] = soles(punto["valor"])

    contexto = {
        "hoy": hoy,
        "cuentas_activas": Cuenta.objects.filter(activa=True).count(),
        "periodos_abiertos": (
            Periodo.objects.filter(empresa=empresa, estado=Periodo.Estado.ABIERTO).count()
            if empresa
            else 0
        ),
        "saldo_tesoreria": soles(saldo),
        "ventas_mes": soles(ventas_base),
        "igv_por_pagar": soles(igv),
        "igv_nota": "Saldo a favor" if igv < 0 else "Después del crédito de compras",
        "renta_mes": soles(renta),
        "periodo_actual": (
            Periodo.objects.filter(empresa=empresa, anio=hoy.year, mes=hoy.month).first()
            if empresa
            else None
        ),
        "serie_meses": serie_meses,
        "maximo_mes": soles(maximo),
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

"""Estados financieros: situación financiera y resultados (NIIF 18)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from contabilidad.models import AsientoLinea
from core.context import empresa_actual

CERO = Decimal("0")

ACTIVO_CORRIENTE = (1, 2)
ACTIVO_NO_CORRIENTE = (3,)


def _lineas(empresa, desde: date, hasta: date):
    return (
        AsientoLinea.objects.filter(
            asiento__empresa=empresa,
            asiento__estado="CONFIRMADO",
            asiento__fecha__range=(desde, hasta),
        )
        .values(
            "cuenta__codigo",
            "cuenta__nombre",
            "cuenta__elemento",
            "cuenta__categoria_financiera",
        )
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )


@login_required
def estados(request):
    empresa = empresa_actual(request)
    hoy = date.today()
    desde = date(hoy.year, 1, 1)
    hasta = hoy

    if request.GET.get("hasta"):
        hasta = date.fromisoformat(request.GET["hasta"])
    if request.GET.get("desde"):
        desde = date.fromisoformat(request.GET["desde"])

    activo_corriente, activo_no_corriente = [], []
    pasivo, patrimonio = [], []
    operacion, financiacion, impuesto = [], [], []

    if empresa:
        for fila in _lineas(empresa, desde, hasta):
            neto = (fila["debe"] or CERO) - (fila["haber"] or CERO)
            if neto == 0:
                continue
            elemento = fila["cuenta__elemento"]
            registro = {
                "codigo": fila["cuenta__codigo"],
                "nombre": fila["cuenta__nombre"],
                "importe": abs(neto),
            }
            if elemento in ACTIVO_CORRIENTE:
                activo_corriente.append(registro)
            elif elemento in ACTIVO_NO_CORRIENTE:
                activo_no_corriente.append(registro)
            elif elemento == 4:
                pasivo.append(registro)
            elif elemento == 5:
                patrimonio.append(registro)
            elif elemento in (6, 7, 8):
                categoria = fila["cuenta__categoria_financiera"] or "OPERACION"
                if elemento == 8:
                    categoria = "IMPUESTO"
                destino = {
                    "OPERACION": operacion,
                    "FINANCIACION": financiacion,
                    "IMPUESTO": impuesto,
                }.get(categoria, operacion)
                destino.append(registro)

    def suma(items) -> Decimal:
        return sum((i["importe"] for i in items), CERO)

    total_activo_corriente = suma(activo_corriente)
    total_activo_no_corriente = suma(activo_no_corriente)
    total_activo = total_activo_corriente + total_activo_no_corriente
    total_pasivo = suma(pasivo)
    total_patrimonio = suma(patrimonio)

    ingresos = sum((i["importe"] for i in operacion if i["codigo"].startswith("7")), CERO)
    gastos = sum((i["importe"] for i in operacion if i["codigo"][0] in "68"), CERO)
    resultado_operacion = ingresos - gastos

    ingresos_fin = sum(
        (i["importe"] for i in financiacion if i["codigo"].startswith("7")), CERO
    )
    gastos_fin = sum(
        (i["importe"] for i in financiacion if i["codigo"][0] in "68"), CERO
    )
    resultado_financiacion = ingresos_fin - gastos_fin

    resultado_antes_impuesto = resultado_operacion + resultado_financiacion
    gasto_impuesto = suma(impuesto)
    resultado_neto = resultado_antes_impuesto - gasto_impuesto
    total_patrimonio_resultado = total_patrimonio + resultado_neto

    contexto = {
        "desde": desde,
        "hasta": hasta,
        "activo_corriente": activo_corriente,
        "activo_no_corriente": activo_no_corriente,
        "pasivo": pasivo,
        "patrimonio": patrimonio,
        "total_activo_corriente": total_activo_corriente,
        "total_activo_no_corriente": total_activo_no_corriente,
        "total_activo": total_activo,
        "total_pasivo": total_pasivo,
        "total_patrimonio": total_patrimonio,
        "total_pasivo_patrimonio": total_pasivo + total_patrimonio_resultado,
        "ingresos": ingresos,
        "gastos": gastos,
        "resultado_operacion": resultado_operacion,
        "resultado_financiacion": resultado_financiacion,
        "resultado_antes_impuesto": resultado_antes_impuesto,
        "gasto_impuesto": gasto_impuesto,
        "resultado_neto": resultado_neto,
        "total_patrimonio_resultado": total_patrimonio_resultado,
        "descuadre": total_activo - (total_pasivo + total_patrimonio_resultado),
    }
    return render(request, "reportes/eeff.html", contexto)

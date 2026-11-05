"""Estados financieros: situación financiera, resultados y cambios en el patrimonio.

El estado de situación financiera es acumulado hasta la fecha de corte.
El estado de resultados cubre el periodo elegido.
Las categorías siguen la NIIF 18: operación, inversión, financiación,
impuesto a las ganancias y operaciones discontinuadas.
"""

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


def _filas(empresa, *, hasta: date, desde: date | None = None):
    filtro = {
        "asiento__empresa": empresa,
        "asiento__estado": "CONFIRMADO",
    }
    if desde is None:
        filtro["asiento__fecha__lte"] = hasta
    else:
        filtro["asiento__fecha__range"] = (desde, hasta)

    return (
        AsientoLinea.objects.filter(**filtro)
        .values(
            "cuenta__codigo",
            "cuenta__nombre",
            "cuenta__elemento",
            "cuenta__categoria_financiera",
        )
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )


def _entrada(fila) -> dict:
    return {
        "codigo": fila["cuenta__codigo"],
        "nombre": fila["cuenta__nombre"],
        "importe": abs((fila["debe"] or CERO) - (fila["haber"] or CERO)),
    }


def _suma(items) -> Decimal:
    return sum((i["importe"] for i in items), CERO)


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

    activo_corriente: list[dict] = []
    activo_no_corriente: list[dict] = []
    pasivo: list[dict] = []
    patrimonio: list[dict] = []

    ingresos_ventas = CERO
    costo_ventas = CERO
    gastos_operativos = CERO
    otros_ingresos = CERO
    gastos_financieros = CERO
    ingresos_financieros = CERO
    gasto_impuesto = CERO
    resultado_acumulado = CERO

    if empresa:
        # --- Situación financiera: acumulado hasta la fecha de corte ---
        for fila in _filas(empresa, hasta=hasta):
            elemento = fila["cuenta__elemento"]
            neto = (fila["debe"] or CERO) - (fila["haber"] or CERO)
            if elemento in ACTIVO_CORRIENTE and neto != 0:
                activo_corriente.append(_entrada(fila))
            elif elemento in ACTIVO_NO_CORRIENTE and neto != 0:
                activo_no_corriente.append(_entrada(fila))
            elif elemento == 4 and neto != 0:
                pasivo.append(_entrada(fila))
            elif elemento == 5 and neto != 0:
                patrimonio.append(_entrada(fila))
            elif elemento in (6, 7, 8):
                resultado_acumulado += -neto

        # --- Resultados: solo el periodo elegido ---
        for fila in _filas(empresa, desde=desde, hasta=hasta):
            codigo = fila["cuenta__codigo"]
            elemento = fila["cuenta__elemento"]
            neto = (fila["debe"] or CERO) - (fila["haber"] or CERO)

            if elemento == 8:
                gasto_impuesto += neto
            elif codigo.startswith("69"):
                costo_ventas += neto
            elif codigo.startswith(("63", "64", "65", "68")):
                gastos_operativos += neto
            elif codigo.startswith(("75", "76")):
                otros_ingresos += -neto
            elif codigo.startswith("67"):
                gastos_financieros += neto
            elif codigo.startswith("77"):
                ingresos_financieros += -neto
            elif codigo.startswith("70"):
                ingresos_ventas += -neto

    resultado_operacion = (
        ingresos_ventas + otros_ingresos - costo_ventas - gastos_operativos
    )
    resultado_financiacion = ingresos_financieros - gastos_financieros
    resultado_antes_impuesto = resultado_operacion + resultado_financiacion
    resultado_neto = resultado_antes_impuesto - gasto_impuesto

    total_activo_corriente = _suma(activo_corriente)
    total_activo_no_corriente = _suma(activo_no_corriente)
    total_activo = total_activo_corriente + total_activo_no_corriente
    total_pasivo = _suma(pasivo)
    total_patrimonio = _suma(patrimonio)
    total_patrimonio_resultado = total_patrimonio + resultado_acumulado

    efectivo = sum(
        (
            item["importe"]
            for item in activo_corriente
            if item["codigo"].startswith(("101", "1031", "1061"))
        ),
        CERO,
    )

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
        "resultado_acumulado": resultado_acumulado,
        "ingresos_ventas": ingresos_ventas,
        "costo_ventas": costo_ventas,
        "gastos_operativos": gastos_operativos,
        "otros_ingresos": otros_ingresos,
        "resultado_operacion": resultado_operacion,
        "gastos_financieros": gastos_financieros,
        "ingresos_financieros": ingresos_financieros,
        "resultado_financiacion": resultado_financiacion,
        "resultado_antes_impuesto": resultado_antes_impuesto,
        "gasto_impuesto": gasto_impuesto,
        "resultado_neto": resultado_neto,
        "descuadre": total_activo - (total_pasivo + total_patrimonio_resultado),
        "efectivo": efectivo,
        "cambios": [
            {"concepto": "Saldo al inicio del ejercicio", "importe": total_patrimonio},
            {"concepto": "Aportes de capital del periodo", "importe": CERO},
            {"concepto": "Resultado acumulado", "importe": resultado_acumulado},
            {"concepto": "Saldo al cierre", "importe": total_patrimonio_resultado},
        ],
    }
    return render(request, "reportes/eeff.html", contexto)

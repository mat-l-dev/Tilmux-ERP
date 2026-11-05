"""Estados financieros: situación financiera, resultados y cambios en el patrimonio.

El estado de situación financiera es acumulado hasta la fecha de corte.
El estado de resultados cubre el periodo elegido.
Las categorías siguen la NIIF 18: operación, inversión, financiación,
impuesto a las ganancias y operaciones discontinuadas.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
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


def _saldo(empresa, prefijos: tuple[str, ...], hasta: date) -> Decimal:
    """Saldo neto de las cuentas que empiezan con esos códigos."""
    filtro = Q()
    for prefijo in prefijos:
        filtro |= Q(cuenta__codigo__startswith=prefijo)

    filas = AsientoLinea.objects.filter(
        filtro,
        asiento__empresa=empresa,
        asiento__estado="CONFIRMADO",
        asiento__fecha__lte=hasta,
    ).aggregate(debe=Sum("debe"), haber=Sum("haber"))

    return (filas["debe"] or CERO) - (filas["haber"] or CERO)


def construir(empresa, desde: date, hasta: date) -> dict:

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

    # --- Flujo de efectivo, método indirecto ---
    EFECTIVO = ("101", "1031", "1061")
    INVENTARIO = ("201", "202", "203", "204", "205", "206", "207")
    POR_COBRAR = ("121", "122", "13", "14")
    POR_PAGAR = ("40", "41", "42", "43", "44", "45", "46", "47")

    inicio = desde - timedelta(days=1)
    efectivo_inicial = _saldo(empresa, EFECTIVO, inicio) if empresa else CERO
    efectivo_final = _saldo(empresa, EFECTIVO, hasta) if empresa else CERO
    variacion_inventario = (
        _saldo(empresa, INVENTARIO, hasta) - _saldo(empresa, INVENTARIO, inicio)
        if empresa
        else CERO
    )
    variacion_cobrar = (
        _saldo(empresa, POR_COBRAR, hasta) - _saldo(empresa, POR_COBRAR, inicio)
        if empresa
        else CERO
    )
    variacion_pagar = (
        -(_saldo(empresa, POR_PAGAR, hasta) - _saldo(empresa, POR_PAGAR, inicio))
        if empresa
        else CERO
    )
    aportes = CERO
    if empresa:
        for fila in _filas(empresa, desde=desde, hasta=hasta):
            if fila["cuenta__elemento"] == 5:
                aportes += (fila["haber"] or CERO) - (fila["debe"] or CERO)

    flujo_operacion = resultado_neto - variacion_inventario - variacion_cobrar + variacion_pagar
    flujo_financiacion = aportes
    flujo_neto = flujo_operacion + flujo_financiacion

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
        "flujo": [
            {"concepto": "Resultado del periodo", "importe": resultado_neto},
            {"concepto": "Variación de inventarios", "importe": -variacion_inventario},
            {"concepto": "Variación de cuentas por cobrar", "importe": -variacion_cobrar},
            {"concepto": "Variación de cuentas por pagar", "importe": variacion_pagar},
            {"concepto": "Flujo de operación", "importe": flujo_operacion, "subtotal": True},
            {"concepto": "Aportes de capital", "importe": aportes},
            {"concepto": "Flujo de financiación", "importe": flujo_financiacion, "subtotal": True},
            {"concepto": "Flujo neto del periodo", "importe": flujo_neto, "subtotal": True},
            {"concepto": "Efectivo al inicio", "importe": efectivo_inicial},
            {"concepto": "Efectivo al cierre", "importe": efectivo_final, "total": True},
        ],
        "flujo_cuadra": efectivo_inicial + flujo_neto - efectivo_final,
    }
    return contexto


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

    contexto = construir(empresa, desde, hasta)
    return render(request, "reportes/eeff.html", contexto)

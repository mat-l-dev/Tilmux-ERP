"""Estados financieros: situación financiera, resultados y cambios en el patrimonio.

El estado de situación financiera es acumulado hasta la fecha de corte.
El estado de resultados cubre el periodo elegido.
Se preparan conforme a la NPIF (Res. CNC 001-2024-EF/30), con las categorías
de operación, financiación e impuesto a las ganancias.
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


def _filas(empresa, *, hasta: date, desde: date | None = None, excluir_cierre: bool = False):
    filtro = {
        "asiento__empresa": empresa,
        "asiento__estado": "CONFIRMADO",
    }
    if desde is None:
        filtro["asiento__fecha__lte"] = hasta
    else:
        filtro["asiento__fecha__range"] = (desde, hasta)

    consulta = AsientoLinea.objects.filter(**filtro)
    if excluir_cierre:
        consulta = consulta.exclude(asiento__origen_tipo="CIERRE")

    return (
        consulta.values(
            "cuenta__codigo",
            "cuenta__nombre",
            "cuenta__elemento",
            "cuenta__categoria_financiera",
        )
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )


def _entrada(fila, *, acreedora: bool = False) -> dict:
    neto = (fila["debe"] or CERO) - (fila["haber"] or CERO)
    return {
        "codigo": fila["cuenta__codigo"],
        "nombre": fila["cuenta__nombre"],
        "importe": -neto if acreedora else neto,
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
            elif elemento == 4 and neto > 0:
                if fila["cuenta__codigo"].startswith("40"):
                    # Saldo deudor de un tributo: crédito fiscal por recuperar.
                    activo_corriente.append(_entrada(fila))
                else:
                    # Un saldo deudor en una cuenta por pagar (por ejemplo 4212)
                    # reduce el pasivo; no es un activo.
                    pasivo.append(_entrada(fila, acreedora=True))
            elif elemento == 4 and neto < 0:
                pasivo.append(_entrada(fila, acreedora=True))
            elif elemento == 5 and neto != 0:
                patrimonio.append(_entrada(fila, acreedora=True))
            elif elemento in (6, 7, 8):
                resultado_acumulado += -neto

        # --- Resultados: solo el periodo elegido, sin el asiento de cierre ---
        for fila in _filas(empresa, desde=desde, hasta=hasta, excluir_cierre=True):
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
    patrimonio_inicial = CERO
    if empresa:
        patrimonio_inicial = -_saldo(empresa, ("5",), desde - timedelta(days=1))
        for fila in _filas(
            empresa, desde=desde, hasta=hasta, excluir_cierre=True
        ):
            if fila["cuenta__elemento"] == 5:
                aportes += (fila["haber"] or CERO) - (fila["debe"] or CERO)

    flujo_operacion = resultado_neto - variacion_inventario - variacion_cobrar + variacion_pagar
    flujo_financiacion = aportes
    flujo_neto = flujo_operacion + flujo_financiacion

    efectivo_cuentas = [
        item
        for item in activo_corriente
        if item["codigo"].startswith(("101", "1031", "1061"))
    ]
    tributos = [item for item in pasivo if item["codigo"].startswith("40")]
    relacionadas = [item for item in pasivo if item["codigo"].startswith("44")]

    inventario_detalle = []
    if empresa:
        from inventario.models import CapaFIFO

        resumen = {}
        for capa in CapaFIFO.objects.filter(
            empresa=empresa, cantidad_restante__gt=0
        ).select_related("producto"):
            fila = resumen.setdefault(
                capa.producto_id, {"producto": capa.producto, "cantidad": CERO, "valor": CERO}
            )
            fila["cantidad"] += capa.cantidad_restante
            fila["valor"] += capa.cantidad_restante * capa.costo_unitario
        inventario_detalle = sorted(
            resumen.values(), key=lambda f: f["valor"], reverse=True
        )[:5]

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
        "total_patrimonio_resultado": total_patrimonio_resultado,
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
        "patrimonio_inicial": patrimonio_inicial,
        "aportes": aportes,
        "descuadre": total_activo - (total_pasivo + total_patrimonio_resultado),
        "efectivo": efectivo,
        "cambios": [
            {"concepto": "Saldo al inicio del ejercicio", "importe": patrimonio_inicial},
            {"concepto": "Aportes y retiros de capital", "importe": aportes},
            {"concepto": "Resultado del periodo", "importe": resultado_neto},
            {
                "concepto": "Saldo al cierre",
                "importe": patrimonio_inicial + aportes + resultado_neto,
            },
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
        "efectivo_cuentas": efectivo_cuentas,
        "tributos": tributos,
        "relacionadas": relacionadas,
        "inventario_detalle": inventario_detalle,
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

    def menos_un_anio(fecha: date) -> date:
        try:
            return fecha.replace(year=fecha.year - 1)
        except ValueError:
            return fecha.replace(year=fecha.year - 1, day=28)

    anterior = construir(empresa, menos_un_anio(desde), menos_un_anio(hasta))
    contexto["anterior"] = anterior
    contexto["anio_anterior"] = hasta.year - 1

    def variacion(actual, previo):
        if not previo:
            return None
        return ((Decimal(actual) - Decimal(previo)) / Decimal(previo) * 100).quantize(
            Decimal("0.1")
        )

    pares = [
        ("Ingresos por ventas", "ingresos_ventas"),
        ("Resultado del periodo", "resultado_neto"),
        ("Total activo", "total_activo"),
        ("Total pasivo", "total_pasivo"),
        ("Total patrimonio", "total_patrimonio_resultado"),
    ]
    contexto["comparativo"] = [
        {
            "concepto": etiqueta,
            "actual": contexto[clave],
            "anterior": anterior[clave],
            "variacion": variacion(contexto[clave], anterior[clave]),
        }
        for etiqueta, clave in pares
    ]
    return render(request, "reportes/eeff.html", contexto)

"""Vistas del núcleo."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from compras.models import Compra
from contabilidad.cierre import cerrar, revertir
from contabilidad.cierre import estado as estado_cierre
from contabilidad.impuestos import (
    asiento_renta,
    saldo_cuenta,
    saldo_renta,
)
from contabilidad.models import Asiento, AsientoLinea, Cuenta
from contabilidad.servicios import ContabilidadError
from ventas.models import Venta

from .context import empresa_actual
from .models import Empresa, HistorialDocumento, Periodo
from .periodos import cerrar_mes, reabrir_mes
from .permisos import requiere_escritura
from .resumen_ventas import ventas_netas_por_mes

MESES_CORTOS = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic")


def _meses_atras(anio: int, mes: int, pasos: int) -> tuple[int, int]:
    total = anio * 12 + (mes - 1) - pasos
    return total // 12, total % 12 + 1


def soles(valor) -> str:
    numero = Decimal(valor or 0).quantize(Decimal("0.01"))
    texto = f"{numero:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _pendientes(empresa) -> list[dict]:
    """Comprobantes que necesitan datos o confirmación."""
    if empresa is None:
        return []

    items = []
    compras = (
        Compra.objects.filter(empresa=empresa)
        .exclude(estado=Compra.Estado.ANULADA)
        .select_related("proveedor")
        .prefetch_related("lineas")
    )
    for compra in compras:
        faltantes = []
        if compra.estado == Compra.Estado.PENDIENTE:
            faltantes.append("factura pendiente")
        if compra.estado == Compra.Estado.BORRADOR:
            faltantes.append("borrador sin confirmar")
        if not compra.serie.strip():
            faltantes.append("serie")
        if not compra.numero.strip():
            faltantes.append("número")
        if len(compra.proveedor.numero_doc) != 11:
            faltantes.append("RUC")
        if not compra.lineas.exists():
            faltantes.append("líneas")
        if faltantes:
            if compra.estado == Compra.Estado.CONFIRMADA:
                url = reverse("compras:corregir", args=[compra.pk])
            else:
                url = f"{reverse('compras:nueva')}?editar={compra.pk}"
            items.append(
                {
                    "tipo": "Compra",
                    "documento": compra,
                    "etiqueta": (
                        f"{compra.serie}-{compra.numero}".strip(" -")
                        or f"Compra #{compra.pk}"
                    ),
                    "tercero": compra.proveedor.nombre,
                    "faltantes": ", ".join(faltantes),
                    "url": url,
                }
            )

    for venta in Venta.objects.filter(
        empresa=empresa, estado=Venta.Estado.BORRADOR
    ).select_related("cliente"):
        items.append(
            {
                "tipo": "Venta",
                "documento": venta,
                "etiqueta": f"{venta.serie}-{venta.numero}".strip(" -")
                or f"Venta #{venta.pk}",
                "tercero": venta.cliente_nombre
                or (venta.cliente.nombre if venta.cliente else "Consumidor final"),
                "faltantes": "borrador sin confirmar",
                "url": f"{reverse('ventas:nueva')}?editar={venta.pk}",
            }
        )
    return items


@login_required
def panel(request: HttpRequest) -> HttpResponse:
    empresa = empresa_actual(request)
    hoy = date.today()

    anio, mes = hoy.year, hoy.month
    periodo_pedido = request.GET.get("periodo", "")
    if periodo_pedido:
        partes = periodo_pedido.split("-")
        if (len(partes) == 2 and len(partes[0]) == 4 and len(partes[1]) == 2
                and partes[0].isascii() and partes[0].isdigit()
                and partes[1].isascii() and partes[1].isdigit()
                and 2000 <= int(partes[0]) <= 9998 and 1 <= int(partes[1]) <= 12):
            anio, mes = int(partes[0]), int(partes[1])
        else:
            periodo_pedido = ""
            messages.warning(request, "El período indicado no es válido; se muestra el último período con actividad.")

    # Si el mes actual no tiene movimiento, abrir el último mes con actividad.
    if empresa and not periodo_pedido:
        hay_movimiento = Asiento.objects.filter(
            empresa=empresa, estado=Asiento.Estado.CONFIRMADO, fecha__year=anio, fecha__month=mes
        ).exists()
        if not hay_movimiento:
            ultimo = (
                Asiento.objects.filter(empresa=empresa, estado=Asiento.Estado.CONFIRMADO)
                .order_by("-fecha")
                .values_list("fecha", flat=True)
                .first()
            )
            if ultimo:
                anio, mes = ultimo.year, ultimo.month

    saldo = Decimal("0")
    ventas_base = Decimal("0")
    igv = Decimal("0")
    renta = Decimal("0")
    ir_por_pagar = Decimal("0")
    asiento = None
    renta_asentada = False
    renta_pendiente = False
    fin_mes = date(anio, mes, calendar.monthrange(anio, mes)[1])

    if empresa:
        saldos = AsientoLinea.objects.filter(
            asiento__empresa=empresa,
            asiento__estado="CONFIRMADO",
            asiento__fecha__lte=fin_mes,
            cuenta__codigo__in=["101", "1031", "1061"],
        ).aggregate(d=Sum("debe"), h=Sum("haber"))
        saldo = Decimal(saldos["d"] or 0) - Decimal(saldos["h"] or 0)

        from reportes.casillas import calcular

        datos_mes = calcular(empresa, anio, mes)
        ventas_base = datos_mes["base_renta"]
        renta = datos_mes["renta"]

        igv = saldo_cuenta(empresa, "40111", fin_mes)
        ir_por_pagar = saldo_renta(empresa, fin_mes)
        asiento = asiento_renta(empresa, anio, mes)
        renta_asentada = asiento is not None
        renta_pendiente = renta > 0 and not renta_asentada

    ventas_acumulado = Decimal("0")
    ventas_anterior = Decimal("0")
    variacion = None
    acumulado = {}
    if empresa:
        acumulado = ventas_netas_por_mes(empresa, date(anio - 1, mes, 1), fin_mes)
        ventas_acumulado = sum((acumulado.get((anio, indice), 0) for indice in range(1, mes + 1)), Decimal("0"))
        ventas_anterior = acumulado.get((anio - 1, mes), Decimal("0"))
        if ventas_anterior > 0:
            variacion = (
                (Decimal(ventas_base) - Decimal(ventas_anterior))
                / Decimal(ventas_anterior)
                * 100
            ).quantize(Decimal("0.1"))

    serie_meses = []
    maximo = Decimal("0")
    if empresa:
        for paso in range(11, -1, -1):
            anio_punto, mes_punto = _meses_atras(anio, mes, paso)
            valor = Decimal(acumulado.get((anio_punto, mes_punto), 0))
            maximo = max(maximo, valor)
            serie_meses.append(
                {
                    "etiqueta": f"{MESES_CORTOS[mes_punto - 1]} {anio_punto % 100:02d}",
                    "valor": valor,
                    "actual": paso == 0,
                }
            )
    for punto in serie_meses:
        punto["altura"] = max(0, int(punto["valor"] * 100 / maximo)) if maximo > 0 else 0
        punto["texto"] = soles(punto["valor"])

    contexto = {
        "hoy": hoy,
        "anio": anio,
        "mes": mes,
        "periodo_valor": f"{anio}-{mes:02d}",
        "periodo_etiqueta": f"{MESES_CORTOS[mes - 1]} {anio}",
        "cuentas_activas": Cuenta.objects.filter(activa=True).count(),
        "periodos_abiertos": (
            Periodo.objects.filter(empresa=empresa, estado=Periodo.Estado.ABIERTO).count()
            if empresa
            else 0
        ),
        "saldo_tesoreria": soles(saldo),
        "ventas_mes": soles(ventas_base),
        "igv_por_pagar": soles(abs(igv)),
        "igv_etiqueta": "IGV a favor" if igv < 0 else "IGV por pagar",
        "igv_nota": "Saldo a favor" if igv < 0 else "Después del crédito de compras",
        "renta_mes": soles(renta),
        "ir_por_pagar": soles(ir_por_pagar),
        "renta_asentada": renta_asentada,
        "renta_pendiente": renta_pendiente,
        "renta_asiento": asiento,
        "periodo_actual": (
            Periodo.objects.filter(empresa=empresa, anio=anio, mes=mes).first()
            if empresa
            else None
        ),
        "serie_meses": serie_meses,
        "maximo_mes": soles(maximo),
        "ventas_acumulado": soles(ventas_acumulado),
        "ventas_anterior": soles(ventas_anterior),
        "variacion": variacion,
        "anio_anterior": anio - 1,
        "pendientes_count": len(_pendientes(empresa)),
    }
    return render(request, "core/panel.html", contexto)


@login_required
def pendientes(request: HttpRequest) -> HttpResponse:
    empresa = empresa_actual(request)
    return render(
        request, "core/pendientes.html", {"items": _pendientes(empresa)}
    )


@login_required
@require_POST
def cambiar_empresa(request: HttpRequest) -> HttpResponse:
    empresa_id = request.POST.get("empresa_id")
    if Empresa.objects.filter(pk=empresa_id, activa=True).exists():
        request.session["empresa_id"] = int(empresa_id)
    return redirect(request.POST.get("siguiente") or "core:panel")


@login_required
def periodos(request: HttpRequest) -> HttpResponse:
    empresa = empresa_actual(request)
    lista = list(
        Periodo.objects.filter(empresa=empresa).order_by("-anio", "-mes")
        if empresa
        else Periodo.objects.none()
    )
    historiales = {}
    for registro in HistorialDocumento.objects.filter(
        empresa=empresa, tipo=HistorialDocumento.Tipo.PERIODO, documento_id__in=[p.pk for p in lista],
    ).select_related("usuario").order_by("-fecha", "-pk"):
        items = historiales.setdefault(registro.documento_id, [])
        if len(items) < 5:
            items.append(registro)
    for periodo in lista:
        periodo.historial_reciente = historiales.get(periodo.pk, [])
        periodo.n_asientos = Asiento.objects.filter(
            empresa=empresa, fecha__year=periodo.anio, fecha__month=periodo.mes
        ).count()
        periodo.ventas = (
            Venta.objects.filter(
                empresa=empresa,
                estado=Venta.Estado.CONFIRMADA,
                fecha__year=periodo.anio,
                fecha__month=periodo.mes,
            ).aggregate(s=Sum("total"))["s"]
            or 0
        )
        periodo.compras = (
            Compra.objects.filter(
                empresa=empresa,
                estado=Compra.Estado.CONFIRMADA,
                fecha__year=periodo.anio,
                fecha__month=periodo.mes,
            ).aggregate(s=Sum("total"))["s"]
            or 0
        )

    anios = []
    if empresa:
        for anio in sorted({p.anio for p in lista}, reverse=True):
            anios.append(estado_cierre(empresa, anio))

    return render(
        request, "core/periodos.html", {"periodos": lista, "anios": anios}
    )


@login_required
@requiere_escritura
@require_POST
def cerrar_periodo(request: HttpRequest, pk: int) -> HttpResponse:
    empresa = empresa_actual(request)
    get_object_or_404(Periodo, pk=pk, empresa=empresa)
    try:
        periodo = cerrar_mes(empresa=empresa, pk=pk, usuario=request.user)
    except ContabilidadError as exc:
        messages.error(request, f"No se pudo cerrar: {exc}")
    else:
        messages.success(request, f"Periodo {periodo.etiqueta} cerrado.")
    return redirect("core:periodos")


@login_required
@requiere_escritura
@require_POST
def revaluar_periodo(request: HttpRequest, pk: int) -> HttpResponse:
    from compras.servicios import CompraError, revaluar

    periodo = get_object_or_404(Periodo, pk=pk, empresa=empresa_actual(request))
    if periodo.estado != Periodo.Estado.ABIERTO:
        messages.error(request, "No se puede revaluar un período cerrado.")
        return redirect("core:periodos")
    try:
        ajustadas, total = revaluar(periodo.empresa, periodo.anio, periodo.mes)
    except (CompraError, ContabilidadError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"{ajustadas} compra(s) revaluada(s). Ajuste total: S/ {total}.",
        )
    return redirect("core:periodos")


@login_required
@require_POST
def reabrir_periodo(request: HttpRequest, pk: int) -> HttpResponse:
    if not request.user.is_superuser:
        messages.error(request, "Solo el administrador puede reabrir un periodo.")
        return redirect("core:periodos")

    empresa = empresa_actual(request)
    get_object_or_404(Periodo, pk=pk, empresa=empresa)
    try:
        periodo = reabrir_mes(empresa=empresa, pk=pk, usuario=request.user, motivo=request.POST.get("motivo", ""))
    except ContabilidadError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Periodo {periodo.etiqueta} reabierto.")
    return redirect("core:periodos")


@login_required
@requiere_escritura
@require_POST
def cerrar_ejercicio(request: HttpRequest, anio: int) -> HttpResponse:
    empresa = empresa_actual(request)
    try:
        asientos = cerrar(empresa, anio, usuario=request.user)
    except ContabilidadError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Ejercicio {anio} cerrado con {len(asientos)} asiento(s) de cierre.",
        )
    return redirect("core:periodos")


@login_required
@require_POST
def revertir_ejercicio(request: HttpRequest, anio: int) -> HttpResponse:
    if not request.user.is_superuser:
        messages.error(
            request, "Solo el administrador puede revertir el cierre anual."
        )
        return redirect("core:periodos")

    empresa = empresa_actual(request)
    try:
        total = revertir(empresa, anio)
    except ContabilidadError as exc:
        messages.error(request, str(exc))
    else:
        messages.warning(
            request,
            f"Cierre {anio} anulado: {total} asiento(s). Reabre diciembre si "
            "necesitas ajustar y vuelve a cerrar.",
        )
    return redirect("core:periodos")


@login_required
def proximamente(request: HttpRequest) -> HttpResponse:
    messages.info(request, "Este módulo se construye en la siguiente sesión.")
    return redirect("core:panel")

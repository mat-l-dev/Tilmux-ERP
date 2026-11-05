"""Reportes contables y tributarios."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.models import Cuenta
from core.context import empresa_actual
from ventas.models import Venta

TASA_RENTA_RER = Decimal("0.015")


def _rango(request) -> tuple[date, date]:
    hoy = date.today()
    desde = request.GET.get("desde") or date(hoy.year, 1, 1).isoformat()
    hasta = request.GET.get("hasta") or hoy.isoformat()
    return date.fromisoformat(desde), date.fromisoformat(hasta)


@login_required
def balance(request):
    empresa = empresa_actual(request)
    desde, hasta = _rango(request)
    filas = []

    if empresa:
        filas = list(
            Cuenta.objects.filter(
                lineas_asiento__asiento__empresa=empresa,
                lineas_asiento__asiento__estado="CONFIRMADO",
                lineas_asiento__asiento__fecha__range=(desde, hasta),
            )
            .annotate(
                total_debe=Sum("lineas_asiento__debe"),
                total_haber=Sum("lineas_asiento__haber"),
            )
            .order_by("codigo")
        )

    for fila in filas:
        debe = fila.total_debe or Decimal("0")
        haber = fila.total_haber or Decimal("0")
        neto = debe - haber
        fila.saldo_deudor = neto if neto > 0 else Decimal("0")
        fila.saldo_acreedor = -neto if neto < 0 else Decimal("0")

    contexto = {
        "filas": filas,
        "desde": desde,
        "hasta": hasta,
        "total_debe": sum((f.total_debe or 0) for f in filas),
        "total_haber": sum((f.total_haber or 0) for f in filas),
    }
    return render(request, "reportes/balance.html", contexto)


@login_required
def mayor(request):
    empresa = empresa_actual(request)
    desde, hasta = _rango(request)
    codigo = request.GET.get("cuenta", "")
    cuenta = None
    movimientos = []
    saldo = Decimal("0")

    if empresa and codigo:
        cuenta = Cuenta.objects.filter(version="2026", codigo=codigo).first()
        if cuenta:
            lineas = (
                cuenta.lineas_asiento.filter(
                    asiento__empresa=empresa,
                    asiento__estado="CONFIRMADO",
                    asiento__fecha__range=(desde, hasta),
                )
                .select_related("asiento")
                .order_by("asiento__fecha", "asiento__numero", "orden")
            )
            for linea in lineas:
                saldo += linea.debe - linea.haber
                movimientos.append({"linea": linea, "saldo": saldo})

    contexto = {
        "desde": desde,
        "hasta": hasta,
        "codigo": codigo,
        "cuenta": cuenta,
        "movimientos": movimientos,
        "saldo": saldo,
    }
    return render(request, "reportes/mayor.html", contexto)


@login_required
def registro_ventas(request):
    empresa = empresa_actual(request)
    desde, hasta = _rango(request)
    ventas = []
    if empresa:
        ventas = Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).order_by("fecha", "serie", "numero")

    base = ventas.aggregate(s=Sum("subtotal"))["s"] if ventas else 0
    igv = ventas.aggregate(s=Sum("igv"))["s"] if ventas else 0
    contexto = {
        "ventas": ventas,
        "desde": desde,
        "hasta": hasta,
        "base": base or 0,
        "igv": igv or 0,
        "total": (base or 0) + (igv or 0),
    }
    return render(request, "reportes/registro_ventas.html", contexto)


@login_required
def registro_compras(request):
    empresa = empresa_actual(request)
    desde, hasta = _rango(request)
    filas = []

    if empresa:
        for compra in Compra.objects.filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).select_related("proveedor"):
            filas.append(
                {
                    "fecha": compra.fecha,
                    "tipo": compra.get_tipo_doc_display(),
                    "documento": f"{compra.serie}-{compra.numero}".strip(" -"),
                    "ruc": compra.proveedor.numero_doc,
                    "proveedor": compra.proveedor.nombre,
                    "base": compra.subtotal,
                    "igv": compra.igv,
                    "total": compra.total,
                    "clase": "Mercadería",
                }
            )
        for gasto in Gasto.objects.filter(
            empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("proveedor"):
            filas.append(
                {
                    "fecha": gasto.fecha,
                    "tipo": gasto.get_tipo_doc_display(),
                    "documento": f"{gasto.serie}-{gasto.numero}".strip(" -"),
                    "ruc": gasto.proveedor.numero_doc,
                    "proveedor": gasto.proveedor.nombre,
                    "base": gasto.base if gasto.igv > 0 else 0,
                    "no_gravado": gasto.base if gasto.igv == 0 else 0,
                    "igv": gasto.igv,
                    "total": gasto.total,
                    "clase": "Gasto",
                }
            )

    filas.sort(key=lambda f: (f["fecha"], f["documento"]))

    contexto = {
        "filas": filas,
        "desde": desde,
        "hasta": hasta,
        "base": sum((f.get("base") or 0) for f in filas),
        "no_gravado": sum((f.get("no_gravado") or 0) for f in filas),
        "igv": sum((f["igv"] or 0) for f in filas),
        "total": sum((f["total"] or 0) for f in filas),
    }
    return render(request, "reportes/registro_compras.html", contexto)


@login_required
def impuestos(request):
    empresa = empresa_actual(request)
    desde, hasta = _rango(request)
    ventas_base = ventas_igv = compras_base = compras_igv = Decimal("0")

    if empresa:
        ventas = Venta.objects.filter(
            empresa=empresa, estado=Venta.Estado.CONFIRMADA, fecha__range=(desde, hasta)
        )
        ventas_base = ventas.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")
        ventas_igv = ventas.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        compras = Compra.objects.filter(
            empresa=empresa, estado=Compra.Estado.CONFIRMADA, fecha__range=(desde, hasta)
        )
        compras_base = compras.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")
        compras_igv = compras.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        # Solo los gastos con comprobante que otorga crédito fiscal (facturas).
        gastos = Gasto.objects.filter(
            empresa=empresa, fecha__range=(desde, hasta), con_credito=True
        )
        compras_base += gastos.aggregate(s=Sum("base"))["s"] or Decimal("0")
        compras_igv += gastos.aggregate(s=Sum("igv"))["s"] or Decimal("0")

    igv = ventas_igv - compras_igv
    renta = (ventas_base * TASA_RENTA_RER).quantize(Decimal("0.01"))

    contexto = {
        "desde": desde,
        "hasta": hasta,
        "ventas_base": ventas_base,
        "ventas_igv": ventas_igv,
        "compras_base": compras_base,
        "compras_igv": compras_igv,
        "igv": igv,
        "renta": renta,
    }
    return render(request, "reportes/impuestos.html", contexto)

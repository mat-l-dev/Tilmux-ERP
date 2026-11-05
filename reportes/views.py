"""Reportes contables y tributarios."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render

from catalogo.models import Producto
from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.models import Cuenta
from core.context import empresa_actual
from inventario.models import CapaFIFO, MovimientoStock
from ventas.models import NotaCredito, NotaDebito, Venta

from .casillas import calcular
from .utils import rango

TASA_RENTA_RER = Decimal("0.015")
CERO = Decimal("0")




@login_required
def balance(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
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

    total_debe = sum((f.total_debe or 0) for f in filas)
    total_haber = sum((f.total_haber or 0) for f in filas)
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))
    contexto = {
        "filas": pagina,
        "page_obj": pagina,
        "desde": desde,
        "hasta": hasta,
        "total_debe": total_debe,
        "total_haber": total_haber,
    }
    return render(request, "reportes/balance.html", contexto)


@login_required
def mayor(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
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

    pagina = Paginator(movimientos, 50).get_page(request.GET.get("page"))
    contexto = {
        "desde": desde,
        "hasta": hasta,
        "codigo": codigo,
        "cuenta": cuenta,
        "movimientos": pagina,
        "page_obj": pagina,
        "saldo": saldo,
    }
    return render(request, "reportes/mayor.html", contexto)


@login_required
def registro_ventas(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[dict] = []

    if empresa:
        for venta in Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).order_by("fecha", "serie", "numero"):
            filas.append(
                {
                    "fecha": venta.fecha,
                    "tipo": venta.get_tipo_doc_display(),
                    "documento": f"{venta.serie}-{venta.numero}",
                    "referencia": "",
                    "cliente": venta.cliente_nombre or "Consumidor final",
                    "base": venta.subtotal,
                    "igv": venta.igv,
                    "total": venta.total,
                }
            )

        for nota in NotaCredito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta"):
            filas.append(
                {
                    "fecha": nota.fecha,
                    "tipo": "Nota de crédito (07)",
                    "documento": f"{nota.serie}-{nota.numero}",
                    "referencia": f"{nota.venta.serie}-{nota.venta.numero}",
                    "cliente": nota.venta.cliente_nombre or "Consumidor final",
                    "base": -nota.base,
                    "igv": -nota.igv,
                    "total": -nota.total,
                }
            )

        for nota in NotaDebito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta"):
            filas.append(
                {
                    "fecha": nota.fecha,
                    "tipo": "Nota de débito (08)",
                    "documento": f"{nota.serie}-{nota.numero}",
                    "referencia": f"{nota.venta.serie}-{nota.venta.numero}",
                    "cliente": nota.venta.cliente_nombre or "Consumidor final",
                    "base": nota.base,
                    "igv": nota.igv,
                    "total": nota.total,
                }
            )

    filas.sort(key=lambda f: (f["fecha"], f["documento"]))

    base = sum((f["base"] for f in filas), Decimal("0"))
    igv = sum((f["igv"] for f in filas), Decimal("0"))
    total = sum((f["total"] for f in filas), Decimal("0"))
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))

    contexto = {
        "filas": pagina,
        "page_obj": pagina,
        "desde": desde,
        "hasta": hasta,
        "base": base,
        "igv": igv,
        "total": total,
    }
    return render(request, "reportes/registro_ventas.html", contexto)


@login_required
def registro_compras(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
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

    base = sum((f.get("base") or 0) for f in filas)
    no_gravado = sum((f.get("no_gravado") or 0) for f in filas)
    igv = sum((f["igv"] or 0) for f in filas)
    total = sum((f["total"] or 0) for f in filas)
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))

    contexto = {
        "filas": pagina,
        "page_obj": pagina,
        "desde": desde,
        "hasta": hasta,
        "base": base,
        "no_gravado": no_gravado,
        "igv": igv,
        "total": total,
    }
    return render(request, "reportes/registro_compras.html", contexto)


@login_required
def impuestos(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    ventas_base = ventas_igv = compras_base = compras_igv = Decimal("0")

    if empresa:
        ventas = Venta.objects.filter(
            empresa=empresa, estado=Venta.Estado.CONFIRMADA, fecha__range=(desde, hasta)
        )
        ventas_base = ventas.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")
        ventas_igv = ventas.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        # Las notas ajustan el débito fiscal del periodo.
        creditos = NotaCredito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).aggregate(b=Sum("base"), i=Sum("igv"))
        ventas_base -= creditos["b"] or Decimal("0")
        ventas_igv -= creditos["i"] or Decimal("0")

        debitos = NotaDebito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).aggregate(b=Sum("base"), i=Sum("igv"))
        ventas_base += debitos["b"] or Decimal("0")
        ventas_igv += debitos["i"] or Decimal("0")

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


@login_required
def conciliacion(request):
    """Compara las casillas del sistema con las que muestra SUNAT."""
    empresa = empresa_actual(request)
    hoy = date.today()
    anio = int(request.GET.get("anio") or hoy.year)
    mes = int(request.GET.get("mes") or hoy.month)

    datos = calcular(empresa, anio, mes) if empresa else None
    filas = []

    if datos:
        pares = [
            ("100", "Ventas gravadas (base)", datos["ventas_base"]),
            ("101", "IGV de ventas", datos["ventas_igv"]),
            ("107", "Compras gravadas (base)", datos["compras_base"]),
            ("108", "IGV de compras", datos["compras_igv"]),
            ("120", "Compras no gravadas", datos["no_gravado"]),
            ("140", "Saldo a favor / por pagar", datos["resultado"]),
        ]
        for casilla, concepto, sistema in pares:
            texto = request.GET.get(f"c{casilla}")
            sunat = None
            diferencia = None
            if texto:
                try:
                    sunat = Decimal(texto.replace(",", ".")).quantize(Decimal("0.01"))
                    diferencia = (sistema - sunat).quantize(Decimal("0.01"))
                except (InvalidOperation, ValueError):
                    sunat = None
            filas.append(
                {
                    "casilla": casilla,
                    "concepto": concepto,
                    "sistema": sistema,
                    "sunat": sunat,
                    "diferencia": diferencia,
                }
            )

    return render(
        request,
        "reportes/conciliacion.html",
        {"datos": datos, "filas": filas, "anio": anio, "mes": mes},
    )


@login_required
def inventario(request):
    empresa = empresa_actual(request)
    q = request.GET.get("q", "").strip()

    capas = CapaFIFO.objects.filter(
        empresa=empresa, cantidad_restante__gt=0
    ).select_related("producto", "producto__unidad")
    if q:
        capas = capas.filter(
            Q(producto__sku__icontains=q) | Q(producto__nombre__icontains=q)
        )

    resumen = {}
    for capa in capas:
        fila = resumen.setdefault(
            capa.producto_id,
            {
                "producto": capa.producto,
                "cantidad": CERO,
                "valor": CERO,
                "capas": 0,
            },
        )
        fila["cantidad"] += capa.cantidad_restante
        fila["valor"] += capa.cantidad_restante * capa.costo_unitario
        fila["capas"] += 1

    filas = sorted(resumen.values(), key=lambda f: f["producto"].sku)
    for fila in filas:
        fila["costo_promedio"] = (
            fila["valor"] / fila["cantidad"] if fila["cantidad"] else CERO
        )

    return render(
        request,
        "reportes/inventario.html",
        {
            "filas": filas,
            "q": q,
            "total_valor": sum((f["valor"] for f in filas), CERO),
        },
    )


@login_required
def kardex(request, pk: int):
    empresa = empresa_actual(request)
    producto = get_object_or_404(Producto, pk=pk)
    movimientos = MovimientoStock.objects.filter(
        empresa=empresa, producto=producto
    ).order_by("fecha", "id")

    saldo = CERO
    filas = []
    for movimiento in movimientos:
        if movimiento.tipo == MovimientoStock.Tipo.ENTRADA:
            saldo += movimiento.cantidad
        else:
            saldo -= movimiento.cantidad
        filas.append({"movimiento": movimiento, "saldo": saldo})

    capas = producto.capas.filter(empresa=empresa, cantidad_restante__gt=0).order_by("fecha", "id")

    return render(
        request,
        "reportes/kardex.html",
        {"producto": producto, "filas": filas, "saldo": saldo, "capas": capas},
    )

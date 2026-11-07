"""Reportes contables y tributarios."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria, Producto
from compras.comprobantes import evaluar_tributacion
from compras.models import Compra
from compras.models_gasto import Gasto
from contabilidad.impuestos import (
    asentar_renta,
    asiento_renta,
    igv_pendiente,
    monto_igv_pagado,
    monto_renta_asentada,
    saldo_cuenta,
    saldo_renta,
)
from contabilidad.impuestos import (
    pagar_igv as registrar_pago_igv,
)
from contabilidad.impuestos import (
    pagar_renta as registrar_pago_renta,
)
from contabilidad.models import Cuenta
from contabilidad.servicios import ContabilidadError
from core.context import empresa_actual
from core.models import Periodo
from core.permisos import requiere_escritura
from inventario.models import CapaFIFO, MovimientoStock
from ventas.models import NotaCredito, NotaDebito, Venta

from .casillas import calcular
from .sire import ArchivoInvalido, leer_filas, sumar, validar_contexto
from .utils import rango

CERO = Decimal("0")


def _entero(valor, defecto: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def _es_mes(desde: date, hasta: date) -> bool:
    return (
        desde.year == hasta.year
        and desde.month == hasta.month
        and desde.day == 1
        and hasta.day == calendar.monthrange(hasta.year, hasta.month)[1]
    )


def _meses_del_rango(desde: date, hasta: date):
    anio, mes = desde.year, desde.month
    while (anio, mes) <= (hasta.year, hasta.month):
        yield anio, mes
        mes += 1
        if mes > 12:
            mes = 1
            anio += 1


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
        for compra in Compra.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha_tributaria__range=(desde, hasta),
        ).select_related("proveedor").prefetch_related("lineas"):
            estado_tributario = evaluar_tributacion(compra)
            usa_credito = estado_tributario.incluido
            pendiente = estado_tributario.requiere_revision
            detalle = compra.glosa or " · ".join(
                linea.descripcion
                for linea in compra.lineas.all()[:2]
                if linea.descripcion
            )
            filas.append(
                {
                    "fecha": compra.fecha,
                    "fecha_anotacion": compra.fecha_anotacion,
                    "tipo": compra.get_tipo_doc_display(),
                    "documento": f"{compra.serie}-{compra.numero}".strip(" -"),
                    "ruc": compra.proveedor.numero_doc,
                    "proveedor": compra.proveedor.nombre,
                    "detalle": detalle,
                    "base": compra.subtotal if usa_credito and compra.igv > 0 else 0,
                    "no_gravado": compra.subtotal if usa_credito and compra.igv == 0 else 0,
                    "igv": compra.igv if usa_credito and compra.igv > 0 else 0,
                    "total": compra.total,
                    "credito": usa_credito,
                    "pendiente": pendiente,
                    "clase": "Mercadería",
                }
            )
        for gasto in Gasto.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            fecha_tributaria__range=(desde, hasta),
            provision=False,
        ).exclude(estado=Gasto.Estado.ANULADO).select_related("proveedor"):
            estado_tributario = evaluar_tributacion(gasto)
            usa_credito = estado_tributario.incluido
            filas.append(
                {
                    "fecha": gasto.fecha,
                    "fecha_anotacion": gasto.fecha_anotacion,
                    "tipo": gasto.get_tipo_doc_display(),
                    "documento": f"{gasto.serie}-{gasto.numero}".strip(" -"),
                    "ruc": gasto.proveedor.numero_doc,
                    "proveedor": gasto.proveedor.nombre,
                    "detalle": gasto.glosa,
                    "base": gasto.base if usa_credito and gasto.igv > 0 else 0,
                    "no_gravado": gasto.base
                    if usa_credito and gasto.igv == 0
                    else 0,
                    "igv": gasto.igv if usa_credito and gasto.igv > 0 else 0,
                    "total": gasto.total,
                    "credito": usa_credito,
                    "pendiente": estado_tributario.requiere_revision,
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
    totales = {
        "ventas_base": Decimal("0"),
        "ventas_igv": Decimal("0"),
        "descuentos_base": Decimal("0"),
        "descuentos_igv": Decimal("0"),
        "compras_base": Decimal("0"),
        "compras_igv": Decimal("0"),
        "no_gravado": Decimal("0"),
        "base_renta": Decimal("0"),
        "renta": Decimal("0"),
        "resultado": Decimal("0"),
    }
    if empresa:
        for anio, mes in _meses_del_rango(desde, hasta):
            parte = calcular(empresa, anio, mes)
            for clave in totales:
                totales[clave] += parte[clave]

    ventas_base = totales["ventas_base"]
    ventas_igv = totales["ventas_igv"]
    descuentos_base = totales["descuentos_base"]
    descuentos_igv = totales["descuentos_igv"]
    compras_base = totales["compras_base"]
    compras_igv = totales["compras_igv"]
    no_gravado = totales["no_gravado"]
    base_renta = totales["base_renta"]
    igv = totales["resultado"]
    renta = totales["renta"]

    es_mes = _es_mes(desde, hasta)
    igv_anterior = Decimal("0")
    igv_por_pagar = Decimal("0")
    ir_por_pagar = Decimal("0")
    igv_pagado = Decimal("0")
    igv_por_pagar_mes = Decimal("0")
    periodo_cerrado = False
    asiento = None
    monto_asentado = Decimal("0")
    if empresa:
        igv_anterior = saldo_cuenta(empresa, "40111", desde - timedelta(days=1))
        igv_por_pagar = saldo_cuenta(empresa, "40111", hasta)
        ir_por_pagar = saldo_renta(empresa, hasta)
        if es_mes:
            igv_pagado = monto_igv_pagado(empresa, desde.year, desde.month)
            igv_por_pagar_mes = igv_pendiente(empresa, desde.year, desde.month)
            periodo = Periodo.objects.filter(
                empresa=empresa, anio=desde.year, mes=desde.month
            ).first()
            periodo_cerrado = bool(
                periodo is None or periodo.estado == Periodo.Estado.CERRADO
            )
            asiento = asiento_renta(empresa, desde.year, desde.month)
            monto_asentado = monto_renta_asentada(asiento)
    igv_resultante = igv_anterior + igv
    c145 = max(-igv_anterior, Decimal("0"))
    c184 = igv - c145
    puede_asentar = bool(empresa and es_mes and renta > 0 and asiento is None)
    puede_pagar_igv = bool(
        empresa
        and es_mes
        and c184 > 0
        and igv_por_pagar_mes > 0
    )

    contexto = {
        "desde": desde,
        "hasta": hasta,
        "anio": hasta.year,
        "mes": hasta.month,
        "es_mes": es_mes,
        "ventas_base": ventas_base,
        "ventas_igv": ventas_igv,
        "descuentos_base": descuentos_base,
        "descuentos_igv": descuentos_igv,
        "compras_base": compras_base,
        "compras_igv": compras_igv,
        "no_gravado": no_gravado,
        "igv": igv,
        "igv_anterior": igv_anterior,
        "igv_resultante": igv_resultante,
        "igv_resultante_abs": abs(igv_resultante),
        "igv_por_pagar": igv_por_pagar,
        "igv_por_pagar_abs": abs(igv_por_pagar),
        "igv_pagado": igv_pagado,
        "igv_pendiente": igv_por_pagar_mes,
        "puede_pagar_igv": puede_pagar_igv,
        "igv_periodo_cerrado": periodo_cerrado,
        "c140": igv,
        "c145": c145,
        "c184": c184,
        "c184_abs": abs(c184),
        "c301": base_renta,
        "c312": renta,
        "c303": Decimal("0"),
        "c304": renta,
        "renta": renta,
        "ir_por_pagar": ir_por_pagar,
        "asiento": asiento,
        "monto_asentado": monto_asentado,
        "puede_asentar": puede_asentar,
        "medios": (
            CuentaTesoreria.objects.filter(empresa=empresa, activa=True)
            if empresa
            else []
        ),
        "hoy": date.today(),
    }
    return render(request, "reportes/impuestos.html", contexto)


@login_required
@requiere_escritura
@require_POST
def asentar_renta_mes(request):
    empresa = empresa_actual(request)
    anio = min(max(_entero(request.POST.get("anio"), date.today().year), 2000), 2100)
    mes = min(max(_entero(request.POST.get("mes"), date.today().month), 1), 12)

    if empresa is None:
        messages.error(request, "Configura una empresa antes de asentar la renta.")
    else:
        try:
            asiento = asentar_renta(empresa, anio, mes, usuario=request.user)
        except ContabilidadError as exc:
            messages.error(request, str(exc))
        else:
            if asiento is None:
                messages.info(
                    request, f"No hay renta que asentar en {mes:02d}/{anio}."
                )
            else:
                messages.success(
                    request,
                    f"Renta de {mes:02d}/{anio} asentada en el asiento "
                    f"{asiento.numero}.",
                )
    return redirect(f"{reverse('reportes:impuestos')}?periodo={anio}-{mes:02d}")


@login_required
@requiere_escritura
@require_POST
def pagar_renta_mes(request):
    empresa = empresa_actual(request)
    anio = min(max(_entero(request.POST.get("anio"), date.today().year), 2000), 2100)
    mes = min(max(_entero(request.POST.get("mes"), date.today().month), 1), 12)

    if empresa is None:
        messages.error(request, "Configura una empresa antes de pagar la renta.")
    else:
        try:
            importe = Decimal(
                (request.POST.get("importe") or "0").replace(",", ".")
            )
            fecha = date.fromisoformat(
                request.POST.get("fecha") or date.today().isoformat()
            )
            medio = CuentaTesoreria.objects.get(
                pk=request.POST.get("medio"), empresa=empresa, activa=True
            )
        except (InvalidOperation, TypeError, ValueError, CuentaTesoreria.DoesNotExist):
            messages.error(request, "Revisa el importe, el medio de pago y la fecha.")
        else:
            try:
                registrar_pago_renta(empresa, fecha, importe, medio)
            except ContabilidadError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request, f"Pago de renta registrado por S/ {importe}."
                )
    return redirect(f"{reverse('reportes:impuestos')}?periodo={anio}-{mes:02d}")


@login_required
@requiere_escritura
@require_POST
def pagar_igv_mes(request):
    empresa = empresa_actual(request)
    anio = min(max(_entero(request.POST.get("anio"), date.today().year), 2000), 2100)
    mes = min(max(_entero(request.POST.get("mes"), date.today().month), 1), 12)

    if empresa is None:
        messages.error(request, "Configura una empresa antes de pagar el IGV.")
    else:
        try:
            importe = Decimal(
                (request.POST.get("importe") or "0").replace(",", ".")
            )
            fecha = date.fromisoformat(
                request.POST.get("fecha") or date.today().isoformat()
            )
            medio = CuentaTesoreria.objects.get(
                pk=request.POST.get("medio"), empresa=empresa, activa=True
            )
        except (InvalidOperation, TypeError, ValueError, CuentaTesoreria.DoesNotExist):
            messages.error(request, "Revisa el importe, el medio de pago y la fecha.")
        else:
            try:
                registrar_pago_igv(
                    empresa,
                    fecha,
                    importe,
                    medio,
                    anio,
                    mes,
                    usuario=request.user,
                )
            except ContabilidadError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Pago de IGV de {mes:02d}/{anio} registrado por S/ {importe}.",
                )
    return redirect(f"{reverse('reportes:impuestos')}?periodo={anio}-{mes:02d}")


@login_required
def conciliacion(request):
    """Compara las casillas del sistema con las que muestra SUNAT."""
    empresa = empresa_actual(request)
    hoy = date.today()
    anio = min(max(_entero(request.GET.get("anio"), hoy.year), 2000), 2100)
    mes = min(max(_entero(request.GET.get("mes"), hoy.month), 1), 12)

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


@login_required
def conciliacion_archivo(request):
    """Lee la propuesta del SIRE (RVIE o RCE) y la compara con el registro."""
    empresa = empresa_actual(request)
    hoy = date.today()
    anio = min(
        max(_entero(request.POST.get("anio") or request.GET.get("anio"), hoy.year), 2000),
        2100,
    )
    mes = min(
        max(_entero(request.POST.get("mes") or request.GET.get("mes"), hoy.month), 1), 12
    )
    registro = request.POST.get("registro") or request.GET.get("registro") or "compras"
    if registro not in {"ventas", "compras"}:
        registro = "compras"

    resultado = None
    error = None
    nombre_archivo = None

    if request.method == "POST":
        archivo = request.FILES.get("archivo")
        if archivo is None:
            error = "Adjunta el archivo de la propuesta."
        elif empresa is None:
            error = "Configura una empresa antes de conciliar."
        else:
            try:
                filas = leer_filas(archivo)
                contexto_archivo = validar_contexto(filas, ruc=empresa.ruc, anio=anio, mes=mes)
                totales = sumar(filas)
            except ArchivoInvalido as exc:
                error = str(exc)
            else:
                nombre_archivo = archivo.name
                datos = calcular(empresa, anio, mes)
                if registro == "ventas":
                    sistema_base = datos["ventas_base"]
                    sistema_igv = datos["ventas_igv"]
                    sistema_no_gravado = Decimal("0")
                    etiqueta = "RVIE · ventas"
                else:
                    sistema_base = datos["compras_base"]
                    sistema_igv = datos["compras_igv"]
                    sistema_no_gravado = datos["no_gravado"]
                    etiqueta = "RCE · compras"

                resultado = {
                    "registro": registro,
                    "etiqueta": etiqueta,
                    "filas": totales["filas"],
                    "columnas": totales["columnas"],
                    "contexto_archivo": contexto_archivo,
                    "sunat_base": totales["base"],
                    "sunat_igv": totales["igv"],
                    "sunat_total": totales["total"],
                    "sistema_base": sistema_base,
                    "sistema_igv": sistema_igv,
                    "sistema_no_gravado": sistema_no_gravado,
                    "sistema_total": sistema_base
                    + sistema_igv
                    + sistema_no_gravado,
                }
                resultado["dif_base"] = (
                    resultado["sistema_base"] - resultado["sunat_base"]
                ).quantize(Decimal("0.01"))
                resultado["dif_igv"] = (
                    resultado["sistema_igv"] - resultado["sunat_igv"]
                ).quantize(Decimal("0.01"))
                resultado["dif_total"] = (
                    resultado["sistema_total"] - resultado["sunat_total"]
                ).quantize(Decimal("0.01"))
                resultado["cuadra"] = all(
                    valor == 0
                    for valor in (
                        resultado["dif_base"],
                        resultado["dif_igv"],
                        resultado["dif_total"],
                    )
                )

    return render(
        request,
        "reportes/conciliacion_archivo.html",
        {
            "anio": anio,
            "mes": mes,
            "registro": registro,
            "resultado": resultado,
            "error": error,
            "nombre_archivo": nombre_archivo,
        },
    )

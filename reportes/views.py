"""Reportes contables y tributarios."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria, Producto
from compras.comprobantes import evaluar_tributacion
from compras.models import Compra, NotaCreditoCompra
from compras.models_gasto import Gasto
from contabilidad.impuestos import (
    asentar_renta,
    asiento_renta,
    c184_libro,
    declaracion_vigente,
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
from contabilidad.models import Cuenta, DeclaracionIGV621
from contabilidad.servicios import ContabilidadError
from core.context import empresa_actual
from core.models import HistorialDocumento, Periodo
from core.permisos import requiere_escritura
from inventario.models import CapaFIFO, MovimientoStock
from ventas.models import NotaCredito, NotaDebito, Venta

from .casillas import calcular
from .clientes import nombre_cliente
from .conciliacion_documentos import totales_documentales
from .conciliacion_rce import comparar_rce
from .estados_sire import (
    SireError,
    registrar_ajuste,
    registrar_generacion,
    registrar_propuesta,
    resumen_periodo,
)
from .forms import CompararSaldoIGVForm, DeclaracionIGV621Form
from .sire import (
    ArchivoInvalido,
    leer_filas,
    moneda_verificada_soles,
    sin_registros,
    sumar,
    validar_contexto,
    verificar_registro,
)
from .utils import FiltroReporteError, filtros_seguros, rango
from .vencimientos import panel_vencimientos

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
@filtros_seguros
def balance(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas = []

    if empresa:
        filas = list(
            Cuenta.objects.filter(
                lineas_asiento__asiento__empresa=empresa,
                lineas_asiento__asiento__estado="CONFIRMADO",
                lineas_asiento__asiento__fecha__lte=hasta,
            )
            .annotate(
                inicial_debe=Sum("lineas_asiento__debe", filter=Q(lineas_asiento__asiento__fecha__lt=desde)),
                inicial_haber=Sum("lineas_asiento__haber", filter=Q(lineas_asiento__asiento__fecha__lt=desde)),
                total_debe=Sum("lineas_asiento__debe", filter=Q(lineas_asiento__asiento__fecha__gte=desde)),
                total_haber=Sum("lineas_asiento__haber", filter=Q(lineas_asiento__asiento__fecha__gte=desde)),
            )
            .order_by("codigo")
        )

    for fila in filas:
        debe = fila.total_debe or Decimal("0")
        haber = fila.total_haber or Decimal("0")
        fila.saldo_inicial = (fila.inicial_debe or Decimal("0")) - (fila.inicial_haber or Decimal("0"))
        neto = fila.saldo_inicial + debe - haber
        fila.saldo_deudor = neto if neto > 0 else Decimal("0")
        fila.saldo_acreedor = -neto if neto < 0 else Decimal("0")

    filas = [f for f in filas if f.saldo_inicial or f.total_debe or f.total_haber]
    total_debe = sum((f.total_debe or 0) for f in filas)
    total_haber = sum((f.total_haber or 0) for f in filas)
    total_deudor = sum((f.saldo_deudor for f in filas), Decimal("0"))
    total_acreedor = sum((f.saldo_acreedor for f in filas), Decimal("0"))
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))
    contexto = {
        "filas": pagina,
        "page_obj": pagina,
        "desde": desde,
        "hasta": hasta,
        "total_debe": total_debe,
        "total_haber": total_haber,
        "total_deudor": total_deudor,
        "total_acreedor": total_acreedor,
    }
    return render(request, "reportes/balance.html", contexto)


@login_required
@filtros_seguros
def mayor(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    codigo = request.GET.get("cuenta", "").strip()
    cuenta = None
    movimientos = []
    saldo = Decimal("0")
    saldo_inicial = Decimal("0")
    cuentas_disponibles = Cuenta.objects.none()

    if empresa:
        cuentas_disponibles = (
            Cuenta.objects.filter(version="2026")
            .filter(
                Q(lineas_asiento__asiento__empresa=empresa, lineas_asiento__asiento__estado="CONFIRMADO")
                | Q(codigo=codigo)
            )
            .distinct()
            .order_by("codigo")
        )

    if empresa and codigo:
        cuenta = Cuenta.objects.filter(version="2026", codigo=codigo).first()
        if cuenta:
            previo = cuenta.lineas_asiento.filter(
                asiento__empresa=empresa, asiento__estado="CONFIRMADO", asiento__fecha__lt=desde,
            ).aggregate(debe=Sum("debe"), haber=Sum("haber"))
            saldo_inicial = (previo["debe"] or Decimal("0")) - (previo["haber"] or Decimal("0"))
            saldo = saldo_inicial
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
        "cuentas_disponibles": cuentas_disponibles,
        "movimientos": pagina,
        "page_obj": pagina,
        "saldo": saldo,
        "saldo_inicial": saldo_inicial,
    }
    return render(request, "reportes/mayor.html", contexto)


@login_required
@filtros_seguros
def registro_ventas(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[dict] = []

    if empresa:
        for venta in Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).select_related("cliente").order_by("fecha", "serie", "numero"):
            filas.append(
                {
                    "fecha": venta.fecha,
                    "tipo": venta.get_tipo_doc_display(),
                    "documento": f"{venta.serie}-{venta.numero}",
                    "referencia": "",
                    "cliente": nombre_cliente(venta),
                    "moneda": venta.moneda,
                    "base": venta.subtotal,
                    "igv": venta.igv,
                    "total": venta.total,
                }
            )

        for nota in NotaCredito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta", "venta__cliente"):
            filas.append(
                {
                    "fecha": nota.fecha,
                    "tipo": "Nota de crédito (07)",
                    "documento": f"{nota.serie}-{nota.numero}",
                    "referencia": f"{nota.venta.serie}-{nota.venta.numero}",
                    "cliente": nombre_cliente(nota.venta),
                    "moneda": nota.venta.moneda,
                    "base": -nota.base,
                    "igv": -nota.igv,
                    "total": -nota.total,
                }
            )

        for nota in NotaDebito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta", "venta__cliente"):
            filas.append(
                {
                    "fecha": nota.fecha,
                    "tipo": "Nota de débito (08)",
                    "documento": f"{nota.serie}-{nota.numero}",
                    "referencia": f"{nota.venta.serie}-{nota.venta.numero}",
                    "cliente": nombre_cliente(nota.venta),
                    "moneda": nota.venta.moneda,
                    "base": nota.base,
                    "igv": nota.igv,
                    "total": nota.total,
                }
            )

    filas.sort(key=lambda f: (f["fecha"], f["documento"]))

    totales = {}
    for fila in filas:
        moneda = fila["moneda"] or "Sin moneda"
        acumulado = totales.setdefault(moneda, {"moneda": moneda, "base": Decimal("0"),
                                                 "igv": Decimal("0"), "total": Decimal("0")})
        for campo in ("base", "igv", "total"):
            acumulado[campo] += fila[campo]
    pagina = Paginator(filas, 25).get_page(request.GET.get("page"))

    contexto = {
        "filas": pagina,
        "page_obj": pagina,
        "desde": desde,
        "hasta": hasta,
        "totales_por_moneda": list(totales.values()),
    }
    return render(request, "reportes/registro_ventas.html", contexto)


@login_required
@filtros_seguros
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

        for nota in NotaCreditoCompra.objects.annotate(
            fecha_tributaria=Coalesce("fecha_anotacion", "fecha")
        ).filter(
            compra__empresa=empresa, fecha_tributaria__range=(desde, hasta)
        ).select_related("compra", "compra__proveedor"):
            compra = nota.compra
            usa_credito = evaluar_tributacion(compra).incluido
            filas.append(
                {
                    "fecha": nota.fecha,
                    "fecha_anotacion": nota.fecha_anotacion,
                    "tipo": "Nota de crédito",
                    "documento": f"{nota.serie}-{nota.numero}".strip(" -"),
                    "ruc": compra.proveedor.numero_doc,
                    "proveedor": compra.proveedor.nombre,
                    "detalle": f"Devolución de {compra.serie}-{compra.numero}".strip(" -"),
                    "base": -nota.base if usa_credito and nota.igv > 0 else 0,
                    "no_gravado": -nota.base if usa_credito and nota.igv == 0 else 0,
                    "igv": -nota.igv if usa_credito and nota.igv > 0 else 0,
                    "total": -nota.total,
                    "credito": usa_credito,
                    "pendiente": False,
                    "clase": "Mercadería",
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
@filtros_seguros
def impuestos(request):
    empresa = empresa_actual(request)
    if not any(request.GET.get(k) for k in ("periodo", "desde", "hasta")):
        hoy = timezone.localdate()
        desde = date(hoy.year, hoy.month, 1)
        hasta = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])
    else:
        desde, hasta = rango(request)
    if not _es_mes(desde, hasta) or desde.year < 2:
        raise FiltroReporteError("El reporte de impuestos requiere un mes completo válido.")
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
    declaracion_actual = (
        declaracion_vigente(empresa, desde.year, desde.month)
        if empresa and es_mes
        else None
    )
    pagos_igv = (
        declaracion_actual.pagos.select_related("cuenta", "movimiento").order_by(
            "-fecha", "-pk"
        )
        if declaracion_actual
        else []
    )
    igv_resultante = igv_anterior + igv
    c145 = max(-igv_anterior, Decimal("0"))
    c184 = igv - c145
    formulario_saldo = CompararSaldoIGVForm(request.POST if request.method == "POST" else None)
    comparacion_saldo = None
    c184_declarado = None
    igv_pendiente_declarado = None
    if empresa and request.method == "POST" and formulario_saldo.is_valid():
        declarado = formulario_saldo.cleaned_data["saldo_declarado"]
        comparacion_saldo = {"declarado": declarado, "libro": c145, "diferencia": declarado - c145}
        c184_declarado = igv - declarado
        if es_mes:
            igv_pendiente_declarado = igv_pendiente(
                empresa, desde.year, desde.month, saldo_favor_anterior=declarado
            )
    puede_asentar = bool(empresa and es_mes and renta > 0 and asiento is None)
    puede_pagar_igv = bool(
        empresa
        and es_mes
        and declaracion_actual is not None
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
        "formulario_saldo": formulario_saldo,
        "comparacion_saldo": comparacion_saldo,
        "c184_declarado": c184_declarado,
        "igv_pendiente_declarado": igv_pendiente_declarado,
        "declaraciones_igv": (
            DeclaracionIGV621.objects.filter(empresa=empresa, anio=desde.year, mes=desde.month)
            if empresa and es_mes else []
        ),
        "declaracion_vigente": declaracion_actual,
        "deuda_constancia": (
            declaracion_actual.casilla_184 if declaracion_actual else None
        ),
        "redondeo_constancia": (
            declaracion_actual.redondeo_deuda if declaracion_actual else None
        ),
        "pagos_igv": pagos_igv,
        "formulario_declaracion": DeclaracionIGV621Form(),
        "mes_anterior": desde - timedelta(days=1),
        "c301": base_renta,
        "c312": renta,
        "c303": None,
        "c304": None,
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
def registrar_declaracion_igv(request):
    empresa = empresa_actual(request)
    try:
        anio, mes = int(request.POST.get("anio", "")), int(request.POST.get("mes", ""))
        if not 2000 <= anio <= 2100 or not 1 <= mes <= 12:
            raise ValueError
    except (TypeError, ValueError):
        messages.error(request, "Selecciona un período válido.")
        return redirect("reportes:impuestos")
    destino = f"{reverse('reportes:impuestos')}?periodo={anio}-{mes:02d}"
    formulario = DeclaracionIGV621Form(request.POST)
    if not empresa:
        messages.error(request, "Configura una empresa antes de registrar la declaración.")
    elif not formulario.is_valid():
        for errores in formulario.errors.values():
            for error in errores:
                messages.error(request, error)
    else:
        try:
            with transaction.atomic():
                declaracion = formulario.save(commit=False)
                declaracion.empresa = empresa
                declaracion.anio, declaracion.mes = anio, mes
                declaracion.registrado_por = request.user
                # Redondeo auditable: casilla 184 (enteros) menos el IGV del libro.
                libro = c184_libro(empresa, anio, mes)
                declaracion.redondeo_deuda = (
                    Decimal(declaracion.casilla_184) - libro
                ).quantize(Decimal("0.01"))
                DeclaracionIGV621.objects.filter(
                    empresa=empresa, anio=anio, mes=mes, vigente=True
                ).update(vigente=False)
                declaracion.vigente = True
                declaracion.save()
                HistorialDocumento.objects.create(
                    empresa=empresa, tipo=HistorialDocumento.Tipo.IMPUESTO,
                    documento_id=anio * 100 + mes, usuario=request.user, accion="REGISTRO_621",
                    detalle=(f"Constancia 621 {declaracion.numero_orden}, {declaracion.get_tipo_display()}; "
                             f"casillas 140: {declaracion.casilla_140}, 145: {declaracion.casilla_145}, "
                             f"184: {declaracion.casilla_184}, redondeo: {declaracion.redondeo_deuda}. "
                             f"Queda vigente para el período. Registro manual, sin verificar en SUNAT."),
                )
        except IntegrityError:
            if not DeclaracionIGV621.objects.filter(
                empresa=empresa, numero_orden=formulario.cleaned_data["numero_orden"], anulada=False,
            ).exists():
                raise
            messages.error(request, "Ya existe una constancia con ese número de orden para esta empresa.")
        else:
            messages.success(request, "Datos de la constancia guardados. Verifica su efecto en SUNAT.")
    return redirect(destino)


@login_required
@requiere_escritura
@require_POST
def anular_registro_621(request, pk):
    empresa = empresa_actual(request)
    motivo = (request.POST.get("motivo") or "").strip()
    with transaction.atomic():
        registro = get_object_or_404(
            DeclaracionIGV621.objects.select_for_update(), pk=pk, empresa=empresa,
        )
        if not motivo or len(motivo) > 250:
            messages.error(request, "Indica el motivo del error, con un máximo de 250 caracteres.")
        elif registro.anulada:
            messages.error(request, "Este registro interno ya fue anulado.")
        else:
            era_vigente = registro.vigente
            registro.anulada = True
            registro.vigente = False
            registro.motivo_anulacion = motivo
            registro.anulada_por = request.user
            registro.anulada_en = timezone.now()
            registro.save(
                update_fields=[
                    "anulada",
                    "vigente",
                    "motivo_anulacion",
                    "anulada_por",
                    "anulada_en",
                ]
            )
            HistorialDocumento.objects.create(
                empresa=empresa, tipo=HistorialDocumento.Tipo.IMPUESTO,
                documento_id=registro.anio * 100 + registro.mes, usuario=request.user,
                accion="ANULAR_REG_621",
                detalle=f"Anulación del registro interno {registro.numero_orden}; motivo: {motivo}.",
            )
            messages.success(request, "Registro interno anulado; esto no anula la declaración en SUNAT.")
            if era_vigente:
                messages.warning(
                    request,
                    "Ese registro era la constancia vigente del período: no queda ninguna "
                    "vigente y el pago del IGV queda bloqueado hasta registrar la correcta.",
                )
    return redirect(f"{reverse('reportes:impuestos')}?periodo={registro.anio}-{registro.mes:02d}")


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
            if request.POST.get("saldo_declarado") not in (None, ""):
                raise ValueError("La comparación temporal no es válida para pagos")
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

    movimientos = MovimientoStock.objects.filter(empresa=empresa)
    if q:
        movimientos = movimientos.filter(
            Q(producto__sku__icontains=q) | Q(producto__nombre__icontains=q)
        )
    saldos = list(movimientos.values("producto_id").annotate(
        entradas=Sum("cantidad", filter=Q(tipo=MovimientoStock.Tipo.ENTRADA)),
        salidas=Sum("cantidad", filter=Q(tipo=MovimientoStock.Tipo.SALIDA)),
    ))

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

    faltantes = {saldo["producto_id"] for saldo in saldos} - resumen.keys()
    for producto in Producto.objects.filter(pk__in=faltantes).select_related("unidad"):
        resumen[producto.pk] = {"producto": producto, "cantidad": CERO, "valor": CERO, "capas": 0}
    for saldo in saldos:
        resumen[saldo["producto_id"]]["saldo_kardex"] = (saldo["entradas"] or CERO) - (saldo["salidas"] or CERO)

    filas = sorted(resumen.values(), key=lambda f: f["producto"].sku)
    for fila in filas:
        fila["saldo_kardex"] = fila.get("saldo_kardex", CERO)
        fila["diferencia"] = fila["saldo_kardex"] != fila["cantidad"]
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
            "hay_diferencias": any(f["diferencia"] for f in filas),
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
                archivo_sin_registros = sin_registros(filas)
                contexto_archivo = validar_contexto(filas, ruc=empresa.ruc, anio=anio, mes=mes)
                registro_verificado = verificar_registro(filas, registro=registro)
                totales = sumar(filas)
                archivo_en_soles = moneda_verificada_soles(filas)
            except ArchivoInvalido as exc:
                error = str(exc)
            else:
                nombre_archivo = archivo.name
                try:
                    archivo.seek(0)
                    registrar_propuesta(
                        empresa=empresa,
                        anio=anio,
                        mes=mes,
                        registro="RCE" if registro == "compras" else "RVIE",
                        archivo=archivo,
                        filas=totales["filas"],
                        base=totales["base"],
                        igv=totales["igv"],
                        total=totales["total"],
                        usuario=request.user,
                    )
                except SireError as exc:
                    messages.warning(
                        request,
                        f"Propuesta comparada, pero no se pudo guardar como estado SIRE: {exc}",
                    )
                datos = calcular(empresa, anio, mes)
                if registro == "ventas":
                    sistema_base = datos["ventas_base"] - datos["descuentos_base"]
                    sistema_igv = datos["ventas_igv"] - datos["descuentos_igv"]
                    sistema_no_gravado = Decimal("0")
                    etiqueta = "RVIE · ventas"
                else:
                    sistema_base = datos["compras_base"]
                    sistema_igv = datos["compras_igv"]
                    sistema_no_gravado = datos["no_gravado"]
                    etiqueta = "RCE · compras"

                documentales = totales_documentales(empresa=empresa, anio=anio, mes=mes, registro=registro)

                resultado = {
                    "registro": registro,
                    "etiqueta": etiqueta,
                    "filas": totales["filas"],
                    "columnas": totales["columnas"],
                    "contexto_archivo": contexto_archivo,
                    "registro_verificado": registro_verificado,
                    "sin_registros": archivo_sin_registros,
                    "sunat_base": totales["base"],
                    "sunat_igv": totales["igv"],
                    "sunat_total": totales["total"],
                    "tiene_total": totales["tiene_total"],
                    "sistema_base": sistema_base,
                    "sistema_igv": sistema_igv,
                    "sistema_no_gravado": sistema_no_gravado,
                    "sistema_total": documentales["total"],
                    "documentos_sin_credito": documentales["sin_credito"],
                    "documentos_incompletos": documentales["incompletos"],
                    "otras_monedas": documentales["otras_monedas"],
                    "moneda_verificada": archivo_en_soles,
                    "total_comparable": (
                        totales["tiene_total"] and archivo_en_soles and not documentales["otras_monedas"]
                    ),
                }
                resultado["dif_base"] = (
                    (resultado["sistema_base"] - resultado["sunat_base"]).quantize(Decimal("0.01"))
                    if archivo_en_soles and not documentales["otras_monedas"] else None
                )
                resultado["dif_igv"] = (
                    (resultado["sistema_igv"] - resultado["sunat_igv"]).quantize(Decimal("0.01"))
                    if archivo_en_soles and not documentales["otras_monedas"] else None
                )
                resultado["dif_total"] = (
                    (resultado["sistema_total"] - resultado["sunat_total"]).quantize(Decimal("0.01"))
                    if resultado["total_comparable"] else None
                )
                resultado["cuadra"] = (
                    resultado["total_comparable"]
                    and resultado["registro_verificado"]
                    and all(contexto_archivo.values())
                    and not documentales["incompletos"]
                    and all(
                        valor == 0
                        for valor in (
                            resultado["dif_base"],
                            resultado["dif_igv"],
                            resultado["dif_total"],
                        )
                    )
                )
                if registro == "compras":
                    resultado["documentos"] = comparar_rce(filas=filas, empresa=empresa, anio=anio, mes=mes)
                    comparacion = resultado["documentos"]
                    if comparacion and any(comparacion[campo] for campo in (
                        "solo_archivo", "solo_sistema", "diferentes", "ambiguos", "omitidos_archivo",
                        "omitidos_sistema",
                    )):
                        resultado["cuadra"] = False

                resultado["estado"] = (
                    "sin_registros"
                    if resultado["sin_registros"]
                    else "cuadra"
                    if resultado["cuadra"]
                    else "revisar"
                )

    documentos = resultado.get("documentos") if resultado else None
    grupos_documentos = [
        ("Solo en el ERP", documentos["solo_sistema"]),
        ("Solo en la propuesta", documentos["solo_archivo"]),
        ("Fechas o importes diferentes", documentos["diferentes"]),
        ("Identificación duplicada: revisar", documentos["ambiguos"]),
    ] if documentos else []
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
            "grupos_documentos": grupos_documentos,
        },
    )


@login_required
def vencimientos(request):
    """Vencimientos de octubre 2026 y dependencia de caja."""
    empresa = empresa_actual(request)
    anio = request.GET.get("anio") or 2026
    mes = request.GET.get("mes") or 10
    try:
        anio, mes = int(anio), int(mes)
    except (TypeError, ValueError):
        anio, mes = 2026, 10
    return render(
        request,
        "reportes/vencimientos.html",
        {
            "datos": panel_vencimientos(empresa, anio, mes),
            "anio": anio,
            "mes": mes,
        },
    )


@login_required
@requiere_escritura
def estado_sire(request):
    """Estado documental del SIRE: propuesta, complemento y constancia."""
    empresa = empresa_actual(request)
    hoy = date.today()
    anio = request.POST.get("anio") or request.GET.get("anio") or hoy.year
    mes = request.POST.get("mes") or request.GET.get("mes") or hoy.month
    try:
        anio, mes = int(anio), int(mes)
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month
    if not 2000 <= anio <= 2100:
        anio = hoy.year
    if not 1 <= mes <= 12:
        mes = hoy.month

    if request.method == "POST" and empresa is not None:
        accion = request.POST.get("accion")
        registro = request.POST.get("registro") or "RCE"
        try:
            if accion == "ajuste":
                fecha = request.POST.get("fecha") or ""
                registrar_ajuste(
                    empresa=empresa,
                    anio=anio,
                    mes=mes,
                    registro=registro,
                    tipo=request.POST.get("tipo", ""),
                    documento=request.POST.get("documento", ""),
                    tipo_doc=request.POST.get("tipo_doc", "OTRO"),
                    fecha=date.fromisoformat(fecha) if fecha else None,
                    base=request.POST.get("base") or 0,
                    igv=request.POST.get("igv") or 0,
                    total=request.POST.get("total") or None,
                    motivo=request.POST.get("motivo", ""),
                    usuario=request.user,
                )
                messages.success(
                    request, "Ajuste registrado. La propuesta queda complementada."
                )
            elif accion == "generar":
                generado = request.POST.get("generado_en") or ""
                registrar_generacion(
                    empresa=empresa,
                    anio=anio,
                    mes=mes,
                    registro=registro,
                    constancia_recepcion=request.POST.get("constancia_recepcion", ""),
                    numero_operacion=request.POST.get("numero_operacion", ""),
                    registros=request.POST.get("registros") or 0,
                    generado_en=(
                        datetime.fromisoformat(generado) if generado else None
                    ),
                    usuario=request.user,
                )
                messages.success(
                    request,
                    "Constancia registrada. El registro queda GENERADO; revisa si el "
                    "período está completo antes de cerrarlo.",
                )
            else:
                messages.error(request, "Acción no reconocida.")
        except (SireError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect(f"{reverse('reportes:estado_sire')}?anio={anio}&mes={mes}")

    resumen = resumen_periodo(empresa, anio, mes) if empresa else None
    return render(
        request,
        "reportes/estado_sire.html",
        {
            "anio": anio,
            "mes": mes,
            "resumen": resumen,
            "registros": resumen["registros"] if resumen else [],
        },
    )

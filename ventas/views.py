"""Pantallas de ventas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria, Producto, Serie, Tercero
from contabilidad.calculos import calcular_linea
from contabilidad.models import Asiento
from core.context import empresa_actual
from core.contexto import usuario_actual
from core.models import HistorialDocumento
from core.permisos import requiere_escritura
from inventario.servicios import StockError
from reportes.casillas import casillas_documento

from .forms import CabeceraVentaForm
from .models import NotaCredito, NotaCreditoLinea, NotaDebito, Venta, VentaLinea
from .servicios import (
    MOTIVOS_CREDITO_IMPLEMENTADOS,
    VentaError,
    confirmar,
    emitir_nota_credito,
    emitir_nota_debito,
)


def _numero_siguiente(empresa, tipo_doc: str, serie: str) -> str:
    registro = Serie.objects.filter(
        empresa=empresa,
        tipo=tipo_doc,
        serie=serie,
    ).first()
    return str((registro.ultimo_numero if registro else 0) + 1)


def _filas_vacias(cantidad: int = 3) -> list[dict]:
    return [{"producto_id": "", "cantidad": "", "precio": ""} for _ in range(cantidad)]


def _leer_filas(post) -> tuple[list[dict], list[str]]:
    productos = post.getlist("linea_producto")
    cantidades = post.getlist("linea_cantidad")
    precios = post.getlist("linea_precio")
    descripciones = post.getlist("linea_descripcion")
    con_igv = bool(post.get("con_igv"))

    filas: list[dict] = []
    errores: list[str] = []

    for indice, (producto_id, cantidad_txt, precio_txt) in enumerate(
        zip(productos, cantidades, precios, strict=False), start=1
    ):
        if not producto_id and not cantidad_txt and not precio_txt:
            continue
        fila = {
            "producto_id": producto_id,
            "cantidad": cantidad_txt,
            "precio": precio_txt,
            "descripcion": (
                descripciones[indice - 1] if indice <= len(descripciones) else ""
            ),
        }
        try:
            producto = Producto.objects.get(pk=int(producto_id))
            cantidad = Decimal(cantidad_txt.replace(",", "."))
            precio = Decimal(precio_txt.replace(",", "."))
        except (ValueError, TypeError, InvalidOperation, Producto.DoesNotExist):
            errores.append(f"Línea {indice}: revisa producto, cantidad y precio.")
            fila["seleccionado"] = producto_id
            filas.append(fila)
            continue

        if cantidad <= 0 or precio <= 0:
            errores.append(f"Línea {indice}: cantidad y precio deben ser positivos.")
            fila["seleccionado"] = producto.pk
            filas.append(fila)
            continue

        base, igv, total = calcular_linea(cantidad, precio, con_igv)
        fila.update(
            {
                "producto": producto,
                "seleccionado": producto.pk,
                "cantidad": cantidad,
                "precio": precio,
                "base": base,
                "igv": igv,
                "total": total,
            }
        )
        filas.append(fila)

    if not filas:
        errores.append("Agrega al menos una línea.")
    return filas, errores


def _filas_desde_venta(venta: Venta) -> list[dict]:
    filas = []
    for linea in venta.lineas.all():
        precio = (
            (linea.total / linea.cantidad) if linea.cantidad else linea.precio_unitario
        )
        filas.append(
            {
                "producto_id": linea.producto_id,
                "seleccionado": linea.producto_id,
                "cantidad": linea.cantidad,
                "precio": precio,
                "descripcion": linea.descripcion,
            }
        )
    return filas or _filas_vacias()


@login_required
def lista(request):
    empresa = empresa_actual(request)
    consulta = (
        Venta.objects.filter(empresa=empresa).select_related("cliente")
        if empresa
        else Venta.objects.none()
    )
    periodo = request.GET.get("periodo", "")
    if periodo and "-" in periodo:
        anio, mes = (int(p) for p in periodo.split("-", 1))
        consulta = consulta.filter(fecha__year=anio, fecha__month=mes)

    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        consulta = consulta.filter(
            Q(cliente_nombre__icontains=busqueda)
            | Q(cliente__nombre__icontains=busqueda)
            | Q(cliente__numero_doc__icontains=busqueda)
            | Q(serie__icontains=busqueda)
            | Q(numero__icontains=busqueda)
        )

    producto_id = request.GET.get("producto", "")
    if producto_id:
        consulta = consulta.filter(lineas__producto_id=producto_id).distinct()
    pagina = Paginator(consulta, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "ventas/lista.html",
        {
            "ventas": pagina,
            "page_obj": pagina,
            "q": busqueda,
            "producto_id": producto_id,
            "productos": Producto.objects.filter(activo=True),
        },
    )


@login_required
@requiere_escritura
@transaction.atomic
def nueva(request):
    empresa = empresa_actual(request)
    if empresa is None:
        messages.error(request, "Primero configura una empresa.")
        return redirect("core:panel")

    productos = list(Producto.objects.filter(activo=True))
    cuentas = list(CuentaTesoreria.objects.filter(empresa=empresa, activa=True))
    hoy = date.today()

    venta_edit = None
    editar_id = request.GET.get("editar") or request.POST.get("venta_id")
    if editar_id:
        venta_edit = get_object_or_404(Venta, pk=editar_id, empresa=empresa)
        if venta_edit.estado != Venta.Estado.BORRADOR:
            messages.error(request, "Solo se puede editar una venta en borrador.")
            return redirect("ventas:detalle", venta_edit.pk)

    contexto = {
        "productos": productos,
        "cuentas": cuentas,
        "hoy": hoy,
        "con_igv": True,
        "filas": _filas_vacias(),
        "venta": venta_edit,
        "cabecera": {
            "tipo_doc": "BOLETA",
            "serie": "B001",
            "numero": _numero_siguiente(empresa, "BOLETA", "B001"),
            "condicion": "CONTADO",
            "fecha": hoy.isoformat(),
            "cuenta": cuentas[0].pk if cuentas else "",
            "canal": "TRANSFERENCIA",
            "cliente_nombre": "",
            "cliente_doc": "",
            "glosa": "",
        },
    }

    if venta_edit is not None:
        contexto["filas"] = _filas_desde_venta(venta_edit)
        contexto["cabecera"] = {
            "tipo_doc": venta_edit.tipo_doc,
            "serie": venta_edit.serie,
            "numero": venta_edit.numero,
            "condicion": venta_edit.condicion,
            "fecha": venta_edit.fecha.isoformat(),
            "cuenta": venta_edit.cuenta_id or "",
            "canal": venta_edit.canal,
            "cliente_nombre": venta_edit.cliente_nombre,
            "cliente_doc": (
                venta_edit.cliente.numero_doc if venta_edit.cliente else ""
            ),
            "glosa": venta_edit.glosa,
        }

    if request.method != "POST":
        return render(request, "ventas/nueva.html", contexto)

    filas, errores = _leer_filas(request.POST)
    formulario = CabeceraVentaForm(request.POST, empresa=empresa)
    if not formulario.is_valid():
        for textos in formulario.errors.values():
            errores.extend(textos)

    contexto.update(
        {
            "filas": filas,
            "errores": errores,
            "con_igv": bool(request.POST.get("con_igv")),
            "cabecera": {
                "tipo_doc": request.POST.get("tipo_doc", "BOLETA"),
                "serie": request.POST.get("serie", "B001"),
                "numero": request.POST.get("numero", ""),
                "condicion": request.POST.get("condicion", "CONTADO"),
                "cliente_nombre": request.POST.get("cliente_nombre", ""),
                "cliente_doc": request.POST.get("cliente_doc", ""),
                "cuenta": request.POST.get("cuenta", ""),
                "canal": request.POST.get("canal", "TRANSFERENCIA"),
                "glosa": request.POST.get("glosa", ""),
                "fecha": request.POST.get("fecha", hoy.isoformat()),
            },
        }
    )

    if errores:
        return render(request, "ventas/nueva.html", contexto)

    datos = formulario.cleaned_data

    cliente = None
    if datos.get("cliente_doc"):
        tipo = "RUC" if len(datos["cliente_doc"]) == 11 else "DNI"
        cliente, _ = Tercero.objects.get_or_create(
            tipo_doc=tipo,
            numero_doc=datos["cliente_doc"],
            defaults={
                "nombre": datos.get("cliente_nombre") or "Cliente sin nombre",
                "rol": "CLIENTE",
            },
        )

    if venta_edit is None:
        venta = Venta(empresa=empresa, creado_por=usuario_actual.get())
    else:
        venta = venta_edit
        venta.lineas.all().delete()

    venta.cliente = cliente
    venta.cliente_nombre = (
        datos.get("cliente_nombre") or (cliente.nombre if cliente else "")
    )[:200]
    venta.fecha = datos["fecha"]
    venta.tipo_doc = datos["tipo_doc"]
    venta.serie = datos["serie"].upper()[:4]
    venta.numero = datos["numero"][:20]
    venta.condicion = datos["condicion"]
    venta.cuenta = datos.get("cuenta")
    venta.canal = datos.get("canal") or "TRANSFERENCIA"
    venta.glosa = datos.get("glosa", "")[:255]
    venta.modificado_por = usuario_actual.get()
    venta.modificado_en = timezone.now()
    venta.save()

    for orden, fila in enumerate(filas, start=1):
        VentaLinea.objects.create(
            venta=venta,
            orden=orden,
            producto=fila["producto"],
            descripcion=fila.get("descripcion", "")[:200],
            cantidad=fila["cantidad"],
            precio_unitario=fila["precio"],
            base=fila["base"],
            igv=fila["igv"],
            total=fila["total"],
        )
    venta.subtotal = sum((f["base"] for f in filas), Decimal("0"))
    venta.igv = sum((f["igv"] for f in filas), Decimal("0"))
    venta.total = venta.subtotal + venta.igv
    venta.save(update_fields=["subtotal", "igv", "total"])

    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo="VENTA",
        documento_id=venta.pk,
        usuario=usuario_actual.get(),
        accion="EDICION" if venta_edit else "CREACION",
        detalle=f"{venta.serie}-{venta.numero} · total {venta.total}",
    )
    messages.success(
        request,
        "Venta actualizada." if venta_edit else "Borrador creado. Revísalo y confírmalo.",
    )
    return redirect("ventas:detalle", venta.pk)


@login_required
@requiere_escritura
def nota_credito(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)
    lineas = list(venta.lineas.select_related("producto"))
    acreditado = {
        fila["venta_linea_id"]: fila["total"]
        for fila in NotaCreditoLinea.objects.filter(nota__venta=venta)
        .values("venta_linea_id")
        .annotate(total=Sum("cantidad"))
    }
    for linea in lineas:
        linea.acreditado = acreditado.get(linea.pk, Decimal("0"))
        linea.disponible = linea.cantidad - linea.acreditado

    if request.method == "POST":
        cantidades = {}
        for linea in lineas:
            valor = (request.POST.get(f"cantidad_{linea.pk}") or "0").replace(",", ".")
            try:
                cantidades[linea.pk] = Decimal(valor)
            except InvalidOperation:
                messages.error(request, "Hay una cantidad inválida.")
                cantidades = None
                break
        if cantidades is not None:
            try:
                nota = emitir_nota_credito(
                    venta=venta,
                    fecha=date.fromisoformat(
                        request.POST.get("fecha") or date.today().isoformat()
                    ),
                    serie=request.POST.get("serie", "").strip().upper()[:4],
                    numero=request.POST.get("numero", "")[:20],
                    motivo_codigo=request.POST.get("motivo", "07"),
                    cantidades=cantidades,
                    reingresa_stock=bool(request.POST.get("reingresa")),
                    descripcion=request.POST.get("descripcion", ""),
                )
            except (VentaError, StockError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Nota de crédito {nota} registrada.")
                return redirect("ventas:detalle", venta.pk)

    return render(
        request,
        "ventas/nota_credito.html",
        {
            "venta": venta,
            "lineas": lineas,
            "motivos": [
                (codigo, texto) for codigo, texto in NotaCredito.Motivo.choices
                if codigo in MOTIVOS_CREDITO_IMPLEMENTADOS
            ],
            "hoy": date.today(),
        },
    )


@login_required
@requiere_escritura
def nota_debito(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)

    if request.method == "POST":
        try:
            base, _igv, _total = calcular_linea(
                Decimal("1"), Decimal((request.POST.get("base") or "0").replace(",", ".")), False
            )
            emitir_nota_debito(
                venta=venta,
                fecha=date.fromisoformat(
                    request.POST.get("fecha") or date.today().isoformat()
                ),
                serie=request.POST.get("serie", "").strip().upper()[:4],
                numero=request.POST.get("numero", "")[:20],
                motivo_codigo=request.POST.get("motivo", "01"),
                base=base,
                igv=_igv,
                descripcion=request.POST.get("descripcion", ""),
            )
        except (VentaError, InvalidOperation) as exc:
            messages.error(request, f"No se pudo emitir: {exc}")
        else:
            messages.success(request, "Nota de débito registrada.")
            return redirect("ventas:detalle", venta.pk)

    return render(
        request,
        "ventas/nota_debito.html",
        {
            "venta": venta,
            "motivos": NotaDebito.Motivo.choices,
            "hoy": date.today(),
        },
    )


@login_required
def detalle(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)
    asiento = Asiento.objects.filter(
        origen_tipo="VENTA", origen_id=venta.pk, tipo_operacion="VENTA"
    ).first()
    return render(
        request,
        "ventas/detalle.html",
        {
            "venta": venta,
            "asiento": asiento,
            "casillas_621": casillas_documento(venta),
            "historial": HistorialDocumento.objects.filter(
                empresa=venta.empresa, tipo="VENTA", documento_id=venta.pk
            ).order_by("-fecha")[:10],
        },
    )


@login_required
@requiere_escritura
@require_POST
def confirmar_venta(request, pk: int):
    venta = get_object_or_404(Venta, pk=pk)
    try:
        confirmar(venta)
    except (VentaError, StockError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Venta confirmada: stock, asiento y cobro listos.")
    return redirect("ventas:detalle", venta.pk)

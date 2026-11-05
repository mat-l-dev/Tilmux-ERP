"""Pantallas de compras."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalogo.models import Producto, Tercero
from contabilidad.calculos import calcular_linea
from contabilidad.models import Asiento
from core.context import empresa_actual

from .models import Compra, CompraLinea, CostoAdicional
from .servicios import CompraError, confirmar


def _decimal(texto: str) -> Decimal:
    return Decimal(str(texto).replace(",", ".").strip())


@login_required
def lista(request):
    empresa = empresa_actual(request)
    compras = (
        Compra.objects.filter(empresa=empresa).select_related("proveedor")[:100]
        if empresa
        else Compra.objects.none()
    )
    return render(request, "compras/lista.html", {"compras": compras})


@login_required
def nueva(request):
    empresa = empresa_actual(request)
    if empresa is None:
        messages.error(request, "Primero configura una empresa.")
        return redirect("core:panel")

    productos = list(Producto.objects.filter(activo=True))
    proveedores = list(
        Tercero.objects.filter(rol__in=["PROVEEDOR", "AMBOS"], activo=True)
    )
    hoy = date.today()

    contexto = {
        "productos": productos,
        "proveedores": proveedores,
        "hoy": hoy,
        "filas": [{} for _ in range(4)],
        "costos": [{} for _ in range(2)],
        "cabecera": {
            "fecha": hoy.isoformat(),
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "",
            "proveedor": "",
            "glosa": "",
        },
    }

    if request.method != "POST":
        return render(request, "compras/nueva.html", contexto)

    errores: list[str] = []

    proveedor = None
    proveedor_id = request.POST.get("proveedor") or ""
    if proveedor_id:
        proveedor = Tercero.objects.filter(pk=proveedor_id).first()
    if proveedor is None:
        nombre = request.POST.get("proveedor_nombre", "").strip()
        ruc = request.POST.get("proveedor_ruc", "").strip()
        if nombre and len(ruc) == 11 and ruc.isdigit():
            proveedor, _ = Tercero.objects.get_or_create(
                tipo_doc="RUC",
                numero_doc=ruc,
                defaults={"nombre": nombre, "rol": "PROVEEDOR"},
            )
        else:
            errores.append("Elige un proveedor o escribe nombre y RUC de 11 dígitos.")

    filas: list[dict] = []
    productos_ids = request.POST.getlist("linea_producto")
    cantidades = request.POST.getlist("linea_cantidad")
    precios = request.POST.getlist("linea_precio")

    for indice, (producto_id, cantidad_txt, precio_txt) in enumerate(
        zip(productos_ids, cantidades, precios), start=1
    ):
        if not producto_id and not cantidad_txt and not precio_txt:
            continue
        fila = {"producto_id": producto_id, "cantidad": cantidad_txt, "precio": precio_txt}
        try:
            producto = Producto.objects.get(pk=int(producto_id))
            cantidad = _decimal(cantidad_txt)
            precio = _decimal(precio_txt)
            if cantidad <= 0 or precio <= 0:
                raise ValueError
        except (ValueError, TypeError, InvalidOperation, Producto.DoesNotExist):
            errores.append(f"Línea {indice}: revisa producto, cantidad y precio.")
            filas.append(fila)
            continue
        base, igv, total = calcular_linea(cantidad, precio, con_igv=False)
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

    costos: list[dict] = []
    conceptos = request.POST.getlist("costo_concepto")
    bases = request.POST.getlist("costo_base")
    igvs = request.POST.getlist("costo_igv")
    for concepto, base_txt, igv_txt in zip(conceptos, bases, igvs):
        if not concepto.strip() and not base_txt:
            continue
        try:
            base = _decimal(base_txt or "0")
            igv = _decimal(igv_txt or "0")
        except (InvalidOperation, TypeError):
            errores.append(f"Costo «{concepto}»: importes inválidos.")
            continue
        if base < 0 or igv < 0:
            errores.append(f"Costo «{concepto}»: importes negativos.")
            continue
        costos.append(
            {"concepto": concepto, "base": base, "igv": igv, "total": base + igv}
        )

    contexto.update(
        {
            "filas": filas,
            "costos": costos,
            "errores": errores,
            "cabecera": {
                "fecha": request.POST.get("fecha", hoy.isoformat()),
                "tipo_doc": request.POST.get("tipo_doc", "FACTURA"),
                "serie": request.POST.get("serie", "F001"),
                "numero": request.POST.get("numero", ""),
                "proveedor": proveedor_id,
                "glosa": request.POST.get("glosa", ""),
            },
        }
    )
    if errores:
        return render(request, "compras/nueva.html", contexto)

    compra = Compra.objects.create(
        empresa=empresa,
        proveedor=proveedor,
        fecha=date.fromisoformat(request.POST.get("fecha") or hoy.isoformat()),
        tipo_doc=request.POST.get("tipo_doc", "FACTURA"),
        serie=request.POST.get("serie", "").upper()[:4],
        numero=request.POST.get("numero", "")[:20],
        glosa=request.POST.get("glosa", "")[:255],
    )
    for orden, fila in enumerate(filas, start=1):
        CompraLinea.objects.create(
            compra=compra,
            orden=orden,
            producto=fila["producto"],
            cantidad=fila["cantidad"],
            precio_unitario=fila["precio"],
            base=fila["base"],
            igv=fila["igv"],
            total=fila["total"],
        )
    for costo in costos:
        CostoAdicional.objects.create(
            compra=compra,
            concepto=costo["concepto"][:120],
            base=costo["base"],
            igv=costo["igv"],
            total=costo["total"],
        )

    compra.subtotal = sum((f["base"] for f in filas), Decimal("0")) + sum(
        (c["base"] for c in costos), Decimal("0")
    )
    compra.igv = sum((f["igv"] for f in filas), Decimal("0")) + sum(
        (c["igv"] for c in costos), Decimal("0")
    )
    compra.total = compra.subtotal + compra.igv
    compra.save(update_fields=["subtotal", "igv", "total"])

    messages.success(request, "Borrador creado. Revísalo y confírmalo.")
    return redirect("compras:detalle", compra.pk)


@login_required
def detalle(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk)
    asiento = Asiento.objects.filter(
        origen_tipo="COMPRA", origen_id=compra.pk
    ).first()
    return render(
        request, "compras/detalle.html", {"compra": compra, "asiento": asiento}
    )


@login_required
@require_POST
def confirmar_compra(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk)
    try:
        confirmar(compra)
    except CompraError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Compra confirmada: stock y asiento generados.")
    return redirect("compras:detalle", compra.pk)

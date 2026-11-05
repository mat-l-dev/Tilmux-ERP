"""Pantallas de compras."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria, Producto, Tercero
from contabilidad.calculos import calcular_linea
from contabilidad.models import Asiento, Cuenta
from contabilidad.moneda import SinTipoCambio, a_soles
from core.context import empresa_actual
from core.contexto import usuario_actual
from core.permisos import requiere_escritura
from documentos.xml_cpe import Guia, XMLInvalido, leer
from ventas.models import Venta
from ventas.models_guia import GuiaRemision

from .forms import CabeceraCompraForm
from .models import Compra, CompraLinea, CostoAdicional
from .servicios import CompraError, confirmar, pagar, registrar_gasto


def _decimal(texto: str) -> Decimal:
    return Decimal(str(texto).replace(",", ".").strip())


@login_required
def lista(request):
    empresa = empresa_actual(request)
    consulta = (
        Compra.objects.filter(empresa=empresa).select_related("proveedor")
        if empresa
        else Compra.objects.none()
    )
    pagina = Paginator(consulta, 25).get_page(request.GET.get("page"))
    return render(
        request, "compras/lista.html", {"compras": pagina, "page_obj": pagina}
    )


@login_required
@requiere_escritura
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
        zip(productos_ids, cantidades, precios, strict=False), start=1
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
    for concepto, base_txt, igv_txt in zip(conceptos, bases, igvs, strict=False):
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

    formulario = CabeceraCompraForm(request.POST)
    if not formulario.is_valid():
        for textos in formulario.errors.values():
            errores.extend(textos)
        return render(request, "compras/nueva.html", contexto)

    datos = formulario.cleaned_data

    compra = Compra.objects.create(
        empresa=empresa,
        proveedor=proveedor,
        fecha=datos["fecha"],
        tipo_doc=datos["tipo_doc"],
        serie=datos["serie"].upper()[:4],
        numero=datos["numero"][:20],
        glosa=datos.get("glosa", "")[:255],
        creado_por=usuario_actual.get(),
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


MAXIMO_XML = 2 * 1024 * 1024

CUENTAS_SUGERIDAS = {"BANCO": "6391", "MERCADOLIBRE": "6311"}


def _cuenta_sugerida(emisor: str) -> Cuenta | None:
    codigo = "6593"
    nombre = (emisor or "").upper()
    for clave, valor in CUENTAS_SUGERIDAS.items():
        if clave in nombre:
            codigo = valor
            break
    return Cuenta.objects.filter(version="2026", codigo=codigo).first()


@login_required
@requiere_escritura
def importar(request):
    empresa = empresa_actual(request)
    if request.method == "POST":
        archivo = request.FILES.get("archivo")
        if archivo is None:
            messages.error(request, "Adjunta un archivo XML.")
        elif archivo.size > MAXIMO_XML:
            messages.error(request, "El archivo supera los 2 MB.")
        else:
            try:
                documento = leer(archivo.read(MAXIMO_XML))
            except XMLInvalido as exc:
                messages.error(request, str(exc))
            else:
                if isinstance(documento, Guia):
                    venta = None
                    referencia = documento.documento_referencia
                    if "-" in referencia:
                        serie_ref, numero_ref = referencia.split("-", 1)
                        venta = Venta.objects.filter(
                            empresa=empresa, serie=serie_ref, numero=numero_ref
                        ).first()
                    request.session["guia_pendiente"] = {
                        "tipo": documento.tipo,
                        "serie": documento.serie,
                        "numero": documento.numero,
                        "fecha": documento.fecha.isoformat(),
                        "remitente_ruc": documento.remitente_ruc,
                        "remitente_nombre": documento.remitente_nombre,
                        "destinatario_ruc": documento.destinatario_ruc,
                        "destinatario_nombre": documento.destinatario_nombre,
                        "peso_bruto": str(documento.peso_bruto or ""),
                        "bultos": documento.bultos,
                        "documento_referencia": documento.documento_referencia,
                        "venta_id": venta.pk if venta else None,
                    }
                    return render(
                        request,
                        "compras/importar_guia.html",
                        {"guia": documento, "venta": venta},
                    )

                try:
                    total_soles, tipo_cambio = a_soles(
                        documento.total, documento.moneda, documento.fecha, lado="venta"
                    )
                    igv_soles, _ = a_soles(
                        documento.igv, documento.moneda, documento.fecha, lado="venta"
                    )
                except SinTipoCambio as exc:
                    messages.error(request, str(exc))
                    return render(request, "compras/importar.html", {"empresa": empresa})

                base_soles = total_soles - igv_soles

                request.session["xml_pendiente"] = {
                    "tipo": documento.tipo,
                    "serie": documento.serie,
                    "numero": documento.numero,
                    "fecha": documento.fecha.isoformat(),
                    "moneda": documento.moneda,
                    "moneda_original": documento.moneda,
                    "tipo_cambio": str(tipo_cambio),
                    "total_original": str(documento.total),
                    "emisor_ruc": documento.emisor_ruc,
                    "emisor_nombre": documento.emisor_nombre,
                    "base": str(base_soles),
                    "igv": str(igv_soles),
                    "total": str(total_soles),
                    "lineas": [
                        {
                            "descripcion": linea.descripcion,
                            "cantidad": str(linea.cantidad),
                            "valor_unitario": str(linea.valor_unitario),
                            "base": str(linea.base),
                        }
                        for linea in documento.lineas
                    ],
                }
                return redirect("compras:importar_preview")
    return render(request, "compras/importar.html", {"empresa": empresa})


@login_required
@requiere_escritura
def importar_preview(request):
    empresa = empresa_actual(request)
    datos = request.session.get("xml_pendiente")
    if not datos:
        messages.info(request, "Primero sube un comprobante.")
        return redirect("compras:importar")

    cuentas = list(
        Cuenta.objects.filter(
            version="2026", activa=True, elemento=6, admite_movimiento=True
        ).order_by("codigo")
    )
    medios = list(CuentaTesoreria.objects.filter(empresa=empresa, activa=True))
    sugerida = _cuenta_sugerida(datos["emisor_nombre"])

    if request.method == "POST":
        cuenta = Cuenta.objects.filter(pk=request.POST.get("cuenta")).first()
        medio = CuentaTesoreria.objects.filter(
            pk=request.POST.get("medio"), empresa=empresa
        ).first()
        if cuenta is None or medio is None:
            messages.error(request, "Elige la cuenta del gasto y el medio de pago.")
        else:
            proveedor, _ = Tercero.objects.get_or_create(
                tipo_doc="RUC",
                numero_doc=datos["emisor_ruc"],
                defaults={
                    "nombre": datos["emisor_nombre"] or "Proveedor",
                    "rol": "PROVEEDOR",
                },
            )
            try:
                registrar_gasto(
                    empresa=empresa,
                    proveedor=proveedor,
                    fecha=date.fromisoformat(datos["fecha"]),
                    tipo_doc=datos["tipo"],
                    serie=datos["serie"],
                    numero=datos["numero"],
                    base=Decimal(datos["base"]),
                    igv=Decimal(datos["igv"]),
                    total=Decimal(datos["total"]),
                    cuenta=cuenta,
                    medio=medio,
                    glosa=f"{datos['tipo']} {datos['serie']}-{datos['numero']}",
                    con_credito=datos["tipo"] == "FACTURA",
                    deducible=datos["tipo"] == "FACTURA",
                )
            except (CompraError, IntegrityError) as exc:
                messages.error(request, f"No se pudo registrar: {exc}")
            else:
                request.session.pop("xml_pendiente", None)
                messages.success(
                    request,
                    f"Gasto registrado: {datos['serie']}-{datos['numero']} "
                    f"por S/ {datos['total']}.",
                )
                return redirect("compras:lista")

    return render(
        request,
        "compras/importar_preview.html",
        {"datos": datos, "cuentas": cuentas, "medios": medios, "sugerida": sugerida},
    )


@login_required
@requiere_escritura
@require_POST
def vincular_guia(request):
    empresa = empresa_actual(request)
    datos = request.session.get("guia_pendiente")
    if not datos:
        messages.info(request, "Primero sube una guía.")
        return redirect("compras:importar")

    venta = None
    if datos.get("venta_id"):
        venta = Venta.objects.filter(pk=datos["venta_id"]).first()

    guia, creada = GuiaRemision.objects.update_or_create(
        empresa=empresa,
        serie=datos["serie"],
        numero=datos["numero"],
        defaults={
            "tipo": datos["tipo"],
            "fecha": date.fromisoformat(datos["fecha"]),
            "remitente_ruc": datos["remitente_ruc"],
            "remitente_nombre": datos["remitente_nombre"],
            "destinatario_ruc": datos["destinatario_ruc"],
            "destinatario_nombre": datos["destinatario_nombre"],
            "peso_bruto": Decimal(datos["peso_bruto"]) if datos["peso_bruto"] else None,
            "bultos": datos["bultos"],
            "documento_referencia": datos["documento_referencia"],
            "venta": venta,
        },
    )
    request.session.pop("guia_pendiente", None)
    if venta:
        messages.success(
            request, f"Guía {guia} vinculada a la venta {venta.serie}-{venta.numero}."
        )
    else:
        messages.warning(
            request,
            f"Guía {guia} guardada, pero no encontré la venta "
            f"{datos['documento_referencia']}.",
        )
    return redirect("compras:lista")


@login_required
@requiere_escritura
def importar_compra(request):
    empresa = empresa_actual(request)
    datos = request.session.get("xml_pendiente")
    if not datos:
        messages.info(request, "Primero sube un comprobante.")
        return redirect("compras:importar")

    lineas = datos.get("lineas") or []
    productos = list(Producto.objects.filter(activo=True))
    con_credito = datos["tipo"] == "FACTURA"

    if request.method == "POST":
        elegidos = request.POST.getlist("producto")
        if not lineas:
            messages.error(request, "El comprobante no trae líneas para mapear.")
        elif len(elegidos) != len(lineas) or not all(elegidos):
            messages.error(request, "Elige un producto en cada línea.")
        else:
            proveedor, _ = Tercero.objects.get_or_create(
                tipo_doc="RUC",
                numero_doc=datos["emisor_ruc"],
                defaults={
                    "nombre": datos["emisor_nombre"] or "Proveedor",
                    "rol": "PROVEEDOR",
                },
            )
            compra = Compra.objects.create(creado_por=usuario_actual.get(), 
                empresa=empresa,
                proveedor=proveedor,
                fecha=date.fromisoformat(datos["fecha"]),
                tipo_doc=datos["tipo"],
                serie=datos["serie"],
                numero=datos["numero"],
                glosa=f"{datos['tipo']} {datos['serie']}-{datos['numero']}",
                con_credito=con_credito,
            )

            base_total = sum((Decimal(linea["base"]) for linea in lineas), Decimal("0.00"))
            igv_total = Decimal(datos["igv"])
            acumulado = Decimal("0.00")
            for indice, (linea, producto_id) in enumerate(zip(lineas, elegidos, strict=False)):
                producto = Producto.objects.get(pk=producto_id)
                base = Decimal(linea["base"])
                if indice == len(lineas) - 1:
                    igv = igv_total - acumulado
                else:
                    igv = (
                        (igv_total * base / base_total).quantize(Decimal("0.01"))
                        if base_total
                        else Decimal("0.00")
                    )
                    acumulado += igv
                CompraLinea.objects.create(
                    compra=compra,
                    orden=indice + 1,
                    producto=producto,
                    descripcion=linea["descripcion"][:200],
                    cantidad=Decimal(linea["cantidad"]),
                    precio_unitario=Decimal(linea["valor_unitario"]),
                    base=base,
                    igv=igv,
                    total=base + igv,
                )

            try:
                confirmar(compra)
            except CompraError as exc:
                messages.error(request, f"No se pudo confirmar: {exc}")
            else:
                request.session.pop("xml_pendiente", None)
                messages.success(
                    request,
                    f"Compra registrada: {datos['serie']}-{datos['numero']} "
                    f"por S/ {datos['total']}.",
                )
                return redirect("compras:detalle", compra.pk)

    return render(
        request,
        "compras/importar_compra.html",
        {
            "datos": datos,
            "lineas": lineas,
            "productos": productos,
            "con_credito": con_credito,
        },
    )


@login_required
@requiere_escritura
def pagar_compra(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk)
    cuentas = list(
        CuentaTesoreria.objects.filter(empresa=compra.empresa, activa=True)
    )
    hoy = date.today()

    if request.method == "POST":
        cuenta = CuentaTesoreria.objects.filter(
            pk=request.POST.get("cuenta"), empresa=compra.empresa
        ).first()
        if cuenta is None:
            messages.error(request, "Elige la cuenta de donde sale el dinero.")
        else:
            try:
                pagado, diferencia = pagar(
                    compra,
                    cuenta=cuenta,
                    fecha=date.fromisoformat(
                        request.POST.get("fecha") or hoy.isoformat()
                    ),
                    canal=request.POST.get("canal", "TRANSFERENCIA"),
                    tipo_cambio_pago=request.POST.get("tipo_cambio") or None,
                    importe=request.POST.get("importe") or None,
                )
            except (CompraError, SinTipoCambio) as exc:
                messages.error(request, str(exc))
            else:
                mensaje = f"Pago registrado por S/ {pagado}."
                if diferencia:
                    mensaje += f" Diferencia de cambio: S/ {diferencia}."
                messages.success(request, mensaje)
                return redirect("compras:detalle", compra.pk)

    return render(
        request,
        "compras/pagar.html",
        {
            "compra": compra,
            "cuentas": cuentas,
            "hoy": hoy,
            "saldo": (compra.total + compra.revaluacion) - compra.monto_pagado,
        },
    )


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
@requiere_escritura
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

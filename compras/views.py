"""Pantallas de compras."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import zip_longest
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import CharField, F, Q, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria, Producto, Tercero
from contabilidad.models import Asiento, Cuenta
from contabilidad.moneda import SinTipoCambio, a_soles
from contabilidad.servicios import ContabilidadError
from core.context import empresa_actual
from core.contexto import usuario_actual
from core.filtros import periodo_mes
from core.lineas_documento import calcular as calcular_linea_validada
from core.lineas_documento import dinero, numero_id
from core.models import Empresa, HistorialDocumento, Periodo
from core.permisos import requiere_escritura
from documentos.xml_cpe import Guia, XMLInvalido, leer
from inventario.servicios import StockError
from reportes.casillas import casillas_documento
from tesoreria.models import MovimientoTesoreria
from ventas.models import Venta
from ventas.models_guia import GuiaRemision

from .anotacion import AnotacionError, cambiar_fecha_anotacion
from .forms import CabeceraCompraForm, GastoPagadoForm, ImportarGastoForm, ProvisionGastoForm
from .models import Compra, CompraLinea, CostoAdicional
from .models_gasto import Gasto
from .provisiones import registrar_provision
from .reversion import revertir_registro
from .servicios import CompraError, confirmar, pagar, registrar_gasto, validar_comprobante


@login_required
def lista(request):
    empresa = empresa_actual(request)
    compras = Compra.objects.filter(empresa=empresa) if empresa else Compra.objects.none()
    gastos = Gasto.objects.filter(empresa=empresa) if empresa else Gasto.objects.none()
    criterio_fecha = request.GET.get("fecha_por", "emision")
    if criterio_fecha not in {"emision", "devengo", "anotacion"}:
        criterio_fecha = "emision"
    fecha_compra = Coalesce("fecha_anotacion", "fecha") if criterio_fecha == "anotacion" else F("fecha")
    fecha_gasto = (
        Coalesce("fecha_anotacion", "fecha") if criterio_fecha == "anotacion"
        else Coalesce("fecha_devengado", "fecha") if criterio_fecha == "devengo"
        else F("fecha")
    )
    compras = compras.annotate(fecha_listado=fecha_compra)
    gastos = gastos.annotate(fecha_listado=fecha_gasto)
    error_filtro = None
    try:
        periodo = periodo_mes(request.GET.get("periodo", ""))
    except ValueError as exc:
        error_filtro = str(exc)
        compras, gastos = compras.none(), gastos.none()
    else:
        if periodo:
            compras = compras.filter(fecha_listado__year=periodo.year, fecha_listado__month=periodo.month)
            gastos = gastos.filter(fecha_listado__year=periodo.year, fecha_listado__month=periodo.month)

    busqueda = request.GET.get("q", "").strip()
    if busqueda:
        filtro = (
            Q(proveedor__nombre__icontains=busqueda)
            | Q(proveedor__numero_doc__icontains=busqueda)
            | Q(serie__icontains=busqueda)
            | Q(numero__icontains=busqueda)
            | Q(glosa__icontains=busqueda)
        )
        compras = compras.filter(filtro)
        gastos = gastos.filter(filtro)

    tipo = request.GET.get("tipo", "")
    if tipo not in {"compra", "gasto"}:
        tipo = ""

    def indices(queryset, clase):
        return queryset.order_by().annotate(
            registro_id=F("pk"), clase=Value(clase, output_field=CharField())
        ).values("fecha_listado", "registro_id", "clase")

    if tipo == "compra":
        consulta = indices(compras, "compra")
    elif tipo == "gasto":
        consulta = indices(gastos, "gasto")
    else:
        consulta = indices(compras, "compra").union(indices(gastos, "gasto"), all=True)
    pagina = Paginator(
        consulta.order_by("-fecha_listado", "-clase", "-registro_id"), 25
    ).get_page(request.GET.get("page"))
    indices_pagina = list(pagina.object_list)
    ids_compras = [i["registro_id"] for i in indices_pagina if i["clase"] == "compra"]
    ids_gastos = [i["registro_id"] for i in indices_pagina if i["clase"] == "gasto"]
    compras_pagina = {
        c.pk: c for c in compras.filter(pk__in=ids_compras).select_related("proveedor")
    }
    gastos_pagina = {
        g.pk: g for g in gastos.filter(pk__in=ids_gastos).select_related("proveedor")
    }
    pagina.object_list = [
        {
            "clase": i["clase"],
            "fecha": i["fecha_listado"],
            "registro": (compras_pagina if i["clase"] == "compra" else gastos_pagina)[i["registro_id"]],
        }
        for i in indices_pagina
    ]
    return render(
        request,
        "compras/lista.html",
        {"compras": pagina, "page_obj": pagina, "q": busqueda, "tipo": tipo,
         "fecha_por": criterio_fecha, "error_filtro": error_filtro},
    )


@login_required
@requiere_escritura
@require_POST
def anotacion(request, clase: str, pk: int):
    empresa = empresa_actual(request)
    if clase not in {"compra", "gasto"} or empresa is None:
        messages.error(request, "No se pudo identificar el documento o la empresa.")
        return redirect("compras:lista")
    get_object_or_404(Compra if clase == "compra" else Gasto, pk=pk, empresa=empresa)
    destino = "compras:detalle" if clase == "compra" else "compras:detalle_gasto"
    try:
        texto = request.POST.get("fecha_anotacion", "").strip()
        fecha = date.fromisoformat(texto) if texto else None
        cambiar_fecha_anotacion(empresa=empresa, clase=clase, pk=pk, fecha=fecha, usuario=request.user)
    except (ValueError, AnotacionError) as exc:
        messages.error(request, str(exc) if isinstance(exc, AnotacionError) else "Revisa la fecha de anotación.")
    else:
        messages.success(request, "Período de anotación actualizado; revisa la comparación con el RCE.")
    return redirect(destino, pk=pk)


@login_required
@requiere_escritura
def nueva_provision(request):
    empresa = empresa_actual(request)
    if empresa is None:
        messages.error(request, "Primero configura una empresa.")
        return redirect("core:panel")
    formulario = ProvisionGastoForm(
        request.POST if request.method == "POST" else None,
        initial={"fecha": date.today(), "operacion": uuid4()},
    )
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data.copy()
        datos.pop("confirmado")
        try:
            gasto, creado = registrar_provision(empresa=empresa, usuario=request.user, **datos)
        except (CompraError, ContabilidadError) as exc:
            formulario.add_error(None, str(exc))
        else:
            mensaje = "Gasto devengado registrado." if creado else "Esta operación ya estaba registrada."
            messages.success(request, mensaje)
            return redirect("compras:detalle_gasto", gasto.pk)
    return render(request, "compras/nueva_provision.html", {"formulario": formulario})


@login_required
@requiere_escritura
def nuevo_gasto(request):
    empresa = empresa_actual(request)
    if empresa is None:
        messages.error(request, "Primero configura una empresa.")
        return redirect("core:panel")
    formulario = GastoPagadoForm(
        request.POST or None, empresa=empresa, initial={"fecha": date.today(), "igv": 0}
    )
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            with transaction.atomic():
                gasto = registrar_gasto(
                    empresa=empresa, proveedor=datos["proveedor"], fecha=datos["fecha"],
                    tipo_doc=datos["tipo_doc"], serie=datos["serie"].strip().upper(),
                    numero=datos["numero"].strip(), base=datos["base"], igv=datos["igv"],
                    total=datos["base"] + datos["igv"], cuenta=datos["cuenta"],
                    medio=datos["medio"], glosa=datos["glosa"],
                    con_credito=datos["con_credito"], deducible=datos["deducible"],
                    provisiones_ids=[p.pk for p in datos["provisiones"]],
                )
                HistorialDocumento.objects.create(
                    empresa=empresa, tipo=HistorialDocumento.Tipo.GASTO, documento_id=gasto.pk,
                    usuario=request.user, accion="REGISTRO", detalle="Gasto pagado registrado manualmente.",
                )
        except (CompraError, ContabilidadError) as exc:
            formulario.add_error(None, str(exc))
        except IntegrityError:
            formulario.add_error(None, "El comprobante ya está registrado. Revisa los datos del proveedor.")
        else:
            messages.success(request, "Gasto pagado registrado con su asiento y movimiento de tesorería.")
            return redirect("compras:detalle_gasto", gasto.pk)
    return render(request, "compras/nuevo_gasto.html", {"formulario": formulario})


@login_required
def detalle_gasto(request, pk: int):
    empresa = empresa_actual(request)
    gasto = get_object_or_404(
        Gasto.objects.select_related("proveedor", "cuenta", "medio", "gasto_origen"),
        pk=pk, empresa=empresa,
    )
    asientos = Asiento.objects.filter(
        empresa=empresa, origen_tipo="GASTO", origen_id=gasto.pk
    ).prefetch_related("lineas__cuenta")
    movimientos = MovimientoTesoreria.objects.filter(
        empresa=empresa, origen_tipo="GASTO", origen_id=gasto.pk
    ).select_related("cuenta")
    historial = HistorialDocumento.objects.filter(
        empresa=empresa, tipo="GASTO", documento_id=gasto.pk
    ).order_by("-fecha")[:10]
    provisiones = gasto.provisiones.filter(empresa=empresa).select_related("proveedor")
    return render(request, "compras/detalle_gasto.html", {
        "gasto": gasto, "asientos": asientos, "movimientos": movimientos,
        "historial": historial, "provisiones": provisiones,
    })


@login_required
@requiere_escritura
@transaction.atomic
def nueva(request):
    empresa = empresa_actual(request)
    if empresa is None:
        messages.error(request, "Primero configura una empresa.")
        return redirect("core:panel")

    compra_edit = None
    editar_id = request.GET.get("editar") or request.POST.get("compra_id")
    if editar_id:
        compra_edit = get_object_or_404(Compra.objects.select_for_update(), pk=editar_id, empresa=empresa)
        if compra_edit.estado not in (Compra.Estado.BORRADOR, Compra.Estado.PENDIENTE):
            messages.error(
                request, "Solo se edita una compra en borrador o pendiente."
            )
            return redirect("compras:detalle", compra_edit.pk)

    productos = list(Producto.objects.filter(activo=True))
    proveedores = list(
        Tercero.objects.filter(rol__in=["PROVEEDOR", "AMBOS"], activo=True)
    )
    hoy = date.today()

    contexto = {
        "productos": productos,
        "proveedores": proveedores,
        "hoy": hoy,
        "con_igv": False,
        "filas": [{} for _ in range(4)],
        "costos": [{} for _ in range(2)],
        "compra": compra_edit,
        "cabecera": {
            "fecha": hoy.isoformat(),
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "",
            "proveedor": "",
            "glosa": "",
            "factura_pendiente": False,
        },
    }

    if compra_edit is not None:
        filas_edit = [
            {
                "seleccionado": linea.producto_id,
                "cantidad": linea.cantidad,
                "precio": linea.precio_unitario,
                "descripcion": linea.descripcion,
            }
            for linea in compra_edit.lineas.all()
        ]
        costos_edit = [
            {
                "concepto": costo.concepto,
                "base": costo.base,
                "igv": costo.igv,
            }
            for costo in compra_edit.costos.all()
        ]
        contexto["filas"] = filas_edit or contexto["filas"]
        contexto["costos"] = costos_edit or contexto["costos"]
        primera = compra_edit.lineas.first()
        if primera and primera.cantidad:
            contexto["con_igv"] = (
                abs(primera.precio_unitario * primera.cantidad - primera.total)
                < Decimal("0.01")
            )
        contexto["cabecera"] = {
            "fecha": compra_edit.fecha.isoformat(),
            "tipo_doc": compra_edit.tipo_doc,
            "serie": compra_edit.serie,
            "numero": compra_edit.numero,
            "proveedor": compra_edit.proveedor_id,
            "glosa": compra_edit.glosa,
            "factura_pendiente": compra_edit.estado == Compra.Estado.PENDIENTE,
        }

    if request.method != "POST":
        return render(request, "compras/nueva.html", contexto)

    errores: list[str] = []

    proveedor = None
    proveedor_id = request.POST.get("proveedor") or ""
    if proveedor_id:
        try:
            proveedor = Tercero.objects.filter(
                pk=numero_id(proveedor_id), rol__in=["PROVEEDOR", "AMBOS"], activo=True
            ).first()
        except ValueError:
            proveedor = None
        if proveedor is None:
            errores.append("Selecciona un proveedor activo válido.")
    else:
        nombre = request.POST.get("proveedor_nombre", "").strip()
        ruc = request.POST.get("proveedor_ruc", "").strip()
        if not (nombre and len(ruc) == 11 and ruc.isascii() and ruc.isdecimal()):
            errores.append("Elige un proveedor o escribe nombre y RUC de 11 dígitos.")

    filas: list[dict] = []
    productos_ids = request.POST.getlist("linea_producto")
    cantidades = request.POST.getlist("linea_cantidad")
    precios = request.POST.getlist("linea_precio")
    descripciones = request.POST.getlist("linea_descripcion")
    con_igv = bool(request.POST.get("con_igv"))
    if len({len(productos_ids), len(cantidades), len(precios)}) != 1:
        errores.append("Las líneas están incompletas; revisa los productos, cantidades y precios.")
    if any(descripcion.strip() for descripcion in descripciones[len(productos_ids):]):
        errores.append("Hay descripciones sin una línea de producto.")

    for indice, (producto_id, cantidad_txt, precio_txt) in enumerate(
        zip_longest(productos_ids, cantidades, precios, fillvalue=""), start=1
    ):
        descripcion = descripciones[indice - 1] if indice <= len(descripciones) else ""
        if not producto_id and not cantidad_txt and not precio_txt and not descripcion.strip():
            continue
        fila = {
            "producto_id": producto_id,
            "seleccionado": producto_id,
            "cantidad": cantidad_txt,
            "precio": precio_txt,
            "descripcion": descripcion,
        }
        try:
            producto = Producto.objects.get(pk=numero_id(producto_id), activo=True)
            cantidad, precio, base, igv, total = calcular_linea_validada(cantidad_txt, precio_txt, con_igv)
        except (ValueError, TypeError, InvalidOperation, Producto.DoesNotExist):
            errores.append(f"Línea {indice}: revisa producto, cantidad y precio.")
            filas.append(fila)
            continue
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
    if len({len(conceptos), len(bases), len(igvs)}) != 1:
        errores.append("Las filas de costos adicionales están incompletas.")
    for concepto, base_txt, igv_txt in zip_longest(conceptos, bases, igvs, fillvalue=""):
        if not concepto.strip() and not base_txt and not igv_txt:
            continue
        try:
            base = dinero(base_txt)
            igv = dinero(igv_txt)
            if not concepto.strip() or base <= 0 or base + igv >= Decimal("10000000000000000"):
                raise ValueError
        except ValueError:
            errores.append(f"Costo «{concepto}»: importes inválidos.")
            costos.append({"concepto": concepto, "base": base_txt, "igv": igv_txt})
            continue
        costos.append(
            {"concepto": concepto, "base": base, "igv": igv, "total": base + igv}
        )

    if not errores and (
        sum((f["total"] for f in filas), Decimal("0")) + sum((c["total"] for c in costos), Decimal("0"))
        >= Decimal("10000000000000000")
    ):
        errores.append("El total de la compra excede el importe permitido.")

    contexto.update(
        {
            "filas": filas,
            "costos": costos,
            "errores": errores,
            "con_igv": con_igv,
            "compra": compra_edit,
            "cabecera": {
                "fecha": request.POST.get("fecha", hoy.isoformat()),
                "tipo_doc": request.POST.get("tipo_doc", "FACTURA"),
                "serie": request.POST.get("serie", "F001"),
                "numero": request.POST.get("numero", ""),
                "proveedor": proveedor_id,
                "proveedor_ruc": request.POST.get("proveedor_ruc", ""),
                "proveedor_nombre": request.POST.get("proveedor_nombre", ""),
                "glosa": request.POST.get("glosa", ""),
                "factura_pendiente": bool(request.POST.get("factura_pendiente")),
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
    factura_pendiente = bool(request.POST.get("factura_pendiente"))
    if proveedor is None:
        proveedor, _ = Tercero.objects.get_or_create(
            tipo_doc="RUC", numero_doc=datos["proveedor_ruc"],
            defaults={"nombre": datos["proveedor_nombre"], "rol": "PROVEEDOR"},
        )
        if not proveedor.activo or proveedor.rol not in ("PROVEEDOR", "AMBOS"):
            errores.append("El RUC ya pertenece a un tercero que no está activo como proveedor.")
            return render(request, "compras/nueva.html", contexto)

    if compra_edit is None:
        compra = Compra(empresa=empresa, creado_por=usuario_actual.get())
    else:
        compra = compra_edit
        compra.lineas.all().delete()
        compra.costos.all().delete()

    compra.proveedor = proveedor
    compra.fecha = datos["fecha"]
    compra.tipo_doc = datos["tipo_doc"]
    compra.serie = datos["serie"].upper()[:4]
    compra.numero = datos["numero"][:20]
    compra.glosa = datos.get("glosa", "")[:255]
    compra.con_credito = datos["tipo_doc"] == Compra.TipoDoc.FACTURA
    compra.estado = (
        Compra.Estado.PENDIENTE if factura_pendiente else Compra.Estado.BORRADOR
    )
    compra.modificado_por = usuario_actual.get()
    compra.modificado_en = timezone.now()
    compra.save()

    for orden, fila in enumerate(filas, start=1):
        CompraLinea.objects.create(
            compra=compra,
            orden=orden,
            producto=fila["producto"],
            descripcion=fila.get("descripcion", "")[:200],
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

    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo="COMPRA",
        documento_id=compra.pk,
        usuario=usuario_actual.get(),
        accion="EDICION" if compra_edit else "CREACION",
        detalle=f"{compra.serie}-{compra.numero} · total {compra.total}",
    )
    messages.success(
        request,
        (
            "Compra actualizada."
            if compra_edit
            else "Compra registrada. Completa la factura antes de confirmar."
            if factura_pendiente
            else "Borrador creado. Revísalo y confírmalo."
        ),
    )
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
                        "empresa_id": empresa.pk if empresa else None,
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
                    if documento.tipo not in {"FACTURA", "BOLETA"}:
                        raise XMLInvalido(
                            "Este flujo solo registra facturas y boletas; las notas requieren otro tratamiento."
                        )
                    if not empresa or documento.receptor_ruc != empresa.ruc:
                        raise XMLInvalido("El receptor del XML no coincide con el RUC de la empresa seleccionada.")
                    if len(documento.emisor_ruc) != 11 or not documento.emisor_ruc.isdigit():
                        raise XMLInvalido("El XML no contiene un RUC de emisor válido.")
                    if (not documento.serie or not documento.numero or documento.total <= 0
                            or documento.base < 0 or documento.igv < 0):
                        raise XMLInvalido("El XML necesita serie, número e importe total válido.")
                    if documento.base + documento.igv != documento.total:
                        raise XMLInvalido(
                            "El comprobante contiene importes adicionales o ajustes que requieren revisión."
                        )
                    total_soles, tipo_cambio = a_soles(
                        documento.total, documento.moneda, documento.fecha, lado="venta"
                    )
                    igv_soles, _ = a_soles(
                        documento.igv, documento.moneda, documento.fecha, lado="venta"
                    )
                except (SinTipoCambio, XMLInvalido) as exc:
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
                    "receptor_ruc": documento.receptor_ruc,
                    "empresa_id": empresa.pk,
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
    if not empresa or datos.get("empresa_id") != empresa.pk or datos.get("receptor_ruc") != empresa.ruc:
        messages.error(request, "El comprobante no corresponde a la empresa seleccionada. Vuelve a subir el XML.")
        return redirect("compras:importar")

    sugerida = _cuenta_sugerida(datos["emisor_nombre"])
    formulario = ImportarGastoForm(
        request.POST or None, empresa=empresa, tipo=datos["tipo"], initial={"cuenta": sugerida},
    )

    if request.method == "POST" and formulario.is_valid():
        if datos.get("moneda_original", datos.get("moneda")) != "PEN":
            formulario.add_error(None, "El registro de gastos en moneda extranjera aún no está disponible.")
        else:
            try:
                with transaction.atomic():
                    proveedor, _ = Tercero.objects.get_or_create(
                        tipo_doc="RUC", numero_doc=datos["emisor_ruc"],
                        defaults={"nombre": datos["emisor_nombre"] or "Proveedor", "rol": "PROVEEDOR"},
                    )
                    gasto = registrar_gasto(
                        empresa=empresa,
                        proveedor=proveedor,
                        fecha=date.fromisoformat(datos["fecha"]),
                        tipo_doc=datos["tipo"],
                        serie=datos["serie"],
                        numero=datos["numero"],
                        base=Decimal(datos["base"]),
                        igv=Decimal(datos["igv"]),
                        total=Decimal(datos["total"]),
                        cuenta=formulario.cleaned_data["cuenta"],
                        medio=formulario.cleaned_data["medio"],
                        glosa=f"{datos['tipo']} {datos['serie']}-{datos['numero']}",
                        con_credito=formulario.cleaned_data["con_credito"],
                        deducible=formulario.cleaned_data["deducible"],
                    )
                    HistorialDocumento.objects.create(
                        empresa=empresa, tipo=HistorialDocumento.Tipo.GASTO, documento_id=gasto.pk,
                        usuario=request.user, accion="REGISTRO", detalle="Gasto pagado registrado desde XML.",
                    )
            except (CompraError, ContabilidadError, IntegrityError) as exc:
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
        {"datos": datos, "formulario": formulario},
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
    if not empresa or datos.get("empresa_id") != empresa.pk:
        messages.error(request, "La guía no corresponde a la empresa seleccionada. Vuelve a subir el XML.")
        return redirect("compras:importar")

    venta = None
    if datos.get("venta_id"):
        venta = Venta.objects.filter(pk=datos["venta_id"], empresa=empresa).first()

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
    if not empresa or datos.get("empresa_id") != empresa.pk or datos.get("receptor_ruc") != empresa.ruc:
        messages.error(request, "El comprobante no corresponde a la empresa seleccionada. Vuelve a subir el XML.")
        return redirect("compras:importar")

    if datos.get("moneda_original", datos.get("moneda")) != "PEN":
        messages.error(
            request,
            "La importación de mercadería en moneda extranjera aún no está disponible: requiere validar sus costos.",
        )
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
            try:
                with transaction.atomic():
                    proveedor, _ = Tercero.objects.get_or_create(
                        tipo_doc="RUC",
                        numero_doc=datos["emisor_ruc"],
                        defaults={
                            "nombre": datos["emisor_nombre"] or "Proveedor",
                            "rol": "PROVEEDOR",
                        },
                    )
                    compra = Compra.objects.create(
                        creado_por=usuario_actual.get(), empresa=empresa, proveedor=proveedor,
                        fecha=date.fromisoformat(datos["fecha"]), tipo_doc=datos["tipo"],
                        serie=datos["serie"], numero=datos["numero"],
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
                                if base_total else Decimal("0.00")
                            )
                            acumulado += igv
                        CompraLinea.objects.create(
                            compra=compra, orden=indice + 1, producto=producto,
                            descripcion=linea["descripcion"][:200], cantidad=Decimal(linea["cantidad"]),
                            precio_unitario=Decimal(linea["valor_unitario"]), base=base,
                            igv=igv, total=base + igv,
                        )
                    confirmar(compra)
            except (CompraError, StockError) as exc:
                messages.error(request, f"No se pudo confirmar: {exc}")
            except (Producto.DoesNotExist, ValueError):
                messages.error(request, "Revisa los productos y los datos del comprobante antes de continuar.")
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
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa_actual(request))
    cuentas = list(
        CuentaTesoreria.objects.filter(empresa=compra.empresa, activa=True, moneda="PEN", cuenta_contable__isnull=False)
    )
    hoy = date.today()

    if request.method == "POST":
        cuenta = CuentaTesoreria.objects.filter(
            pk=request.POST.get("cuenta"), empresa=compra.empresa, activa=True,
            moneda="PEN", cuenta_contable__isnull=False,
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
            except (CompraError, SinTipoCambio, ContabilidadError, ValueError) as exc:
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
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa_actual(request))
    asiento = Asiento.objects.filter(
        origen_tipo="COMPRA", origen_id=compra.pk, tipo_operacion="COMPRA"
    ).first()
    return render(
        request,
        "compras/detalle.html",
        {
            "compra": compra,
            "asiento": asiento,
            "casillas_621": casillas_documento(compra),
            "historial": HistorialDocumento.objects.filter(
                empresa=compra.empresa, tipo="COMPRA", documento_id=compra.pk
            ).order_by("-fecha")[:10],
        },
    )


@login_required
@requiere_escritura
@require_POST
def confirmar_compra(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa_actual(request))
    try:
        confirmar(compra)
    except (CompraError, StockError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Compra confirmada: stock y asiento generados.")
    return redirect("compras:detalle", compra.pk)


@login_required
@requiere_escritura
@transaction.atomic
def corregir(request, pk: int):
    empresa = empresa_actual(request)
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa)
    if compra.estado != Compra.Estado.CONFIRMADA:
        messages.info(request, "Esta compra todavía se puede editar completa.")
        return redirect(f"{reverse('compras:nueva')}?editar={compra.pk}")

    if request.method == "POST":
        compra = get_object_or_404(Compra.objects.select_for_update(), pk=pk, empresa=empresa)
        Empresa.objects.select_for_update().get(pk=empresa.pk)
        fechas = {compra.fecha, compra.fecha_anotacion or compra.fecha}
        periodos = Q()
        for fecha in fechas:
            periodos |= Q(anio=fecha.year, mes=fecha.month)
        asientos = Asiento.objects.filter(
            empresa=empresa, origen_tipo__in=["COMPRA", "COMPRA_PAGO"], origen_id=compra.pk,
            estado=Asiento.Estado.CONFIRMADO,
        )
        periodos |= Q(pk__in=asientos.values("periodo_id"))
        periodos_afectados = Periodo.objects.select_for_update().filter(
            periodos, empresa=empresa,
        ).order_by("pk")
        if any(periodo.estado == Periodo.Estado.CERRADO for periodo in periodos_afectados):
            messages.error(request, "No se pueden corregir datos vinculados a un período cerrado.")
            return redirect("compras:detalle", compra.pk)
        documento_anterior = (compra.tipo_doc, compra.serie, compra.numero)
        compra.glosa = request.POST.get("glosa", "")[:255]
        tipo = request.POST.get("tipo_doc", "")
        if tipo in Compra.TipoDoc.values:
            if (tipo == Compra.TipoDoc.FACTURA) != compra.con_credito:
                messages.error(
                    request,
                    "Cambiar el tipo cambiaría el crédito fiscal. Anula la compra "
                    "y vuelve a registrarla con el tipo correcto.",
                )
                return redirect("compras:detalle", compra.pk)
            compra.tipo_doc = tipo
        if not compra.serie.strip():
            compra.serie = request.POST.get("serie", "").upper()[:4]
        if not compra.numero.strip():
            compra.numero = request.POST.get("numero", "")[:20]
        if (compra.tipo_doc, compra.serie, compra.numero) != documento_anterior:
            try:
                validar_comprobante(
                    empresa=compra.empresa, proveedor=compra.proveedor, tipo_doc=compra.tipo_doc,
                    serie=compra.serie, numero=compra.numero, compra_id=compra.pk,
                )
            except CompraError as exc:
                messages.error(request, str(exc))
                return redirect("compras:detalle", compra.pk)
        compra.modificado_por = usuario_actual.get()
        compra.modificado_en = timezone.now()
        compra.save(
            update_fields=[
                "glosa",
                "tipo_doc",
                "serie",
                "numero",
                "modificado_por",
                "modificado_en",
            ]
        )

        documento = f"{compra.serie}-{compra.numero}".strip(" -")
        Asiento.objects.filter(
            empresa=compra.empresa,
            origen_tipo="COMPRA",
            origen_id=compra.pk,
            tipo_operacion="COMPRA",
            estado=Asiento.Estado.CONFIRMADO,
        ).update(glosa=f"Compra {documento}".strip()[:255])
        Asiento.objects.filter(
            empresa=compra.empresa,
            origen_tipo="COMPRA_PAGO",
            origen_id=compra.pk,
            tipo_operacion="PAGO_PROVEEDOR",
            estado=Asiento.Estado.CONFIRMADO,
        ).update(glosa=f"Pago compra {documento}".strip()[:255])
        MovimientoTesoreria.objects.filter(
            empresa=compra.empresa,
            origen_tipo="COMPRA_PAGO",
            origen_id=compra.pk,
        ).update(concepto=f"Pago compra {documento}".strip()[:200])

        for linea in compra.lineas.all():
            nueva = request.POST.get(f"desc_{linea.pk}")
            if nueva is not None:
                linea.descripcion = nueva[:200]
                linea.save(update_fields=["descripcion"])

        HistorialDocumento.objects.create(
            empresa=compra.empresa,
            tipo="COMPRA",
            documento_id=compra.pk,
            usuario=usuario_actual.get(),
            accion="CORRECCION",
            detalle="Completados datos de factura o descripción",
        )
        messages.success(request, "Datos de la compra actualizados.")
        return redirect("compras:detalle", compra.pk)

    return render(request, "compras/corregir.html", {"compra": compra})


@login_required
@requiere_escritura
@require_POST
def anular(request, pk: int):
    compra = get_object_or_404(Compra, pk=pk, empresa=empresa_actual(request))
    if request.POST.get("confirmo_error") != "on":
        messages.error(request, "Confirma que se trata de un registro interno erróneo, no de una devolución.")
        return redirect("compras:detalle", compra.pk)
    try:
        revertir_registro(empresa=compra.empresa, compra_id=compra.pk, motivo=request.POST.get("motivo", ""),
                          usuario=request.user)
    except (CompraError, ContabilidadError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Registro revertido con asiento inverso e historial. Revisa el RCE correspondiente.")
    return redirect("compras:detalle", compra.pk)

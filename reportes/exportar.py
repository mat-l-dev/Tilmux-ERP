"""Exportación de los registros para el SIRE.

Se generan columnas con nombres legibles en lugar de posiciones fijas, para que
puedas mapearlas a la plantilla vigente sin adivinar. Los importes van como
texto decimal con punto, sin separador de miles.
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font

from compras.comprobantes import evaluar_tributacion
from compras.models import Compra
from compras.models_gasto import Gasto
from core.context import empresa_actual
from ventas.models import NotaCredito, NotaDebito, Venta

from .clientes import nombre_cliente, tipo_identidad_cliente
from .eeff import construir
from .pdf_eeff import generar as generar_pdf
from .utils import filtros_seguros, rango

CAMPOS_VENTAS = [
    "periodo",
    "fecha",
    "tipo_documento",
    "serie",
    "numero",
    "documento_modificado",
    "tipo_doc_cliente",
    "numero_doc_cliente",
    "cliente",
    "base_imponible",
    "igv",
    "total",
    "moneda",
]

TIPO_SUNAT_COMPRA = {"FACTURA": "01", "BOLETA": "03", "OTRO": "00"}

CAMPOS_COMPRAS = [
    "periodo",
    "fecha",
    "tipo_documento",
    "serie",
    "numero",
    "ruc_proveedor",
    "proveedor",
    "base_imponible",
    "igv",
    "no_gravado",
    "total",
    "clase",
    "credito",
    "pendiente",
]


def _csv(nombre: str, cabecera: list[str], filas: list[list]) -> HttpResponse:
    respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    respuesta.write("\ufeff")
    escritor = csv.writer(respuesta)
    escritor.writerow(cabecera)
    escritor.writerows(filas)
    return respuesta


def _periodo(fecha: date) -> str:
    return f"{fecha.year}{fecha.month:02d}00"


def _importe(valor) -> str:
    return f"{Decimal(valor or 0):.2f}"


@login_required
@filtros_seguros
def ventas(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[list] = []

    if empresa:
        for venta in Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).select_related("cliente").order_by("fecha", "serie", "numero"):
            filas.append(
                [
                    _periodo(venta.fecha),
                    venta.fecha.isoformat(),
                    "01" if venta.tipo_doc == "FACTURA" else "03",
                    venta.serie,
                    venta.numero,
                    "",
                    tipo_identidad_cliente(venta),
                    venta.cliente.numero_doc if venta.cliente else "",
                    nombre_cliente(venta),
                    _importe(venta.subtotal),
                    _importe(venta.igv),
                    _importe(venta.total),
                    venta.moneda,
                ]
            )

        for nota in NotaCredito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta", "venta__cliente"):
            venta = nota.venta
            filas.append(
                [
                    _periodo(nota.fecha),
                    nota.fecha.isoformat(),
                    "07",
                    nota.serie,
                    nota.numero,
                    f"{venta.serie}-{venta.numero}",
                    tipo_identidad_cliente(venta),
                    venta.cliente.numero_doc if venta.cliente else "",
                    nombre_cliente(venta),
                    _importe(-nota.base),
                    _importe(-nota.igv),
                    _importe(-nota.total),
                    venta.moneda,
                ]
            )

        for nota in NotaDebito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("venta", "venta__cliente"):
            venta = nota.venta
            filas.append(
                [
                    _periodo(nota.fecha),
                    nota.fecha.isoformat(),
                    "08",
                    nota.serie,
                    nota.numero,
                    f"{venta.serie}-{venta.numero}",
                    tipo_identidad_cliente(venta),
                    venta.cliente.numero_doc if venta.cliente else "",
                    nombre_cliente(venta),
                    _importe(nota.base),
                    _importe(nota.igv),
                    _importe(nota.total),
                    venta.moneda,
                ]
            )

    filas.sort(key=lambda f: (f[1], f[3], f[4]))
    return _csv(
        f"registro-ventas-{desde:%Y%m}-{hasta:%Y%m}.csv", CAMPOS_VENTAS, filas
    )


@login_required
@filtros_seguros
def compras(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[list] = []

    if empresa:
        for compra in Compra.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha_tributaria__range=(desde, hasta),
        ).select_related("proveedor").order_by("fecha", "serie", "numero"):
            estado_tributario = evaluar_tributacion(compra)
            usa_credito = estado_tributario.incluido
            filas.append(
                [
                    _periodo(compra.fecha_anotacion or compra.fecha),
                    compra.fecha.isoformat(),
                    TIPO_SUNAT_COMPRA.get(compra.tipo_doc, "00"),
                    compra.serie,
                    compra.numero,
                    compra.proveedor.numero_doc,
                    compra.proveedor.nombre,
                    _importe(compra.subtotal if usa_credito and compra.igv > 0 else 0),
                    _importe(compra.igv if usa_credito else 0),
                    _importe(
                        compra.subtotal
                        if usa_credito and compra.igv == 0
                        else 0
                    ),
                    _importe(compra.total),
                    "Mercadería",
                    "Sí" if usa_credito else "No",
                    "Sí" if estado_tributario.requiere_revision else "No",
                ]
            )

        for gasto in Gasto.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
            empresa=empresa,
            fecha_tributaria__range=(desde, hasta),
            provision=False,
        ).exclude(estado=Gasto.Estado.ANULADO).select_related("proveedor").order_by("fecha", "serie", "numero"):
            estado_tributario = evaluar_tributacion(gasto)
            usa_credito = estado_tributario.incluido
            filas.append(
                [
                    _periodo(gasto.fecha_anotacion or gasto.fecha),
                    gasto.fecha.isoformat(),
                    "01" if gasto.tipo_doc == "FACTURA" else ("03" if gasto.tipo_doc == "BOLETA" else "00"),
                    gasto.serie,
                    gasto.numero,
                    gasto.proveedor.numero_doc,
                    gasto.proveedor.nombre,
                    _importe(gasto.base if usa_credito and gasto.igv > 0 else 0),
                    _importe(gasto.igv if usa_credito and gasto.igv > 0 else 0),
                    _importe(gasto.base if usa_credito and gasto.igv == 0 else 0),
                    _importe(gasto.total),
                    "Gasto",
                    "Sí" if usa_credito else "No",
                    "Sí" if estado_tributario.requiere_revision else "No",
                ]
            )

    filas.sort(key=lambda f: (f[1], f[3], f[4]))
    return _csv(
        f"registro-compras-{desde:%Y%m}-{hasta:%Y%m}.csv", CAMPOS_COMPRAS, filas
    )


def _hoja(libro, titulo, filas, subtotales=(), totales=()):
    hoja = libro.create_sheet(titulo)
    hoja.column_dimensions["A"].width = 46
    hoja.column_dimensions["B"].width = 16
    for indice, (concepto, importe) in enumerate(filas, start=1):
        hoja.cell(row=indice, column=1, value=concepto)
        celda = hoja.cell(row=indice, column=2, value=float(importe))
        celda.number_format = "#,##0.00"
        if concepto in subtotales:
            hoja.cell(row=indice, column=1).font = Font(bold=True)
            celda.font = Font(bold=True)
        if concepto in totales:
            hoja.cell(row=indice, column=1).font = Font(bold=True, size=12)
            celda.font = Font(bold=True, size=12)
    return hoja


@login_required
@filtros_seguros
def eeff_excel(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    datos = construir(empresa, desde, hasta)

    libro = Workbook()
    libro.remove(libro.active)

    situacion = [(a["codigo"] + " " + a["nombre"], a["importe"]) for a in datos["activo_corriente"]]
    situacion.append(("Total activo corriente", datos["total_activo_corriente"]))
    situacion += [(a["codigo"] + " " + a["nombre"], a["importe"]) for a in datos["activo_no_corriente"]]
    situacion.append(("Total activo", datos["total_activo"]))
    situacion += [(p["codigo"] + " " + p["nombre"], p["importe"]) for p in datos["pasivo"]]
    situacion.append(("Total pasivo", datos["total_pasivo"]))
    situacion += [(p["codigo"] + " " + p["nombre"], p["importe"]) for p in datos["patrimonio"]]
    situacion.append(("Resultado acumulado", datos["resultado_acumulado"]))
    situacion.append(("Total pasivo y patrimonio", datos["total_pasivo_patrimonio"]))
    _hoja(
        libro,
        "Situación",
        situacion,
        subtotales={"Total activo corriente", "Total pasivo"},
        totales={"Total activo", "Total pasivo y patrimonio"},
    )

    resultados = [
        ("Ingresos por ventas", datos["ingresos_ventas"]),
        ("Costo de ventas", -datos["costo_ventas"]),
        ("Gastos de operación", -datos["gastos_operativos"]),
        ("Otros ingresos operativos", datos["otros_ingresos"]),
        ("Resultado de operación", datos["resultado_operacion"]),
        ("Ingresos financieros", datos["ingresos_financieros"]),
        ("Gastos financieros", -datos["gastos_financieros"]),
        ("Resultado antes de impuesto", datos["resultado_antes_impuesto"]),
        ("Impuesto a las ganancias", -datos["gasto_impuesto"]),
        ("Resultado del periodo", datos["resultado_neto"]),
    ]
    _hoja(
        libro,
        "Resultados",
        resultados,
        subtotales={"Resultado de operación"},
        totales={"Resultado del periodo"},
    )

    _hoja(libro, "Cambios", [(c["concepto"], c["importe"]) for c in datos["cambios"]], totales={"Saldo al cierre"})
    _hoja(libro, "Flujo", [(f["concepto"], f["importe"]) for f in datos["flujo"]], totales={"Efectivo al cierre"})

    respuesta = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    respuesta["Content-Disposition"] = f'attachment; filename="eeff-{hasta:%Y%m%d}.xlsx"'
    libro.save(respuesta)
    return respuesta


@login_required
@filtros_seguros
def eeff_pdf(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    datos = construir(empresa, desde, hasta)
    respuesta = HttpResponse(generar_pdf(datos, empresa), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="eeff-{hasta:%Y%m%d}.pdf"'
    return respuesta

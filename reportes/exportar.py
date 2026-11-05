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
from django.http import HttpResponse

from compras.models import Compra
from compras.models_gasto import Gasto
from core.context import empresa_actual
from ventas.models import NotaCredito, NotaDebito, Venta

from .utils import rango

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
def ventas(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[list] = []

    if empresa:
        for venta in Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).order_by("fecha", "serie", "numero"):
            filas.append(
                [
                    _periodo(venta.fecha),
                    venta.fecha.isoformat(),
                    "01" if venta.tipo_doc == "FACTURA" else "03",
                    venta.serie,
                    venta.numero,
                    "",
                    "06" if venta.cliente and venta.cliente.tipo_doc == "RUC" else "01",
                    venta.cliente.numero_doc if venta.cliente else "",
                    venta.cliente_nombre or "Consumidor final",
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
                    "06" if venta.cliente and venta.cliente.tipo_doc == "RUC" else "01",
                    venta.cliente.numero_doc if venta.cliente else "",
                    venta.cliente_nombre or "Consumidor final",
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
                    "06" if venta.cliente and venta.cliente.tipo_doc == "RUC" else "01",
                    venta.cliente.numero_doc if venta.cliente else "",
                    venta.cliente_nombre or "Consumidor final",
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
def compras(request):
    empresa = empresa_actual(request)
    desde, hasta = rango(request)
    filas: list[list] = []

    if empresa:
        for compra in Compra.objects.filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            fecha__range=(desde, hasta),
        ).select_related("proveedor").order_by("fecha", "serie", "numero"):
            filas.append(
                [
                    _periodo(compra.fecha),
                    compra.fecha.isoformat(),
                    "01" if compra.tipo_doc == "FACTURA" else "03",
                    compra.serie,
                    compra.numero,
                    compra.proveedor.numero_doc,
                    compra.proveedor.nombre,
                    _importe(compra.subtotal),
                    _importe(compra.igv),
                    "0.00",
                    _importe(compra.total),
                    "Mercadería",
                ]
            )

        for gasto in Gasto.objects.filter(
            empresa=empresa, fecha__range=(desde, hasta)
        ).select_related("proveedor").order_by("fecha", "serie", "numero"):
            filas.append(
                [
                    _periodo(gasto.fecha),
                    gasto.fecha.isoformat(),
                    "01" if gasto.tipo_doc == "FACTURA" else ("03" if gasto.tipo_doc == "BOLETA" else "00"),
                    gasto.serie,
                    gasto.numero,
                    gasto.proveedor.numero_doc,
                    gasto.proveedor.nombre,
                    _importe(gasto.base if gasto.igv > 0 else 0),
                    _importe(gasto.igv),
                    _importe(gasto.base if gasto.igv == 0 else 0),
                    _importe(gasto.total),
                    "Gasto",
                ]
            )

    filas.sort(key=lambda f: (f[1], f[3], f[4]))
    return _csv(
        f"registro-compras-{desde:%Y%m}-{hasta:%Y%m}.csv", CAMPOS_COMPRAS, filas
    )

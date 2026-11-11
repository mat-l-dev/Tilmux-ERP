"""Vencimientos tributarios de octubre 2026 y dependencia de caja.

Solo se muestran las fechas **verificadas** en la auditoría del 10/11/2026 para
el RUC terminado en 1: SIRE el 16/11/2026 y PDT 621 / pago del IGV el
17/11/2026 (cronograma de atraso SIRE, RS 281-2022). Noviembre no está
verificado y este panel no inventa fechas: si se pide otro período, avisa que
no hay fechas sustentadas.

La deuda del IGV es la estimación del libro (`igv_pendiente`). Sin el P0-5 la
constancia todavía no manda; por eso el panel muestra la cifra de libros y
recuerda que la declaración va en enteros (RS 025-2000), sin presentarla como
deuda declarada.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from contabilidad.impuestos import (
    c184_libro,
    igv_pendiente,
    monto_igv_pagado,
    saldo_cuenta,
)
from contabilidad.models import DeclaracionIGV621
from core.models import Empresa
from tesoreria.models import RestitucionSocio

from .estados_sire import resumen_periodo

PERIODO_VERIFICADO = (2026, 10)
FUENTE = "Auditoría consolidada 10/11/2026 y cronograma de atraso SIRE 2026 (RS 281-2022) para RUC terminado en 1."
OBLIGACIONES = (
    {
        "clave": "SIRE",
        "nombre": "SIRE · RCE y RVIE de octubre 2026",
        "detalle": "Registro de compras y de ventas del período 202610.",
        "fecha": date(2026, 11, 16),
    },
    {
        "clave": "PDT",
        "nombre": "PDT 621 · octubre 2026",
        "detalle": "Declaración mensual de IGV y renta RER del período 202610.",
        "fecha": date(2026, 11, 17),
    },
    {
        "clave": "IGV",
        "nombre": "Pago del IGV · octubre 2026",
        "detalle": (
            "S/ 105 en la declaración (redondeo a enteros); 105,38 en libros. "
            "El pago vence aunque el depósito de Mercado Pago no llegue."
        ),
        "fecha": date(2026, 11, 17),
    },
)
CERO = Decimal("0.00")


def _estado_pendiente(fecha: date, hoy: date) -> str:
    if fecha < hoy:
        return "VENCIDO"
    if fecha == hoy:
        return "VENCE HOY"
    return "PENDIENTE"


def _obligacion(*, clave, nombre, detalle, fecha, hoy, cumplido, estado_cumplido, extra=None):
    estado = estado_cumplido if cumplido else _estado_pendiente(fecha, hoy)
    return {
        "clave": clave,
        "nombre": nombre,
        "detalle": detalle,
        "fecha": fecha,
        "dias": (fecha - hoy).days,
        "estado": estado,
        "cumplido": cumplido,
        "tono": "ok" if cumplido else "rojo",
        "extra": extra or {},
    }


def panel_vencimientos(
    empresa: Empresa | None,
    anio: int = 2026,
    mes: int = 10,
    hoy: date | None = None,
) -> dict:
    """Estado de las obligaciones verificadas de octubre 2026."""
    hoy = hoy or date.today()
    datos = {
        "anio": anio,
        "mes": mes,
        "hoy": hoy,
        "fuente": FUENTE,
        "verificado": False,
        "mensaje": "",
        "obligaciones": [],
        "sire": None,
        "pdt": None,
        "igv": None,
        "caja": None,
        "pendientes": 0,
        "vencidos": 0,
        "proximo": None,
    }
    if empresa is None:
        datos["mensaje"] = "Elige una empresa para ver sus vencimientos."
        return datos
    if (anio, mes) != PERIODO_VERIFICADO:
        datos["mensaje"] = (
            "No hay fechas de vencimiento verificadas para este período. "
            "Este panel solo muestra octubre 2026, con las fechas sustentadas "
            "en el cronograma oficial."
        )
        return datos

    datos["verificado"] = True

    sire = resumen_periodo(empresa, anio, mes)
    obligaciones = [
        _obligacion(
            clave="SIRE",
            nombre=OBLIGACIONES[0]["nombre"],
            detalle=OBLIGACIONES[0]["detalle"],
            fecha=OBLIGACIONES[0]["fecha"],
            hoy=hoy,
            cumplido=sire["cerrado"],
            estado_cumplido="GENERADO",
            extra={
                "registros": [
                    {"registro": fila["registro"], "estado": fila["estado"], "cerrado": fila["cerrado"]}
                    for fila in sire["registros"]
                ]
            },
        )
    ]

    declaracion = (
        DeclaracionIGV621.objects.filter(empresa=empresa, anio=anio, mes=mes, anulada=False)
        .order_by("-registrado_en", "-pk")
        .first()
    )
    obligaciones.append(
        _obligacion(
            clave="PDT",
            nombre=OBLIGACIONES[1]["nombre"],
            detalle=OBLIGACIONES[1]["detalle"],
            fecha=OBLIGACIONES[1]["fecha"],
            hoy=hoy,
            cumplido=declaracion is not None,
            estado_cumplido="DECLARADO",
            extra={
                "registro_manual": declaracion is not None,
                "casilla_184": declaracion.casilla_184 if declaracion else None,
                "numero_orden": declaracion.numero_orden if declaracion else "",
            },
        )
    )

    pendiente = igv_pendiente(empresa, anio, mes)
    pagado = monto_igv_pagado(empresa, anio, mes)
    libro = c184_libro(empresa, anio, mes)
    deuda_libros = libro if libro > CERO else CERO
    saldo_favor_libros = -libro if libro < CERO else CERO
    if deuda_libros <= CERO:
        cumplido_igv, estado_igv = True, "SIN DEUDA"
    else:
        cumplido_igv, estado_igv = pendiente <= CERO, "PAGADO"
    obligaciones.append(
        _obligacion(
            clave="IGV",
            nombre=OBLIGACIONES[2]["nombre"],
            detalle=OBLIGACIONES[2]["detalle"],
            fecha=OBLIGACIONES[2]["fecha"],
            hoy=hoy,
            cumplido=cumplido_igv,
            estado_cumplido=estado_igv,
            extra={
                "pendiente": pendiente,
                "pagado": pagado,
                "deuda_libros": deuda_libros,
                "saldo_favor_libros": saldo_favor_libros,
                "declarada": declaracion is not None,
            },
        )
    )

    caja = {
        "prestamo_socio": saldo_cuenta(empresa, "4411", hoy),
        "reembolso_socio": saldo_cuenta(empresa, "4419", hoy),
        "restituciones_registradas": RestitucionSocio.objects.filter(empresa=empresa).count(),
        "nota": (
            "Los vencimientos del IGV y del PDT no dependen de que llegue el "
            "depósito: si la caja no alcanza, el impuesto igual vence. Las "
            "deudas con el socio se muestran como pendientes hasta que exista "
            "voucher."
        ),
    }

    datos.update(
        {
            "obligaciones": obligaciones,
            "sire": sire,
            "pdt": {
                "declaracion": declaracion,
                "casilla_184": declaracion.casilla_184 if declaracion else None,
            },
            "igv": {
                "pendiente": pendiente,
                "pagado": pagado,
                "deuda_libros": deuda_libros,
                "saldo_favor_libros": saldo_favor_libros,
                "declarada": declaracion is not None,
                "deuda_constancia": declaracion.casilla_184 if declaracion else None,
                "redondeo_constancia": (
                    declaracion.redondeo_deuda if declaracion else None
                ),
            },
            "caja": caja,
        }
    )
    pendientes = [obligacion for obligacion in obligaciones if not obligacion["cumplido"]]
    datos["pendientes"] = len(pendientes)
    datos["vencidos"] = sum(1 for obligacion in pendientes if obligacion["estado"] == "VENCIDO")
    datos["proximo"] = min(pendientes, key=lambda obligacion: obligacion["fecha"]) if pendientes else None
    return datos


def resumen_panel(empresa: Empresa | None, anio: int, mes: int, hoy: date | None = None) -> dict:
    """Datos mínimos para la tarjeta del panel."""
    datos = panel_vencimientos(empresa, anio, mes, hoy=hoy)
    if not datos["verificado"]:
        return {
            "verificado": False,
            "mensaje": datos["mensaje"],
            "pendientes": 0,
            "vencidos": 0,
            "proximo": None,
            "anio": anio,
            "mes": mes,
        }
    pendientes = [obligacion for obligacion in datos["obligaciones"] if not obligacion["cumplido"]]
    return {
        "verificado": True,
        "anio": anio,
        "mes": mes,
        "pendientes": len(pendientes),
        "vencidos": sum(1 for obligacion in pendientes if obligacion["estado"] == "VENCIDO"),
        "proximo": datos["proximo"],
    }

"""Renta RER: cálculo, asiento mensual, saldo por pagar y pago."""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from core.models import Empresa

from .models import Asiento, AsientoLinea
from .servicios import ContabilidadError, Montos, postear

CUENTA_RENTA = "40171"
CUENTA_IGV = "40111"
CERO = Decimal("0")


def calculo(empresa: Empresa, anio: int, mes: int) -> dict:
    """Ventas netas y renta del mes según el RER."""
    from reportes.casillas import calcular

    return calcular(empresa, anio, mes)


def asiento_renta(empresa: Empresa, anio: int, mes: int) -> Asiento | None:
    return Asiento.objects.filter(
        empresa=empresa,
        estado=Asiento.Estado.CONFIRMADO,
        tipo_operacion="RENTA_MENSUAL",
        fecha__year=anio,
        fecha__month=mes,
    ).first()


def monto_renta_asentada(asiento: Asiento | None) -> Decimal:
    if asiento is None:
        return CERO
    filas = asiento.lineas.filter(
        cuenta__codigo__startswith=CUENTA_RENTA
    ).aggregate(d=Sum("debe"), h=Sum("haber"))
    return (filas["h"] or CERO) - (filas["d"] or CERO)


def saldo_cuenta(empresa: Empresa, prefijo: str, hasta: date) -> Decimal:
    """Saldo acreedor (positivo) o deudor (negativo) de una cuenta."""
    filas = AsientoLinea.objects.filter(
        asiento__empresa=empresa,
        asiento__estado=Asiento.Estado.CONFIRMADO,
        asiento__fecha__lte=hasta,
        cuenta__codigo__startswith=prefijo,
    ).aggregate(d=Sum("debe"), h=Sum("haber"))
    return (filas["h"] or CERO) - (filas["d"] or CERO)


def saldo_renta(empresa: Empresa, hasta: date) -> Decimal:
    """Saldo acreedor de la 40171: renta devengada que falta pagar."""
    return saldo_cuenta(empresa, CUENTA_RENTA, hasta)


@transaction.atomic
def asentar_renta(
    empresa: Empresa,
    anio: int,
    mes: int,
    usuario=None,
) -> Asiento | None:
    """Asienta la renta del mes si aún no está asentada. Idempotente."""
    datos = calculo(empresa, anio, mes)
    renta = datos["renta"]
    existente = asiento_renta(empresa, anio, mes)

    if existente is not None:
        asentado = monto_renta_asentada(existente)
        if asentado == renta:
            return existente
        raise ContabilidadError(
            f"La renta asentada es S/ {asentado} y la calculada S/ {renta}. "
            "Anula el asiento de renta del mes y vuelve a asentarla."
        )

    if renta <= CERO:
        return None

    fecha = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return postear(
        empresa=empresa,
        fecha=fecha,
        tipo="RENTA_MENSUAL",
        glosa=f"Renta RER {mes:02d}/{anio} · 1,5 % de S/ {datos['ventas_base']}",
        montos=Montos(total=renta),
        origen_tipo="RENTA_MENSUAL",
        origen_id=anio * 100 + mes,
        usuario=usuario,
    )


@transaction.atomic
def pagar_renta(empresa: Empresa, fecha: date, importe, medio):
    """Registra la salida de banco y debita la renta por pagar."""
    from tesoreria.servicios import registrar

    importe = Decimal(importe).quantize(Decimal("0.01"))
    if importe <= CERO:
        raise ContabilidadError("El importe debe ser mayor a cero.")

    saldo = saldo_renta(empresa, fecha)
    if importe > saldo:
        raise ContabilidadError(
            f"El pago (S/ {importe}) supera la renta por pagar (S/ {saldo})."
        )

    return registrar(
        empresa=empresa,
        cuenta=medio,
        fecha=fecha,
        tipo="EGRESO",
        importe=importe,
        concepto="Pago de renta RER",
        tipo_regla="PAGO_RENTA",
        origen_tipo="PAGO_RENTA",
        origen_id=fecha.year * 100 + fecha.month,
    )

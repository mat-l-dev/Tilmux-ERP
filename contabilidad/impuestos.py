"""Renta RER: cálculo, asiento mensual, saldo por pagar y pago."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum

from core.models import Empresa, HistorialDocumento, Periodo

from .models import Asiento, AsientoLinea
from .servicios import ContabilidadError, Montos, periodo_de, postear

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
    Empresa.objects.select_for_update().get(pk=empresa.pk)
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


def asiento_igv(empresa: Empresa, anio: int, mes: int) -> Asiento | None:
    return Asiento.objects.filter(
        empresa=empresa,
        estado=Asiento.Estado.CONFIRMADO,
        tipo_operacion="IGV_MENSUAL",
        origen_id=anio * 100 + mes,
    ).first()


def monto_igv_pagado(empresa: Empresa, anio: int, mes: int) -> Decimal:
    asientos = Asiento.objects.filter(
        empresa=empresa,
        estado=Asiento.Estado.CONFIRMADO,
        tipo_operacion="IGV_MENSUAL",
        origen_id=anio * 100 + mes,
    )
    filas = AsientoLinea.objects.filter(
        asiento__in=asientos,
        cuenta__codigo__startswith=CUENTA_IGV,
    ).aggregate(d=Sum("debe"), h=Sum("haber"))
    return (filas["d"] or CERO) - (filas["h"] or CERO)


def _igv_del_periodo(
    empresa: Empresa,
    anio: int,
    mes: int,
    saldo_favor_anterior: Decimal | None = None,
) -> Decimal:
    datos = calculo(empresa, anio, mes)
    if saldo_favor_anterior is None:
        desde = date(anio, mes, 1)
        saldo_anterior = saldo_cuenta(empresa, CUENTA_IGV, desde - timedelta(days=1))
        saldo_favor_anterior = max(-saldo_anterior, CERO)
    else:
        try:
            saldo_favor_anterior = Decimal(str(saldo_favor_anterior))
            if not saldo_favor_anterior.is_finite() or saldo_favor_anterior < CERO:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ContabilidadError("El saldo anterior debe ser un importe no negativo.") from None
    return datos["resultado"] - saldo_favor_anterior


def igv_pendiente(
    empresa: Empresa,
    anio: int,
    mes: int,
    saldo_favor_anterior: Decimal | None = None,
) -> Decimal:
    """IGV del periodo que aún no se ha pagado."""
    c184 = _igv_del_periodo(empresa, anio, mes, saldo_favor_anterior=saldo_favor_anterior)
    if c184 <= CERO:
        return CERO
    pagado = monto_igv_pagado(empresa, anio, mes)
    return max(c184 - pagado, CERO)


@transaction.atomic
def pagar_igv(
    empresa: Empresa,
    fecha: date,
    importe,
    medio,
    anio: int,
    mes: int,
    usuario=None,
    saldo_favor_anterior=None,
):
    """Registra el pago del IGV de un periodo, con asiento y movimiento."""
    from tesoreria.servicios import registrar

    if saldo_favor_anterior is not None:
        raise ContabilidadError(
            "La comparación temporal del saldo anterior no puede usarse para registrar pagos."
        )
    importe = Decimal(importe).quantize(Decimal("0.01"))
    if importe <= CERO:
        raise ContabilidadError("El importe debe ser mayor a cero.")
    if medio is None or medio.cuenta_contable is None:
        raise ContabilidadError("Elige una cuenta de tesorería con cuenta contable.")
    if medio.empresa_id != empresa.pk:
        raise ContabilidadError("La cuenta de tesorería pertenece a otra empresa.")
    if not medio.activa or medio.moneda != "PEN":
        raise ContabilidadError("Elige una cuenta activa en soles para registrar el pago de IGV.")

    # Evita que dos pagos simultáneos calculen el mismo saldo pendiente.
    Empresa.objects.select_for_update().get(pk=empresa.pk)

    # El periodo del pago debe estar abierto.
    periodo_de(empresa, fecha)
    periodo = Periodo.objects.filter(empresa=empresa, anio=anio, mes=mes).first()
    if periodo is None:
        raise ContabilidadError(f"No existe el periodo {anio}-{mes:02d}.")
    pendiente = igv_pendiente(empresa, anio, mes)
    if pendiente <= CERO:
        raise ContabilidadError(f"No hay IGV pendiente en {mes:02d}/{anio}.")
    if importe > pendiente:
        raise ContabilidadError(
            f"El pago (S/ {importe}) supera el IGV pendiente (S/ {pendiente})."
        )

    movimiento = registrar(
        empresa=empresa,
        cuenta=medio,
        fecha=fecha,
        tipo="EGRESO",
        importe=importe,
        concepto=f"Pago IGV {mes:02d}/{anio}",
        tipo_regla="IGV_MENSUAL",
        origen_tipo="PAGO_IGV",
        origen_id=anio * 100 + mes,
    )
    asiento = asiento_igv(empresa, anio, mes)
    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo=HistorialDocumento.Tipo.IMPUESTO,
        documento_id=anio * 100 + mes,
        usuario=usuario,
        accion="PAGO",
        detalle=(
            f"IGV {mes:02d}/{anio}: S/ {importe} desde {medio.nombre}. "
            f"Movimiento {movimiento.pk}"
            + (f", asiento {asiento.numero}." if asiento else ".")
        ),
    )
    return movimiento

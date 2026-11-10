"""Conversión a soles con el tipo de cambio guardado."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from core.models import TipoCambio

CENT = Decimal("0.01")


class SinTipoCambio(Exception):
    pass


def tipo_cambio_de(fecha: date) -> TipoCambio:
    try:
        return TipoCambio.del_dia(fecha)
    except ValueError as exc:
        raise SinTipoCambio(
            f"No hay tipo de cambio para {fecha}. Cárgalo antes de registrar el documento."
        ) from exc


def tipo_cambio_para(fecha: date) -> tuple[TipoCambio, bool]:
    """Devuelve el TC aplicable y si es de una fecha anterior (para avisar)."""
    registro = tipo_cambio_de(fecha)
    return registro, registro.fecha != fecha


def a_soles(importe, moneda: str, fecha: date, *, lado: str = "venta") -> tuple[Decimal, Decimal]:
    """Devuelve (importe en soles, tipo de cambio usado)."""
    valor = Decimal(importe).quantize(CENT)
    if moneda == "PEN" or not moneda:
        return valor, Decimal("1")

    registro = tipo_cambio_de(fecha)
    tasa = registro.venta if lado == "venta" else registro.compra
    convertido = (valor * tasa).quantize(CENT, rounding=ROUND_HALF_UP)
    return convertido, tasa

"""Validación numérica común a líneas de compras y ventas."""

from decimal import Decimal, InvalidOperation

from django import forms
from django.core.exceptions import ValidationError

from contabilidad.calculos import calcular_linea

_CANTIDAD = forms.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal("0.0001"))
_PRECIO = forms.DecimalField(max_digits=18, decimal_places=6, min_value=Decimal("0.000001"))
_DINERO = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0"))


def numero_id(texto):
    if not texto or not texto.isascii() or not texto.isdecimal() or len(texto) > 18 or int(texto) < 1:
        raise ValueError("Identificador inválido")
    return int(texto)


def calcular(cantidad, precio, con_igv):
    try:
        cantidad = _CANTIDAD.clean(cantidad.replace(",", "."))
        precio = _PRECIO.clean(precio.replace(",", "."))
        base, igv, total = calcular_linea(cantidad, precio, con_igv)
        if base <= 0 or total >= Decimal("10000000000000000"):
            raise ValueError("Importe fuera de rango")
        return cantidad, precio, base, igv, total
    except (ValidationError, InvalidOperation, ValueError, TypeError, AttributeError):
        raise ValueError("Cantidad o precio inválido") from None


def dinero(texto):
    try:
        return _DINERO.clean((texto or "0").replace(",", "."))
    except (ValidationError, InvalidOperation, ValueError, TypeError, AttributeError):
        raise ValueError("Importe inválido") from None

"""Cálculo de líneas con IGV, en un solo lugar."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TASA_IGV = Decimal("0.18")


def _cent(valor: Decimal) -> Decimal:
    return valor.quantize(CENT, rounding=ROUND_HALF_UP)


def calcular_linea(
    cantidad: Decimal, precio: Decimal, con_igv: bool
) -> tuple[Decimal, Decimal, Decimal]:
    """Devuelve (base, igv, total) redondeando solo en la línea."""
    bruto = _cent(Decimal(cantidad) * Decimal(precio))
    if con_igv:
        base = _cent(bruto / (Decimal("1") + TASA_IGV))
        return base, bruto - base, bruto
    base = bruto
    igv = _cent(base * TASA_IGV)
    return base, igv, base + igv

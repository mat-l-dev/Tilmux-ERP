"""Motor de asientos: la única puerta para escribir contabilidad."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max

from core.models import Empresa, Periodo

from .models import Asiento, AsientoLinea, Cuenta, Regla, ReglaLinea

CENT = Decimal("0.01")
ZERO = Decimal("0")


class ContabilidadError(Exception):
    pass


@dataclass(frozen=True)
class Montos:
    base: Decimal = ZERO
    igv: Decimal = ZERO
    total: Decimal = ZERO
    costo: Decimal = ZERO
    no_gravado: Decimal = ZERO


def q(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def periodo_de(empresa: Empresa, fecha: date) -> Periodo:
    periodo, _ = Periodo.objects.get_or_create(
        empresa=empresa,
        anio=fecha.year,
        mes=fecha.month,
        defaults={"version_pcge": "2026"},
    )
    if periodo.estado == Periodo.Estado.CERRADO:
        raise ContabilidadError(f"El periodo {periodo.etiqueta} está cerrado.")
    return periodo


@transaction.atomic
def postear(
    *,
    empresa: Empresa,
    fecha: date,
    tipo: str,
    glosa: str,
    montos: Montos,
    origen_tipo: str = "",
    origen_id: int | None = None,
    cuenta_medio: Cuenta | None = None,
    cuenta_destino: Cuenta | None = None,
) -> Asiento:
    """Crea el asiento a partir de la regla del tipo de operación."""
    periodo = periodo_de(empresa, fecha)
    try:
        regla = Regla.objects.prefetch_related("lineas__cuenta").get(tipo=tipo)
    except Regla.DoesNotExist as exc:
        raise ContabilidadError(f"No existe regla para {tipo}.") from exc

    Empresa.objects.select_for_update().get(pk=empresa.pk)
    ultimo = Asiento.objects.filter(empresa=empresa).aggregate(m=Max("numero"))["m"]

    asiento = Asiento.objects.create(
        empresa=empresa,
        periodo=periodo,
        numero=(ultimo or 0) + 1,
        fecha=fecha,
        tipo_operacion=tipo,
        glosa=glosa[:255],
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )

    lineas: list[AsientoLinea] = []
    for linea in regla.lineas.all():
        if linea.importe_ref == ReglaLinea.ImporteRef.MEDIO:
            cuenta = cuenta_medio
            valor = montos.total
        elif linea.importe_ref == ReglaLinea.ImporteRef.MEDIO_DESTINO:
            cuenta = cuenta_destino
            valor = montos.total
        else:
            cuenta = linea.cuenta
            valor = getattr(montos, linea.importe_ref.lower())

        valor = q(valor)
        if valor == ZERO:
            continue
        if cuenta is None:
            raise ContabilidadError(
                f"La regla {regla.tipo} necesita una cuenta que no se indicó."
            )
        lineas.append(
            AsientoLinea(
                asiento=asiento,
                orden=len(lineas) + 1,
                cuenta=cuenta,
                debe=valor if linea.lado == "D" else ZERO,
                haber=valor if linea.lado == "H" else ZERO,
                monto_contable=valor,
                monto_tributario=valor,
                glosa=(linea.glosa or glosa)[:255],
            )
        )

    debe = sum((l.debe for l in lineas), ZERO)
    haber = sum((l.haber for l in lineas), ZERO)
    if debe != haber:
        raise ContabilidadError(
            f"El asiento no cuadra: debe {debe} contra haber {haber}."
        )
    if not lineas:
        raise ContabilidadError("El asiento quedó sin líneas.")

    AsientoLinea.objects.bulk_create(lineas)
    return asiento

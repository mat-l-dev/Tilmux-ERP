"""Motor de asientos: la única puerta para escribir contabilidad."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max

from core.contexto import usuario_actual
from core.models import Empresa, HistorialDocumento, Periodo

from .models import Asiento, AsientoLinea, Cuenta, Regla, ReglaLinea

logger = logging.getLogger(__name__)

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
    # Serializa la comprobación del período con su cierre y con otros asientos.
    Empresa.objects.select_for_update().get(pk=empresa.pk)
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
    cuenta_gasto: Cuenta | None = None,
    usuario=None,
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
        creado_por=usuario or usuario_actual.get(),
    )

    lineas: list[AsientoLinea] = []
    for linea in regla.lineas.all():
        if linea.importe_ref == ReglaLinea.ImporteRef.MEDIO:
            cuenta = cuenta_medio
            valor = montos.total
        elif linea.importe_ref == ReglaLinea.ImporteRef.MEDIO_DESTINO:
            cuenta = cuenta_destino
            valor = montos.total
        elif linea.importe_ref == ReglaLinea.ImporteRef.GASTO:
            cuenta = cuenta_gasto
            valor = montos.base if montos.base else montos.total
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

    debe = sum((linea.debe for linea in lineas), ZERO)
    haber = sum((linea.haber for linea in lineas), ZERO)
    if debe != haber:
        raise ContabilidadError(
            f"El asiento no cuadra: debe {debe} contra haber {haber}."
        )
    if not lineas:
        raise ContabilidadError("El asiento quedó sin líneas.")

    AsientoLinea.objects.bulk_create(lineas)
    logger.info(
        "asiento %s %s total=%s usuario=%s",
        asiento.numero, asiento.tipo_operacion, sum((x.debe for x in lineas), ZERO),
        getattr(asiento.creado_por, "username", None),
    )
    return asiento


@transaction.atomic
def postear_lineas(
    *,
    empresa: Empresa,
    fecha: date,
    tipo: str,
    glosa: str,
    lineas: list[tuple[Cuenta, Decimal, Decimal, str]],
    origen_tipo: str = "",
    origen_id: int | None = None,
    usuario=None,
) -> Asiento:
    """Asiento con líneas explícitas: (cuenta, debe, haber, glosa)."""
    periodo = periodo_de(empresa, fecha)
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
        creado_por=usuario or usuario_actual.get(),
    )

    filas = []
    for orden, (cuenta, debe, haber, detalle) in enumerate(lineas, start=1):
        debe, haber = q(debe), q(haber)
        if debe == ZERO and haber == ZERO:
            continue
        filas.append(
            AsientoLinea(
                asiento=asiento,
                orden=orden,
                cuenta=cuenta,
                debe=debe,
                haber=haber,
                monto_contable=debe or haber,
                monto_tributario=debe or haber,
                glosa=(detalle or glosa)[:255],
            )
        )

    total_debe = sum((linea.debe for linea in filas), ZERO)
    total_haber = sum((linea.haber for linea in filas), ZERO)
    if total_debe != total_haber:
        raise ContabilidadError(
            f"El asiento no cuadra: debe {total_debe} contra haber {total_haber}."
        )
    if not filas:
        raise ContabilidadError("El asiento quedó sin líneas.")

    AsientoLinea.objects.bulk_create(filas)
    return asiento


def _historial_asiento(asiento: Asiento, *, accion: str, detalle: str, usuario=None):
    HistorialDocumento.objects.create(
        empresa=asiento.empresa,
        tipo=HistorialDocumento.Tipo.ASIENTO,
        documento_id=asiento.pk,
        usuario=usuario,
        accion=accion,
        detalle=detalle[:2000],
    )


@transaction.atomic
def anular_asiento(asiento: Asiento, motivo: str, usuario=None) -> Asiento:
    """Anula un asiento sin borrar sus líneas y deja rastro en el historial."""
    if not motivo.strip():
        raise ContabilidadError("La anulación de un asiento necesita un motivo.")

    asiento = (
        Asiento.objects.select_for_update()
        .select_related("periodo")
        .get(pk=asiento.pk)
    )
    if asiento.estado == Asiento.Estado.ANULADO:
        return asiento
    if asiento.periodo.estado == Periodo.Estado.CERRADO:
        raise ContabilidadError(
            f"El periodo {asiento.periodo.etiqueta} está cerrado; "
            "no se puede anular el asiento."
        )

    anterior = asiento.estado
    asiento.estado = Asiento.Estado.ANULADO
    asiento.save(update_fields=["estado"])
    _historial_asiento(
        asiento,
        accion="ANULACION",
        detalle=f"Motivo: {motivo.strip()}. Estado anterior: {anterior}.",
        usuario=usuario,
    )
    logger.warning("asiento %s anulado: %s", asiento.numero, motivo.strip())
    return asiento


@transaction.atomic
def reclasificar_linea_asiento(
    linea: AsientoLinea,
    cuenta_nueva: Cuenta,
    motivo: str,
    *,
    glosa: str | None = None,
    usuario=None,
) -> AsientoLinea:
    """Cambia la cuenta de una línea confirmada, conservando el asiento y su historia."""
    if not motivo.strip():
        raise ContabilidadError("La reclasificación necesita un motivo.")

    linea = (
        AsientoLinea.objects.select_for_update()
        .select_related("asiento", "asiento__periodo", "cuenta")
        .get(pk=linea.pk)
    )
    asiento = linea.asiento
    if asiento.estado != Asiento.Estado.CONFIRMADO:
        raise ContabilidadError("Solo se reclasifica una línea de un asiento confirmado.")
    if asiento.periodo.estado == Periodo.Estado.CERRADO:
        raise ContabilidadError(
            f"El periodo {asiento.periodo.etiqueta} está cerrado; "
            "no se puede reclasificar la línea."
        )

    anterior = linea.cuenta
    if anterior.pk == cuenta_nueva.pk:
        return linea

    linea.cuenta = cuenta_nueva
    campos = ["cuenta"]
    if glosa is not None:
        linea.glosa = glosa[:255]
        campos.append("glosa")
    linea.save(update_fields=campos)
    _historial_asiento(
        asiento,
        accion="RECLASIFICACION",
        detalle=(
            f"Línea {linea.orden}: {anterior.codigo} {anterior.nombre} → "
            f"{cuenta_nueva.codigo} {cuenta_nueva.nombre}. Motivo: {motivo.strip()}."
        ),
        usuario=usuario,
    )
    logger.warning(
        "línea %s del asiento %s reclasificada de %s a %s",
        linea.orden,
        asiento.numero,
        anterior.codigo,
        cuenta_nueva.codigo,
    )
    return linea


@transaction.atomic
def corregir_glosa_asiento(
    asiento: Asiento,
    glosa: str,
    motivo: str,
    usuario=None,
) -> Asiento:
    """Corrige la glosa de un asiento confirmado y registra el cambio."""
    if not glosa.strip():
        raise ContabilidadError("La glosa no puede quedar vacía.")
    if not motivo.strip():
        raise ContabilidadError("La corrección de glosa necesita un motivo.")

    asiento = Asiento.objects.select_for_update().get(pk=asiento.pk)
    if asiento.estado != Asiento.Estado.CONFIRMADO:
        raise ContabilidadError("Solo se corrige la glosa de un asiento confirmado.")

    anterior = asiento.glosa
    if anterior == glosa.strip():
        return asiento

    asiento.glosa = glosa.strip()[:255]
    asiento.save(update_fields=["glosa"])
    _historial_asiento(
        asiento,
        accion="CORRECCION",
        detalle=f"Glosa: «{anterior}» → «{asiento.glosa}». Motivo: {motivo.strip()}.",
        usuario=usuario,
    )
    return asiento

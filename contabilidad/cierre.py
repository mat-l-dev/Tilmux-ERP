"""Cierre anual: cuentas de resultado a 89 y luego a 59.

El cierre se hace con dos asientos al 31 de diciembre:

1. Se debitan las cuentas de ingreso (elemento 7) y se acreditan las de gasto
   (elementos 6 y 8). La diferencia va a la cuenta 89, que es solo de tránsito.
2. El saldo de 89 se transfiere a resultados acumulados: 591 si hubo utilidad
   o 592 si hubo pérdida.

Los asientos quedan marcados con ``origen_tipo = "CIERRE"`` para que los
estados financieros no los cuenten dos veces: el estado de resultados excluye
el cierre y el balance sí lo incluye.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Sum

from compras.models import Compra
from core.contexto import usuario_actual
from core.models import Empresa, Periodo
from ventas.models import Venta

from .models import Asiento, AsientoLinea, Cuenta
from .servicios import ContabilidadError, q

CIERRE = "CIERRE"
CERO = Decimal("0")


def _cuenta(codigo: str) -> Cuenta:
    try:
        return Cuenta.objects.get(version="2026", codigo=codigo)
    except Cuenta.DoesNotExist as exc:
        raise ContabilidadError(f"Falta la cuenta {codigo} en el PCGE.") from exc


def saldos_resultado(empresa: Empresa, anio: int):
    """Cuentas 6, 7 y 8 con movimiento en el año, sin los asientos de cierre."""
    return (
        AsientoLinea.objects.filter(
            asiento__empresa=empresa,
            asiento__estado=Asiento.Estado.CONFIRMADO,
            asiento__fecha__year=anio,
            cuenta__elemento__in=(6, 7, 8),
        )
        .exclude(asiento__origen_tipo=CIERRE)
        .values("cuenta__codigo", "cuenta__nombre", "cuenta__elemento")
        .annotate(debe=Sum("debe"), haber=Sum("haber"))
        .order_by("cuenta__codigo")
    )


def calcular(empresa: Empresa, anio: int) -> dict:
    """Saldos y resultado del ejercicio antes de cerrar."""
    filas = []
    ingresos = CERO
    gastos = CERO

    for fila in saldos_resultado(empresa, anio):
        debe = fila["debe"] or CERO
        haber = fila["haber"] or CERO
        elemento = fila["cuenta__elemento"]

        if elemento == 7:
            saldo = q(haber - debe)
            if saldo == CERO:
                continue
            ingresos += saldo
            # Para cerrar un ingreso se debita la cuenta.
            lado = "D" if saldo > 0 else "H"
        else:
            saldo = q(debe - haber)
            if saldo == CERO:
                continue
            gastos += saldo
            # Para cerrar un gasto se acredita la cuenta.
            lado = "H" if saldo > 0 else "D"

        filas.append(
            {
                "codigo": fila["cuenta__codigo"],
                "nombre": fila["cuenta__nombre"],
                "elemento": elemento,
                "importe": abs(saldo),
                "lado": lado,
                "tipo": "ingreso" if elemento == 7 else "gasto",
            }
        )

    return {
        "anio": anio,
        "filas": filas,
        "ingresos": q(ingresos),
        "gastos": q(gastos),
        "resultado": q(ingresos - gastos),
    }


def estado(empresa: Empresa, anio: int) -> dict:
    """Indica si el ejercicio está cerrado y qué falta para cerrarlo."""
    cerrado = Asiento.objects.filter(
        empresa=empresa,
        origen_tipo=CIERRE,
        origen_id=anio,
        estado=Asiento.Estado.CONFIRMADO,
    ).exists()
    abiertos = list(
        Periodo.objects.filter(
            empresa=empresa, anio=anio, estado=Periodo.Estado.ABIERTO
        ).order_by("mes")
    )
    borradores = Venta.objects.filter(
        empresa=empresa, fecha__year=anio, estado=Venta.Estado.BORRADOR
    ).count()
    borradores += Compra.objects.filter(
        empresa=empresa, fecha__year=anio, estado=Compra.Estado.BORRADOR
    ).count()
    datos = calcular(empresa, anio)
    return {
        **datos,
        "cerrado": cerrado,
        "abiertos": abiertos,
        "borradores": borradores,
        "puede_cerrar": not cerrado and not abiertos and borradores == 0,
    }


def _validar(empresa: Empresa, anio: int) -> None:
    if Asiento.objects.filter(
        empresa=empresa,
        origen_tipo=CIERRE,
        origen_id=anio,
        estado=Asiento.Estado.CONFIRMADO,
    ).exists():
        raise ContabilidadError(f"El ejercicio {anio} ya está cerrado.")

    abiertos = Periodo.objects.filter(
        empresa=empresa, anio=anio, estado=Periodo.Estado.ABIERTO
    ).order_by("mes")
    if abiertos.exists():
        etiquetas = ", ".join(p.etiqueta for p in abiertos)
        raise ContabilidadError(
            f"Cierra primero los periodos abiertos: {etiquetas}."
        )

    borradores = Venta.objects.filter(
        empresa=empresa, fecha__year=anio, estado=Venta.Estado.BORRADOR
    ).count()
    borradores += Compra.objects.filter(
        empresa=empresa, fecha__year=anio, estado=Compra.Estado.BORRADOR
    ).count()
    if borradores:
        raise ContabilidadError(
            f"Quedan {borradores} comprobante(s) en borrador del ejercicio {anio}."
        )


def _periodo(empresa: Empresa, anio: int) -> Periodo:
    periodo, _ = Periodo.objects.get_or_create(
        empresa=empresa,
        anio=anio,
        mes=12,
        defaults={"version_pcge": "2026"},
    )
    return periodo


def _crear_asiento(
    *,
    empresa: Empresa,
    periodo: Periodo,
    fecha: date,
    glosa: str,
    lineas: list[tuple[Cuenta, Decimal, Decimal, str]],
    usuario=None,
) -> Asiento:
    filas = []
    for orden, (cuenta, debe, haber, detalle) in enumerate(lineas, start=1):
        debe, haber = q(debe), q(haber)
        if debe == CERO and haber == CERO:
            continue
        filas.append(
            AsientoLinea(
                asiento=None,
                orden=orden,
                cuenta=cuenta,
                debe=debe,
                haber=haber,
                monto_contable=debe or haber,
                monto_tributario=debe or haber,
                glosa=(detalle or glosa)[:255],
            )
        )

    total_debe = sum((linea.debe for linea in filas), CERO)
    total_haber = sum((linea.haber for linea in filas), CERO)
    if total_debe != total_haber:
        raise ContabilidadError(
            f"El asiento de cierre no cuadra: debe {total_debe} contra haber {total_haber}."
        )
    if not filas:
        raise ContabilidadError("El asiento de cierre quedó sin líneas.")

    Empresa.objects.select_for_update().get(pk=empresa.pk)
    ultimo = Asiento.objects.filter(empresa=empresa).aggregate(m=Max("numero"))["m"]
    asiento = Asiento.objects.create(
        empresa=empresa,
        periodo=periodo,
        numero=(ultimo or 0) + 1,
        fecha=fecha,
        tipo_operacion=CIERRE,
        glosa=glosa[:255],
        origen_tipo=CIERRE,
        origen_id=fecha.year,
        creado_por=usuario or usuario_actual.get(),
    )
    for linea in filas:
        linea.asiento = asiento
    AsientoLinea.objects.bulk_create(filas)
    return asiento


@transaction.atomic
def cerrar(empresa: Empresa, anio: int, usuario=None) -> list[Asiento]:
    """Genera los asientos de cierre del ejercicio. Devuelve los creados."""
    _validar(empresa, anio)
    datos = calcular(empresa, anio)
    if not datos["filas"]:
        raise ContabilidadError(
            f"El ejercicio {anio} no tiene cuentas de resultado para cerrar."
        )

    fecha = date(anio, 12, 31)
    periodo = _periodo(empresa, anio)
    glosa = f"Cierre del ejercicio {anio}"

    lineas = []
    for fila in datos["filas"]:
        cuenta = _cuenta(fila["codigo"])
        if fila["lado"] == "D":
            lineas.append((cuenta, fila["importe"], CERO, f"Cierre {cuenta.codigo}"))
        else:
            lineas.append((cuenta, CERO, fila["importe"], f"Cierre {cuenta.codigo}"))

    resultado = datos["resultado"]
    asientos = []
    if resultado > 0:
        lineas.append(
            (_cuenta("891"), CERO, resultado, f"Utilidad del ejercicio {anio}")
        )
    elif resultado < 0:
        lineas.append(
            (_cuenta("892"), -resultado, CERO, f"Pérdida del ejercicio {anio}")
        )

    asientos.append(
        _crear_asiento(
            empresa=empresa,
            periodo=periodo,
            fecha=fecha,
            glosa=f"{glosa} · determinación del resultado",
            lineas=lineas,
            usuario=usuario,
        )
    )

    if resultado > 0:
        asientos.append(
            _crear_asiento(
                empresa=empresa,
                periodo=periodo,
                fecha=fecha,
                glosa=f"{glosa} · utilidad a resultados acumulados",
                lineas=[
                    (_cuenta("891"), resultado, CERO, "Cierre de la cuenta 89"),
                    (_cuenta("591"), CERO, resultado, "Utilidad no distribuida"),
                ],
                usuario=usuario,
            )
        )
    elif resultado < 0:
        asientos.append(
            _crear_asiento(
                empresa=empresa,
                periodo=periodo,
                fecha=fecha,
                glosa=f"{glosa} · pérdida a resultados acumulados",
                lineas=[
                    (_cuenta("592"), -resultado, CERO, "Pérdida acumulada"),
                    (_cuenta("892"), CERO, -resultado, "Cierre de la cuenta 89"),
                ],
                usuario=usuario,
            )
        )

    if periodo.estado != Periodo.Estado.CERRADO:
        periodo.estado = Periodo.Estado.CERRADO
        periodo.save(update_fields=["estado"])

    return asientos


@transaction.atomic
def revertir(empresa: Empresa, anio: int) -> int:
    """Anula los asientos de cierre del ejercicio. Devuelve cuántos anuló."""
    asientos = Asiento.objects.filter(
        empresa=empresa,
        origen_tipo=CIERRE,
        origen_id=anio,
        estado=Asiento.Estado.CONFIRMADO,
    )
    total = asientos.count()
    if not total:
        raise ContabilidadError(f"El ejercicio {anio} no está cerrado.")
    asientos.update(estado=Asiento.Estado.ANULADO)
    return total

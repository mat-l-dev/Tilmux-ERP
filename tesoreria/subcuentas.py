"""Subcuentas analíticas por banco bajo la 1061 y su conciliación.

La 1061 agrupa todas las cuentas corrientes; sin subcuentas, una transferencia
entre dos bancos propios asienta D 1061 / H 1061 y desaparece del mayor. Cada
`CuentaTesoreria` de tipo BANCO recibe una divisionaria determinista (106101,
106102, …) que cuelga de la 1061: el total agregado no cambia y cada banco
queda visible y conciliable.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from contabilidad.models import Asiento, AsientoLinea, Cuenta
from contabilidad.servicios import Montos, postear

from .models import MovimientoTesoreria

PADRE = "1061"
CERO = Decimal("0.00")


class SubcuentaError(Exception):
    pass


def _padre(version: str) -> Cuenta:
    padre = Cuenta.objects.filter(version=version, codigo=PADRE).first()
    if padre is None:
        raise SubcuentaError(f"No existe la cuenta {PADRE} en la versión {version} del PCGE.")
    return padre


def _siguiente_codigo(version: str) -> str:
    codigos = set(Cuenta.objects.filter(version=version, codigo__startswith=PADRE).values_list("codigo", flat=True))
    sufijos = [int(codigo[4:]) for codigo in codigos if len(codigo) == 6 and codigo[4:].isdigit()]
    siguiente = max(sufijos, default=0) + 1
    while f"{PADRE}{siguiente:02d}" in codigos:
        siguiente += 1
    return f"{PADRE}{siguiente:02d}"


def subcuenta_de(cuenta) -> Cuenta:
    """Devuelve la subcuenta de la cuenta bancaria, creándola si no existe.

    Es determinista: la primera vez crea el siguiente código libre bajo 1061 y
    lo guarda en la cuenta de tesorería; las siguientes veces devuelve el mismo.
    """
    actual = cuenta.cuenta_contable
    if actual is not None and len(actual.codigo) == 6 and actual.codigo.startswith(PADRE) and actual.codigo != PADRE:
        return actual

    version = actual.version if actual is not None else "2026"
    padre = _padre(version)
    codigo = _siguiente_codigo(version)
    subcuenta = Cuenta.objects.create(
        version=version,
        codigo=codigo,
        nombre=f"{cuenta.nombre} · subcuenta {PADRE}",
        padre=PADRE,
        elemento=padre.elemento,
        naturaleza=padre.naturaleza,
        admite_movimiento=True,
        activa=True,
    )
    if cuenta.pk:
        type(cuenta).objects.filter(pk=cuenta.pk).update(cuenta_contable=subcuenta)
    cuenta.cuenta_contable = subcuenta
    return subcuenta


def saldo_tesoreria(empresa, cuenta, hasta=None) -> Decimal:
    """Saldo de la cuenta bancaria según sus movimientos de tesorería."""
    movimientos = MovimientoTesoreria.objects.filter(empresa=empresa, cuenta=cuenta)
    if hasta is not None:
        movimientos = movimientos.filter(fecha__lte=hasta)
    totales = movimientos.aggregate(
        ingresos=Sum("importe", filter=Q(tipo=MovimientoTesoreria.Tipo.INGRESO)),
        egresos=Sum("importe", filter=Q(tipo=MovimientoTesoreria.Tipo.EGRESO)),
    )
    return (totales["ingresos"] or CERO) - (totales["egresos"] or CERO)


def saldo_contable(empresa, cuenta, hasta=None) -> Decimal:
    """Saldo deudor de la subcuenta contable del banco."""
    subcuenta = subcuenta_de(cuenta)
    lineas = AsientoLinea.objects.filter(
        asiento__empresa=empresa,
        asiento__estado=Asiento.Estado.CONFIRMADO,
        cuenta=subcuenta,
    )
    if hasta is not None:
        lineas = lineas.filter(asiento__fecha__lte=hasta)
    totales = lineas.aggregate(debe=Sum("debe"), haber=Sum("haber"))
    return (totales["debe"] or CERO) - (totales["haber"] or CERO)


@transaction.atomic
def reclasificar_historico(empresa, fecha) -> list[dict]:
    """Mueve el saldo histórico de la 1061 a la subcuenta de cada banco.

    No toca los asientos históricos: crea un asiento de reclasificación por
    banco (D subcuenta / H 1061, o al revés) por la diferencia entre tesorería y
    subcuenta. Es idempotente. Requiere un período abierto en ``fecha``.
    """
    from catalogo.models import CuentaTesoreria

    padre = _padre("2026")
    movimientos = []
    for cuenta in CuentaTesoreria.objects.filter(empresa=empresa, tipo=CuentaTesoreria.Tipo.BANCO).select_related(
        "cuenta_contable"
    ):
        subcuenta = subcuenta_de(cuenta)
        padre = _padre(subcuenta.version)
        en_tesoreria = saldo_tesoreria(empresa, cuenta)
        en_contabilidad = saldo_contable(empresa, cuenta, hasta=fecha)
        diferencia = en_tesoreria - en_contabilidad
        if diferencia == 0:
            continue
        if diferencia > 0:
            medio, destino = padre, subcuenta
        else:
            medio, destino = subcuenta, padre
        asiento = postear(
            empresa=empresa,
            fecha=fecha,
            tipo="TRANSFERENCIA",
            glosa=f"Reclasificación de saldo histórico · {cuenta.nombre}"[:255],
            montos=Montos(total=abs(diferencia)),
            origen_tipo="RECLASIFICACION",
            origen_id=cuenta.pk,
            cuenta_medio=medio,
            cuenta_destino=destino,
        )
        movimientos.append(
            {
                "cuenta": cuenta,
                "subcuenta": subcuenta,
                "importe": abs(diferencia),
                "asiento": asiento,
            }
        )
    return movimientos

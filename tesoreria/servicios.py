from datetime import date
from decimal import Decimal

from django.db import transaction

from catalogo.models import CuentaTesoreria
from contabilidad.servicios import Montos, postear
from core.models import Empresa

from .models import MovimientoTesoreria


@transaction.atomic
def registrar(
    *,
    empresa: Empresa,
    cuenta: CuentaTesoreria,
    fecha: date,
    tipo: str,
    importe: Decimal,
    concepto: str,
    canal: str = "TRANSFERENCIA",
    origen_tipo: str = "",
    origen_id: int | None = None,
    tipo_regla: str | None = None,
    base: Decimal | None = None,
    igv: Decimal = Decimal("0"),
) -> MovimientoTesoreria:
    movimiento = MovimientoTesoreria.objects.create(
        empresa=empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo=tipo,
        importe=importe,
        canal=canal,
        concepto=concepto[:200],
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )

    regla = tipo_regla or (
        "COBRO_CLIENTE"
        if tipo == MovimientoTesoreria.Tipo.INGRESO
        else "PAGO_PROVEEDOR"
    )
    postear(
        empresa=empresa,
        fecha=fecha,
        tipo=regla,
        glosa=concepto,
        montos=Montos(
            total=importe,
            base=importe if base is None else base,
            igv=igv,
        ),
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        cuenta_medio=cuenta.cuenta_contable,
    )
    return movimiento


@transaction.atomic
def anotar(
    *,
    empresa: Empresa,
    cuenta: CuentaTesoreria,
    fecha: date,
    tipo: str,
    importe: Decimal,
    concepto: str,
    canal: str = "TRANSFERENCIA",
    origen_tipo: str = "",
    origen_id: int | None = None,
) -> MovimientoTesoreria:
    """Registra el movimiento de dinero sin generar asiento (ya lo hizo el dueño)."""
    return MovimientoTesoreria.objects.create(
        empresa=empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo=tipo,
        importe=importe,
        canal=canal,
        concepto=concepto[:200],
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )


@transaction.atomic
def transferir(
    *,
    empresa: Empresa,
    origen: CuentaTesoreria,
    destino: CuentaTesoreria,
    fecha: date,
    importe: Decimal,
    concepto: str,
) -> None:
    MovimientoTesoreria.objects.create(
        empresa=empresa,
        cuenta=origen,
        fecha=fecha,
        tipo=MovimientoTesoreria.Tipo.EGRESO,
        importe=importe,
        concepto=f"Transferencia a {destino.nombre}: {concepto}"[:200],
        origen_tipo="TRANSFERENCIA",
    )
    MovimientoTesoreria.objects.create(
        empresa=empresa,
        cuenta=destino,
        fecha=fecha,
        tipo=MovimientoTesoreria.Tipo.INGRESO,
        importe=importe,
        concepto=f"Transferencia desde {origen.nombre}: {concepto}"[:200],
        origen_tipo="TRANSFERENCIA",
    )
    postear(
        empresa=empresa,
        fecha=fecha,
        tipo="TRANSFERENCIA",
        glosa=concepto,
        montos=Montos(total=importe),
        origen_tipo="TRANSFERENCIA",
        cuenta_medio=origen.cuenta_contable,
        cuenta_destino=destino.cuenta_contable,
    )

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

    tipo_regla = (
        "COBRO_CLIENTE"
        if tipo == MovimientoTesoreria.Tipo.INGRESO
        else "PAGO_PROVEEDOR"
    )
    postear(
        empresa=empresa,
        fecha=fecha,
        tipo=tipo_regla,
        glosa=concepto,
        montos=Montos(total=importe),
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        cuenta_medio=cuenta.cuenta_contable,
    )
    return movimiento

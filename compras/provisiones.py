"""Registro auditable de gastos devengados aún sin comprobante."""

from decimal import Decimal
from uuid import UUID

from django.db import transaction

from core.models import Empresa, HistorialDocumento

from .models_gasto import Gasto
from .servicios import CompraError, registrar_gasto


@transaction.atomic
def registrar_provision(*, empresa, proveedor, fecha, importe, cuenta, glosa, usuario, operacion):
    if not isinstance(operacion, UUID) or usuario is None or not usuario.pk:
        raise CompraError("La operación necesita un identificador y usuario válidos.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    detalle = f"Operación: {operacion}"
    anterior = HistorialDocumento.objects.filter(
        empresa=empresa,
        tipo=HistorialDocumento.Tipo.GASTO,
        usuario=usuario,
        accion="PROVISION",
        detalle=detalle,
    ).first()
    if anterior:
        gasto = Gasto.objects.filter(pk=anterior.documento_id, empresa=empresa, provision=True).first()
        if gasto is None:
            raise CompraError("No se encontró la provisión asociada a esta operación; revisa el historial.")
        return gasto, False
    if not proveedor.activo or proveedor.rol not in ("PROVEEDOR", "AMBOS"):
        raise CompraError("Selecciona un proveedor activo.")
    if not glosa.strip():
        raise CompraError("Describe el gasto devengado.")
    gasto = registrar_gasto(
        empresa=empresa,
        proveedor=proveedor,
        fecha=fecha,
        fecha_devengado=fecha,
        tipo_doc=Gasto.TipoDoc.OTRO,
        serie="",
        numero="",
        base=importe,
        igv=Decimal("0"),
        total=importe,
        cuenta=cuenta,
        medio=None,
        glosa=glosa.strip(),
        provision=True,
        con_credito=False,
        deducible=False,
    )
    gasto.creado_por = usuario
    gasto.save(update_fields=["creado_por"])
    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo=HistorialDocumento.Tipo.GASTO,
        documento_id=gasto.pk,
        usuario=usuario,
        accion="PROVISION",
        detalle=detalle,
    )
    return gasto, True

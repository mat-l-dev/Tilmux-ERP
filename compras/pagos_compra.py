"""Registro idempotente de pagos introducidos desde la pantalla de compras."""

from uuid import UUID

from django.db import transaction

from core.models import HistorialDocumento

from .models import Compra
from .servicios import CompraError, pagar


@transaction.atomic
def registrar_pago(*, compra, cuenta, fecha, canal, tipo_cambio_pago, importe, operacion, usuario):
    try:
        identificador = UUID(str(operacion))
    except (ValueError, TypeError, AttributeError):
        raise CompraError("La operación no es válida. Vuelve a abrir el formulario de pago.") from None
    if not importe or not str(importe).strip():
        raise CompraError("Indica el importe del pago.")
    compra = Compra.objects.select_for_update().get(pk=compra.pk, empresa=compra.empresa)
    identificacion = f"Operación: {identificador}"
    if HistorialDocumento.objects.filter(
        empresa=compra.empresa, tipo=HistorialDocumento.Tipo.COMPRA, documento_id=compra.pk,
        accion="PAGO", detalle__endswith=identificacion,
    ).exists():
        return None, False
    resultado = pagar(compra, cuenta=cuenta, fecha=fecha, canal=canal,
                      tipo_cambio_pago=tipo_cambio_pago, importe=importe)
    HistorialDocumento.objects.create(
        empresa=compra.empresa, tipo=HistorialDocumento.Tipo.COMPRA, documento_id=compra.pk,
        usuario=usuario, accion="PAGO", detalle=f"Pago de S/ {resultado[0]} el {fecha}. {identificacion}",
    )
    return resultado, True

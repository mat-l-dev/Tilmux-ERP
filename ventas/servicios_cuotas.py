"""Programación de pagos pactada en borradores de venta."""

from decimal import Decimal

from django.db import transaction

from core.models import HistorialDocumento

from .models import CuotaVenta, Venta
from .servicios import VentaError


def validar_cuotas(venta, cuotas, total):
    if not cuotas:
        raise VentaError("Agrega al menos una cuota para la venta al crédito.")
    if any(c["importe"] <= 0 or c["vencimiento"] < venta.fecha for c in cuotas):
        raise VentaError("Cada cuota debe ser positiva y vencer en la fecha de la venta o después.")
    if not any(c["vencimiento"] > venta.fecha for c in cuotas):
        raise VentaError("Una venta al crédito necesita al menos un vencimiento posterior a la venta.")
    if sum((c["importe"] for c in cuotas), Decimal("0")) != total:
        raise VentaError(
            "La suma de las cuotas debe ser igual al total de la venta. "
            "Los anticipos y deducciones aún no están implementados."
        )


@transaction.atomic
def guardar_cuotas(*, venta, cuotas, usuario=None):
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.BORRADOR or venta.condicion != Venta.Condicion.CREDITO:
        raise VentaError("Solo se pueden programar cuotas en una venta al crédito en borrador.")
    total = sum((linea.total for linea in venta.lineas.all()), Decimal("0"))
    validar_cuotas(venta, cuotas, total)
    venta.cuotas.all().delete()
    CuotaVenta.objects.bulk_create([
        CuotaVenta(venta=venta, numero=i, vencimiento=cuota["vencimiento"], importe=cuota["importe"])
        for i, cuota in enumerate(cuotas, 1)
    ])
    detalle = "; ".join(f"{c['vencimiento'].isoformat()}: {c['importe']:.2f}" for c in cuotas)
    HistorialDocumento.objects.create(
        empresa=venta.empresa, tipo="VENTA", documento_id=venta.pk, usuario=usuario,
        accion="CUOTAS", detalle=f"Cuotas pactadas: {detalle}",
    )

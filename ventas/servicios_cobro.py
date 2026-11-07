"""Saldos y cobros de ventas al crédito, sin modificar documentos históricos."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Sum

from catalogo.models import CuentaTesoreria
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import registrar

from .models import CobroVenta, Venta
from .servicios import VentaError


def saldo_pendiente(venta):
    """Saldo documentado; no incluye cobros históricos no vinculados a la venta."""

    def suma(qs):
        return qs.aggregate(total=Sum("total"))["total"] or Decimal("0")

    cobrado = venta.cobros.aggregate(total=Sum("importe"))["total"] or Decimal("0")
    return venta.total + suma(venta.notas_debito) - suma(venta.notas_credito) - cobrado


@transaction.atomic
def cobrar_venta(*, venta, fecha, importe, cuenta, canal, usuario=None):
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA or venta.condicion != Venta.Condicion.CREDITO:
        raise VentaError("Solo se pueden cobrar ventas al crédito confirmadas.")
    if venta.moneda != "PEN":
        raise VentaError("Por ahora solo se pueden registrar cobros en soles.")
    cuenta = CuentaTesoreria.objects.select_for_update().get(pk=cuenta.pk)
    if (
        cuenta.empresa_id != venta.empresa_id
        or not cuenta.activa
        or cuenta.moneda != "PEN"
        or not cuenta.cuenta_contable_id
    ):
        raise VentaError("Selecciona una cuenta activa en soles de la empresa, con cuenta contable.")
    if canal not in CuentaTesoreria.Canal.values:
        raise VentaError("Selecciona un canal de cobro válido.")
    try:
        importe = Decimal(importe)
        if not importe.is_finite() or importe <= 0 or importe != importe.quantize(Decimal("0.01")):
            raise VentaError("El importe debe ser positivo y tener hasta dos decimales.")
    except InvalidOperation, TypeError, ValueError:
        raise VentaError("El importe del cobro no es válido.") from None
    fechas = [venta.fecha]
    for documentos in (venta.cobros, venta.notas_credito, venta.notas_debito):
        ultima = documentos.aggregate(fecha=Max("fecha"))["fecha"]
        if ultima:
            fechas.append(ultima)
    if fecha < max(fechas):
        raise VentaError("La fecha no puede ser anterior a la venta, sus notas o cobros ya registrados.")
    if MovimientoTesoreria.objects.filter(
        empresa=venta.empresa, origen_tipo="VENTA", origen_id=venta.pk, tipo="INGRESO"
    ).exists():
        raise VentaError(
            "La venta tiene un movimiento de cobro anterior que requiere revisión antes de registrar otro."
        )
    saldo = saldo_pendiente(venta)
    if importe > saldo:
        raise VentaError(f"El importe excede el saldo pendiente de S/ {max(saldo, Decimal('0')):.2f}.")
    cobro = CobroVenta.objects.create(
        venta=venta, fecha=fecha, importe=importe, cuenta=cuenta, canal=canal, creado_por=usuario
    )
    registrar(
        empresa=venta.empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo="INGRESO",
        importe=importe,
        concepto=f"Cobro venta {venta.serie}-{venta.numero}",
        canal=canal,
        origen_tipo="COBRO_VENTA",
        origen_id=cobro.pk,
    )
    return cobro

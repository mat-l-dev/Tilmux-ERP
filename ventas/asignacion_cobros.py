"""Asignación explícita de cobros existentes a cuotas, sin volver a cobrar."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from catalogo.models import CuentaTesoreria
from contabilidad.models import Asiento
from core.models import Empresa, HistorialDocumento, Periodo
from tesoreria.models import MovimientoTesoreria

from .models import CobroVenta, CuotaVenta, Venta
from .servicios import VentaError


@transaction.atomic
def asignar_cobro(*, venta, cobro_id, cuota_id, usuario):
    venta = Venta.objects.select_for_update().get(pk=venta.pk, empresa=venta.empresa)
    if usuario is None or not usuario.is_authenticated or not usuario.pk:
        raise VentaError("La asignación necesita un usuario autenticado.")
    if venta.estado != Venta.Estado.CONFIRMADA or venta.condicion != Venta.Condicion.CREDITO or venta.moneda != "PEN":
        raise VentaError("Solo se asignan cobros de ventas al crédito confirmadas en soles.")
    cobro = CobroVenta.objects.select_for_update().filter(pk=cobro_id, venta=venta).first()
    cuota = CuotaVenta.objects.select_for_update().filter(pk=cuota_id, venta=venta).first()
    if cobro is None or cuota is None:
        raise VentaError("El cobro o la cuota no pertenecen a esta venta.")
    cuenta = CuentaTesoreria.objects.select_for_update().get(pk=cobro.cuenta_id)
    Empresa.objects.select_for_update().get(pk=venta.empresa_id)
    if cuenta.empresa_id != venta.empresa_id or not cuenta.cuenta_contable_id:
        raise VentaError("La cuenta vinculada al cobro necesita revisión.")
    if cobro.cuota_id:
        if cobro.cuota_id == cuota.pk:
            return False
        raise VentaError("Este cobro ya tiene otra cuota asignada y no se puede cambiar aquí.")
    if venta.notas_credito.exists() or venta.notas_debito.exists():
        raise VentaError("La venta tiene notas; la asignación necesita revisión antes de continuar.")
    if MovimientoTesoreria.objects.filter(
        empresa=venta.empresa, origen_tipo="VENTA", origen_id=venta.pk, tipo="INGRESO",
    ).exists():
        raise VentaError("La venta tiene un cobro histórico adicional que necesita revisión.")
    movimientos = list(MovimientoTesoreria.objects.filter(
        empresa=venta.empresa, origen_tipo="COBRO_VENTA", origen_id=cobro.pk,
    ))
    if (len(movimientos) != 1 or movimientos[0].tipo != "INGRESO"
            or movimientos[0].cuenta_id != cobro.cuenta_id or movimientos[0].fecha != cobro.fecha
            or movimientos[0].importe != cobro.importe or movimientos[0].canal != cobro.canal):
        raise VentaError("El movimiento de este cobro necesita revisión antes de asignarlo.")
    asientos = list(Asiento.objects.filter(
        empresa=venta.empresa, origen_tipo="COBRO_VENTA", origen_id=cobro.pk,
    ).select_related("periodo").prefetch_related("lineas__cuenta"))
    if (len(asientos) != 1 or asientos[0].estado != Asiento.Estado.CONFIRMADO
            or asientos[0].tipo_operacion != "COBRO_CLIENTE" or asientos[0].fecha != cobro.fecha):
        raise VentaError("El asiento de este cobro necesita revisión antes de asignarlo.")
    asiento = asientos[0]
    if (asiento.periodo.empresa_id != venta.empresa_id or asiento.periodo.anio != cobro.fecha.year
            or asiento.periodo.mes != cobro.fecha.month):
        raise VentaError("El período del asiento necesita revisión antes de asignar el cobro.")
    if asiento.periodo.estado == Periodo.Estado.CERRADO:
        raise VentaError("El período del cobro está cerrado; la asignación requiere revisión.")
    recibido = sum((linea.debe - linea.haber for linea in asiento.lineas.all()
                    if linea.cuenta_id == cuenta.cuenta_contable_id), Decimal("0"))
    cancelado = sum((linea.haber - linea.debe for linea in asiento.lineas.all()
                     if linea.cuenta.version == "2026" and linea.cuenta.codigo == "1212"), Decimal("0"))
    if recibido != cobro.importe or cancelado != cobro.importe:
        raise VentaError("Los importes contables de este cobro necesitan revisión.")
    asignado = cuota.cobros_asignados.aggregate(total=Sum("importe"))["total"] or Decimal("0")
    if cobro.importe > cuota.importe - asignado:
        raise VentaError("El cobro supera el importe disponible de esta cuota; no se divide automáticamente.")
    cobro.cuota = cuota
    cobro.save(update_fields=["cuota"])
    HistorialDocumento.objects.create(
        empresa=venta.empresa, tipo=HistorialDocumento.Tipo.VENTA, documento_id=venta.pk,
        usuario=usuario, accion="ASIGNAR_CUOTA",
        detalle=f"Cobro del {cobro.fecha} por S/ {cobro.importe} asignado a la cuota {cuota.numero}.",
    )
    return True

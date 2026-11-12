"""Saldos y cobros de ventas al crédito, sin modificar documentos históricos."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Sum

from catalogo.models import CuentaTesoreria
from core.models import HistorialDocumento
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import registrar

from .models import CobroVenta, CuotaVenta, Venta
from .servicios import VentaError


def saldo_pendiente(venta):
    """Saldo documentado, descontando cobros y movimientos históricos.

    Un ``MovimientoTesoreria`` con ``origen_tipo="VENTA"`` es dinero que entró
    por la venta antes de que existiera el vínculo con cuotas. No se puede
    ignorar: se descuenta del saldo, pero no se confunde con un ``CobroVenta``
    (esos movimientos usan ``origen_tipo="COBRO_VENTA"``).
    """

    def suma(qs, campo="total"):
        return qs.aggregate(total=Sum(campo))["total"] or Decimal("0")

    cobrado = suma(venta.cobros, "importe")
    historico = suma(
        MovimientoTesoreria.objects.filter(
            empresa=venta.empresa,
            origen_tipo="VENTA",
            origen_id=venta.pk,
            tipo="INGRESO",
        ),
        "importe",
    )
    return (
        venta.total
        + suma(venta.notas_debito)
        - suma(venta.notas_credito)
        - cobrado
        - historico
    )


@transaction.atomic
def registrar_cobro_formulario(*, venta, operacion, usuario, **datos):
    """El mismo envío web no debe registrar dos cobros de una venta."""
    from uuid import UUID

    if not isinstance(operacion, UUID):
        raise VentaError("La operación no es válida. Vuelve a abrir el formulario de cobro.")
    venta = Venta.objects.select_for_update().get(pk=venta.pk, empresa=venta.empresa)
    identificacion = f"Operación: {operacion}"
    if HistorialDocumento.objects.filter(
        empresa=venta.empresa, tipo=HistorialDocumento.Tipo.VENTA, documento_id=venta.pk,
        accion="COBRO", detalle__endswith=identificacion,
    ).exists():
        return False
    cobro = cobrar_venta(venta=venta, usuario=usuario, **datos)
    HistorialDocumento.objects.create(
        empresa=venta.empresa, tipo=HistorialDocumento.Tipo.VENTA, documento_id=venta.pk,
        usuario=usuario, accion="COBRO",
        detalle=(f"Cobro de S/ {datos.get('importe', cobro.importe)} el {cobro.fecha}"
                 f"{f', cuota {cobro.cuota.numero}' if cobro.cuota_id else ', sin cuota asignada'}. {identificacion}"),
    )
    return True


@transaction.atomic
def cobrar_venta(
    *,
    venta,
    fecha,
    importe,
    cuenta,
    canal,
    usuario=None,
    cuota=None,
    asignar_automaticamente=True,
):
    """Registra un cobro; si no se indica cuota, la reparte FIFO entre cuotas.

    ``asignar_automaticamente=False`` deja el cobro sin cuota para asignarlo
    después a mano (comportamiento anterior).
    """
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
    saldo = saldo_pendiente(venta)
    if importe > saldo:
        raise VentaError(f"El importe excede el saldo pendiente de S/ {max(saldo, Decimal('0')):.2f}.")
    creados = []
    if cuota is not None:
        cuota = CuotaVenta.objects.select_for_update().filter(pk=cuota.pk, venta=venta).first()
        if cuota is None:
            raise VentaError("La cuota no pertenece a esta venta.")
        if (venta.cobros.filter(cuota__isnull=True).exists()
                or venta.notas_credito.exists() or venta.notas_debito.exists()):
            raise VentaError("Hay cobros sin asignar o notas que requieren revisión antes de asignar cuotas.")
        asignado = cuota.cobros_asignados.aggregate(total=Sum("importe"))["total"] or Decimal("0")
        if importe > cuota.importe - asignado:
            raise VentaError("El cobro supera el importe disponible para asignar a esta cuota.")
        creados.append(
            CobroVenta.objects.create(
                venta=venta, fecha=fecha, importe=importe, cuenta=cuenta,
                canal=canal, creado_por=usuario, cuota=cuota,
            )
        )
    elif (
        asignar_automaticamente
        and not venta.notas_credito.exists()
        and not venta.notas_debito.exists()
        and not venta.cobros.filter(cuota__isnull=True).exists()
        and venta.cuotas.exists()
    ):
        resto = importe
        cuotas = CuotaVenta.objects.select_for_update().filter(venta=venta).order_by(
            "vencimiento", "numero"
        )
        for pendiente in cuotas:
            if resto <= 0:
                break
            asignado = pendiente.cobros_asignados.aggregate(total=Sum("importe"))["total"] or Decimal("0")
            disponible = pendiente.importe - asignado
            if disponible <= 0:
                continue
            parte = min(resto, disponible)
            creados.append(
                CobroVenta.objects.create(
                    venta=venta, fecha=fecha, importe=parte, cuenta=cuenta,
                    canal=canal, creado_por=usuario, cuota=pendiente,
                )
            )
            resto -= parte
        if resto > 0:
            creados.append(
                CobroVenta.objects.create(
                    venta=venta, fecha=fecha, importe=resto, cuenta=cuenta,
                    canal=canal, creado_por=usuario, cuota=None,
                )
            )
    else:
        creados.append(
            CobroVenta.objects.create(
                venta=venta, fecha=fecha, importe=importe, cuenta=cuenta,
                canal=canal, creado_por=usuario, cuota=None,
            )
        )
    cobro = creados[0]
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

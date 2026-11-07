"""Liquidación explícita de provisiones respaldadas por un asiento vigente."""

from decimal import Decimal

from contabilidad.models import Asiento, Cuenta
from contabilidad.servicios import postear_lineas
from core.contexto import usuario_actual
from core.models import HistorialDocumento
from tesoreria.models import MovimientoTesoreria

from .models_gasto import Gasto


def preparar_provisiones(*, empresa, proveedor, fecha, igv, total, ids):
    from .servicios import CompraError

    ids = list(ids)
    if not ids:
        return []
    if len(ids) != len(set(ids)) or igv != 0:
        raise CompraError("La liquidación solo admite provisiones distintas y comprobantes sin IGV.")
    provisiones = list(Gasto.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if len(provisiones) != len(ids):
        raise CompraError("No se encontraron todas las provisiones seleccionadas.")
    for item in provisiones:
        if (item.empresa_id != empresa.pk or item.proveedor_id != proveedor.pk
                or not item.provision or item.estado != Gasto.Estado.PROVISION
                or item.gasto_origen_id or item.fecha_periodo > fecha or item.igv != 0
                or item.total <= 0):
            raise CompraError(
                "Revisa que las provisiones estén pendientes, sean del mismo proveedor "
                "y anteriores al comprobante, sin IGV."
            )
        asientos = list(Asiento.objects.filter(
            empresa=empresa, origen_tipo="GASTO", origen_id=item.pk,
            tipo_operacion="PROVISION_GASTO", estado=Asiento.Estado.CONFIRMADO,
        ).prefetch_related("lineas__cuenta"))
        if len(asientos) != 1 or asientos[0].fecha > fecha:
            raise CompraError(
                "La provisión necesita un único asiento vigente anterior al comprobante; revisa su contabilidad."
            )
        saldo = sum((linea.haber - linea.debe for linea in asientos[0].lineas.all()
                     if linea.cuenta.codigo == "4212"), Decimal("0"))
        if saldo != item.total:
            raise CompraError("La cuenta por pagar de una provisión no coincide con su importe.")
    if sum((item.total for item in provisiones), Decimal("0")) != total:
        raise CompraError("Las provisiones seleccionadas deben sumar exactamente el total del comprobante.")
    return provisiones


def liquidar_provisiones(*, gasto, provisiones, medio):
    cuenta = Cuenta.objects.get(version="2026", codigo="4212")
    postear_lineas(
        empresa=gasto.empresa, fecha=gasto.fecha, tipo="PAGO_PROVEEDOR",
        glosa=f"Liquidación de provisiones · {gasto.proveedor.nombre}"[:255],
        lineas=[(cuenta, gasto.total, Decimal("0"), "Cancelación de provisiones"),
                (medio.cuenta_contable, Decimal("0"), gasto.total, "Salida de dinero")],
        origen_tipo="GASTO", origen_id=gasto.pk,
    )
    for item in provisiones:
        item.gasto_origen = gasto
        item.save(update_fields=["gasto_origen"])
        HistorialDocumento.objects.create(
            empresa=gasto.empresa, tipo=HistorialDocumento.Tipo.GASTO,
            documento_id=item.pk, usuario=usuario_actual.get(), accion="LIQUIDACION",
            detalle=f"Liquidada mediante el gasto {gasto.pk} por {item.total}.",
        )


def validar_provisiones_vinculadas(*, gasto, provisiones):
    """Verifica el respaldo de una deuda vinculada sin suponer pagos históricos."""
    from .servicios import CompraError

    if not provisiones or gasto.provision or gasto.igv != 0:
        raise CompraError("Las provisiones vinculadas necesitan revisión antes del pago.")
    for item in provisiones:
        if (item.empresa_id != gasto.empresa_id or item.proveedor_id != gasto.proveedor_id
                or not item.provision or item.gasto_origen_id != gasto.pk
                or item.estado != Gasto.Estado.PROVISION or item.igv != 0
                or item.fecha_periodo > gasto.fecha or item.total <= 0):
            raise CompraError("Una provisión vinculada no corresponde al comprobante.")
        if not HistorialDocumento.objects.filter(
            empresa=gasto.empresa, tipo="GASTO", documento_id=item.pk,
            accion="PROVISION", detalle__startswith="Operación: ",
        ).exists():
            raise CompraError("Una provisión no tiene el respaldo necesario para este flujo.")
        asientos = list(Asiento.objects.filter(
            empresa=gasto.empresa, origen_tipo="GASTO", origen_id=item.pk,
        ).prefetch_related("lineas__cuenta"))
        if (len(asientos) != 1 or asientos[0].estado != Asiento.Estado.CONFIRMADO
                or asientos[0].tipo_operacion != "PROVISION_GASTO" or asientos[0].fecha > gasto.fecha):
            raise CompraError("El asiento de una provisión necesita revisión.")
        saldo = sum((linea.haber - linea.debe for linea in asientos[0].lineas.all()
                     if linea.cuenta.version == "2026" and linea.cuenta.codigo == "4212"), Decimal("0"))
        if saldo != item.total or MovimientoTesoreria.objects.filter(
            empresa=gasto.empresa, origen_tipo="GASTO", origen_id=item.pk,
        ).exists():
            raise CompraError("La deuda o los movimientos de una provisión necesitan revisión.")
    if sum((item.total for item in provisiones), Decimal("0")) != gasto.total:
        raise CompraError("Las provisiones vinculadas no suman el total del comprobante.")

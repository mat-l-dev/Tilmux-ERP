"""Gastos con comprobante pendiente de pago, y sus pagos identificables."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.db.models import Sum

from catalogo.models import CuentaTesoreria
from contabilidad.models import Asiento, Cuenta
from contabilidad.servicios import periodo_de, postear_lineas
from core.models import Empresa, HistorialDocumento
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import anotar

from .comprobantes import ruc_valido
from .liquidacion import preparar_provisiones, validar_provisiones_vinculadas
from .models_gasto import Gasto, PagoGasto
from .servicios import CompraError, validar_comprobante


def importe_valido(valor, *, permite_cero=False):
    try:
        importe = Decimal(str(valor))
        if (not importe.is_finite() or importe != importe.quantize(Decimal("0.01"))
                or importe >= Decimal("10000000000000000")
                or importe < 0 or (not permite_cero and importe == 0)):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise CompraError("Indica un importe válido en soles, con hasta dos decimales.") from None
    return importe


@transaction.atomic
def registrar_pendiente(*, empresa, proveedor, fecha, tipo_doc, serie, numero, base, igv,
                        cuenta, glosa, con_credito, deducible, usuario, provisiones=(), confirma_base_provision=False):
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    serie, numero = serie.strip().upper(), numero.strip()
    if tipo_doc not in (Gasto.TipoDoc.FACTURA, Gasto.TipoDoc.BOLETA) or not serie or not numero:
        raise CompraError("Indica una factura o boleta con serie y número.")
    if not proveedor.activo or proveedor.rol not in ("PROVEEDOR", "AMBOS"):
        raise CompraError("Selecciona un proveedor activo.")
    if tipo_doc == Gasto.TipoDoc.FACTURA and not ruc_valido(proveedor):
        raise CompraError("La factura requiere un proveedor con RUC de 11 dígitos.")
    if con_credito and tipo_doc != Gasto.TipoDoc.FACTURA:
        raise CompraError("Solo una factura puede marcarse con crédito fiscal.")
    if not cuenta.activa or not cuenta.admite_movimiento or cuenta.elemento != 6 or cuenta.version != "2026":
        raise CompraError("Selecciona una cuenta de gasto activa.")
    if not glosa.strip():
        raise CompraError("Describe el gasto.")
    base, igv = importe_valido(base), importe_valido(igv, permite_cero=True)
    total = importe_valido(base + igv)
    validar_comprobante(empresa=empresa, proveedor=proveedor, tipo_doc=tipo_doc, serie=serie, numero=numero)
    if provisiones and igv and (not con_credito or tipo_doc != Gasto.TipoDoc.FACTURA
                                or len(provisiones) != 1 or not confirma_base_provision):
        raise CompraError("La liquidación solo admite una provisión por la base de una factura "
                          "con crédito fiscal confirmado.")
    provisiones = preparar_provisiones(
        empresa=empresa, proveedor=proveedor, fecha=fecha, igv=igv, total=base if igv else total,
        permite_igv=bool(igv),
        ids=[item.pk for item in provisiones],
    )
    cuentas = {c.codigo: c for c in Cuenta.objects.filter(version="2026", codigo__in=["4211", "4212", "40111"])}
    if "4212" not in cuentas or (con_credito and igv and "40111" not in cuentas):
        raise CompraError("Faltan cuentas contables necesarias para registrar el gasto.")
    gasto = Gasto.objects.create(
        empresa=empresa, proveedor=proveedor, fecha=fecha, fecha_devengado=None if provisiones else fecha,
        tipo_doc=tipo_doc, serie=serie, numero=numero, base=base, igv=igv, total=total,
        cuenta=cuenta, glosa=glosa.strip(), con_credito=con_credito, deducible=deducible,
        estado=Gasto.Estado.REGISTRADO, creado_por=usuario,
    )
    if provisiones:
        periodo_de(empresa, fecha)
        for provision in provisiones:
            provision.gasto_origen = gasto
            provision.save(update_fields=["gasto_origen"])
        sin_comprobante = validar_provisiones_vinculadas(
            gasto=gasto, provisiones=provisiones, exigir_reclasificacion=False,
        )
        if sin_comprobante or igv:
            if "4211" not in cuentas:
                raise CompraError("Falta la cuenta contable de comprobantes no emitidos.")
            lineas = []
            if sin_comprobante:
                lineas.append((cuentas["4211"], sin_comprobante, Decimal("0"), "Deuda sin comprobante"))
            if igv:
                lineas.append((cuentas["40111"], igv, Decimal("0"), "IGV de la factura"))
            lineas.append((cuentas["4212"], Decimal("0"), sin_comprobante + igv, "Deuda documentada"))
            postear_lineas(
                empresa=empresa, fecha=fecha, tipo="PROVISION_GASTO", usuario=usuario,
                glosa=f"Comprobante recibido {serie}-{numero}",
                lineas=lineas,
                origen_tipo="GASTO_RECLAS_PROV", origen_id=gasto.pk,
            )
        validar_provisiones_vinculadas(gasto=gasto, provisiones=provisiones)
        for provision in provisiones:
            HistorialDocumento.objects.create(
                empresa=empresa, tipo="GASTO", documento_id=provision.pk, usuario=usuario,
                accion="VINCULACION", detalle=f"Vinculada al comprobante {serie}-{numero}, pendiente de pago.",
            )
        HistorialDocumento.objects.create(
            empresa=empresa, tipo="GASTO", documento_id=gasto.pk, usuario=usuario,
            accion="DEUDA_PROVISION", detalle="Comprobante vinculado a provisiones; pendiente de pago.",
        )
    else:
        cero = Decimal("0")
        lineas = [(cuenta, base if con_credito else total, cero, "Gasto")]
        if con_credito and igv:
            lineas.append((cuentas["40111"], igv, cero, "IGV"))
        lineas.append((cuentas["4212"], cero, total, "Cuenta por pagar"))
        postear_lineas(empresa=empresa, fecha=fecha, tipo="PROVISION_GASTO", glosa=glosa,
                       lineas=lineas, origen_tipo="GASTO_PENDIENTE", origen_id=gasto.pk, usuario=usuario)
    HistorialDocumento.objects.create(empresa=empresa, tipo="GASTO", documento_id=gasto.pk,
                                      usuario=usuario, accion="REGISTRO", detalle="Gasto pendiente de pago.")
    return gasto


@transaction.atomic
def pagar_gasto(*, empresa, gasto_id, fecha, importe, cuenta, canal, operacion, usuario):
    if not isinstance(operacion, UUID):
        raise CompraError("Identificador de operación inválido.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    gasto = Gasto.objects.select_for_update().get(pk=gasto_id, empresa=empresa)
    anterior = PagoGasto.objects.filter(operacion=operacion).first()
    if anterior:
        if anterior.gasto_id != gasto.pk:
            raise CompraError("La operación ya corresponde a otro gasto.")
        return anterior, False
    origen = Asiento.objects.filter(empresa=empresa, origen_tipo="GASTO_PENDIENTE", origen_id=gasto.pk,
                                    estado=Asiento.Estado.CONFIRMADO)
    marca_provision = HistorialDocumento.objects.filter(
        empresa=empresa, tipo="GASTO", documento_id=gasto.pk, accion="DEUDA_PROVISION",
    ).count()
    if (gasto.provision or gasto.estado != Gasto.Estado.REGISTRADO
            or (origen.count(), marca_provision) not in ((1, 0), (0, 1))):
        raise CompraError("Este gasto no admite pagos desde este flujo.")
    if MovimientoTesoreria.objects.filter(empresa=empresa, origen_tipo="GASTO", origen_id=gasto.pk).exists():
        raise CompraError("El gasto tiene un movimiento anterior que debe revisarse.")
    pagos = gasto.pagos.all()
    if marca_provision:
        provisiones = list(gasto.provisiones.select_for_update().order_by("pk"))
        validar_provisiones_vinculadas(gasto=gasto, provisiones=provisiones)
    else:
        lineas_deuda = origen.get().lineas.filter(cuenta__version="2026", cuenta__codigo="4212")
        totales = lineas_deuda.aggregate(debe=Sum("debe"), haber=Sum("haber"))
        if (totales["haber"] or Decimal("0")) - (totales["debe"] or Decimal("0")) != gasto.total:
            raise CompraError("El asiento original de la deuda necesita revisión.")
    for pago_anterior in pagos:
        if (Asiento.objects.filter(empresa=empresa, origen_tipo="PAGO_GASTO", origen_id=pago_anterior.pk,
                                   estado=Asiento.Estado.CONFIRMADO).count() != 1
                or MovimientoTesoreria.objects.filter(empresa=empresa, origen_tipo="PAGO_GASTO",
                                                      origen_id=pago_anterior.pk).count() != 1):
            raise CompraError("Un pago anterior necesita revisión contable antes de registrar otro.")
    ultimo = pagos.order_by("-fecha").first()
    if fecha < gasto.fecha or (ultimo and fecha < ultimo.fecha):
        raise CompraError("La fecha no puede ser anterior al comprobante ni al último pago.")
    if cuenta.empresa_id != empresa.pk or not cuenta.activa or cuenta.moneda != "PEN" or not cuenta.cuenta_contable_id:
        raise CompraError("Selecciona una cuenta activa en soles de la empresa.")
    if canal not in CuentaTesoreria.Canal.values:
        raise CompraError("Selecciona un canal de pago válido.")
    importe = importe_valido(importe)
    saldo = gasto.total - (pagos.aggregate(total=Sum("importe"))["total"] or Decimal("0"))
    if importe > saldo:
        raise CompraError("El pago supera el saldo pendiente.")
    cuenta_pagar = Cuenta.objects.get(version="2026", codigo="4212")
    pago = PagoGasto.objects.create(gasto=gasto, fecha=fecha, importe=importe, cuenta=cuenta,
                                    operacion=operacion, creado_por=usuario)
    postear_lineas(empresa=empresa, fecha=fecha, tipo="PAGO_PROVEEDOR", glosa=f"Pago {gasto.serie}-{gasto.numero}",
                   lineas=[(cuenta_pagar, importe, Decimal("0"), "Pago de obligación"),
                           (cuenta.cuenta_contable, Decimal("0"), importe, "Salida de fondos")],
                   origen_tipo="PAGO_GASTO", origen_id=pago.pk, usuario=usuario)
    anotar(empresa=empresa, cuenta=cuenta, fecha=fecha, tipo="EGRESO", importe=importe,
           concepto=f"Pago {gasto.serie}-{gasto.numero}", canal=canal, origen_tipo="PAGO_GASTO", origen_id=pago.pk)
    if importe == saldo:
        gasto.estado = Gasto.Estado.PAGADO
        gasto.save(update_fields=["estado"])
    HistorialDocumento.objects.create(empresa=empresa, tipo="GASTO", documento_id=gasto.pk,
                                      usuario=usuario, accion="PAGO", detalle=f"Pago de S/ {importe} el {fecha}.")
    return pago, True

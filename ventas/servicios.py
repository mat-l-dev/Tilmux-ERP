"""Confirmación de ventas, notas de crédito y conversión de cotizaciones."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from contabilidad.servicios import Montos, postear
from inventario.servicios import entrar, salir
from tesoreria.servicios import registrar

from .models import Cotizacion, NotaCredito, Venta, VentaLinea

CENT = Decimal("0.01")
LIMITE_IDENTIFICACION = Decimal("700.00")


class VentaError(Exception):
    pass


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def confirmar(venta: Venta) -> Venta:
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.BORRADOR:
        raise VentaError("Solo se confirma una venta en borrador.")

    lineas = list(venta.lineas.select_related("producto"))
    if not lineas:
        raise VentaError("La venta no tiene líneas.")

    base = _cent(sum((l.base for l in lineas), Decimal("0")))
    igv = _cent(sum((l.igv for l in lineas), Decimal("0")))
    total = base + igv

    if venta.tipo_doc == Venta.TipoDoc.FACTURA:
        if venta.cliente is None or venta.cliente.tipo_doc != "RUC":
            raise VentaError("Una factura exige cliente con RUC.")
    if (
        venta.tipo_doc == Venta.TipoDoc.BOLETA
        and total > LIMITE_IDENTIFICACION
        and venta.cliente is None
    ):
        raise VentaError(
            "Una boleta mayor a S/ 700 debe identificar al comprador con DNI."
        )
    if venta.condicion == Venta.Condicion.CONTADO and venta.cuenta is None:
        raise VentaError("Una venta al contado necesita una cuenta de tesorería.")

    costo_venta = Decimal("0")
    for linea in lineas:
        movimiento = salir(
            empresa=venta.empresa,
            producto=linea.producto,
            fecha=venta.fecha,
            cantidad=linea.cantidad,
            origen_tipo="VENTA",
            origen_id=venta.pk,
            glosa=f"Venta {venta.serie}-{venta.numero}",
        )
        linea.costo_unitario = movimiento.costo_unitario
        linea.costo_total = movimiento.costo_total
        linea.save(update_fields=["costo_unitario", "costo_total"])
        costo_venta += movimiento.costo_total

    venta.subtotal = base
    venta.igv = igv
    venta.total = total
    venta.costo_venta = _cent(costo_venta)
    venta.estado = Venta.Estado.CONFIRMADA
    venta.confirmada_en = timezone.now()
    venta.save(
        update_fields=[
            "subtotal",
            "igv",
            "total",
            "costo_venta",
            "estado",
            "confirmada_en",
        ]
    )

    postear(
        empresa=venta.empresa,
        fecha=venta.fecha,
        tipo="VENTA",
        glosa=f"Venta {venta.serie}-{venta.numero}",
        montos=Montos(base=base, igv=igv, total=total, costo=venta.costo_venta),
        origen_tipo="VENTA",
        origen_id=venta.pk,
    )

    if venta.condicion == Venta.Condicion.CONTADO:
        registrar(
            empresa=venta.empresa,
            cuenta=venta.cuenta,
            fecha=venta.fecha,
            tipo="INGRESO",
            importe=total,
            concepto=f"Cobro venta {venta.serie}-{venta.numero}",
            canal=venta.canal,
            origen_tipo="VENTA",
            origen_id=venta.pk,
        )

    return venta


@transaction.atomic
def emitir_nota_credito(
    *,
    venta: Venta,
    fecha: date,
    serie: str,
    numero: str,
    motivo: str,
    reingresa_stock: bool = True,
) -> NotaCredito:
    venta = Venta.objects.get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA:
        raise VentaError("Solo se acredita una venta confirmada.")

    if reingresa_stock:
        for linea in venta.lineas.select_related("producto"):
            entrar(
                empresa=venta.empresa,
                producto=linea.producto,
                fecha=fecha,
                cantidad=linea.cantidad,
                costo_unitario=linea.costo_unitario,
                origen_tipo="NOTA_CREDITO",
                origen_id=venta.pk,
                glosa=f"Devolución {serie}-{numero}",
            )

    nota = NotaCredito.objects.create(
        venta=venta,
        fecha=fecha,
        serie=serie,
        numero=numero,
        motivo=motivo[:200],
        base=venta.subtotal,
        igv=venta.igv,
        total=venta.total,
        costo=venta.costo_venta,
        reingresa_stock=reingresa_stock,
    )

    postear(
        empresa=venta.empresa,
        fecha=fecha,
        tipo="NOTA_CREDITO",
        glosa=f"Nota de crédito {serie}-{numero}",
        montos=Montos(
            base=venta.subtotal,
            igv=venta.igv,
            total=venta.total,
            costo=venta.costo_venta,
        ),
        origen_tipo="NOTA_CREDITO",
        origen_id=nota.pk,
    )
    return nota


@transaction.atomic
def convertir_cotizacion(
    cotizacion: Cotizacion, *, fecha: date, tipo_doc: str, serie: str, numero: str
) -> Venta:
    if cotizacion.estado == Cotizacion.Estado.CONVERTIDA:
        raise VentaError("La cotización ya fue convertida.")

    venta = Venta.objects.create(
        empresa=cotizacion.empresa,
        cliente=cotizacion.cliente,
        cliente_nombre=cotizacion.cliente_nombre,
        fecha=fecha,
        tipo_doc=tipo_doc,
        serie=serie,
        numero=numero,
        cotizacion=cotizacion,
        glosa=cotizacion.glosa,
    )
    for linea in cotizacion.lineas.all():
        VentaLinea.objects.create(
            venta=venta,
            orden=linea.orden,
            producto=linea.producto,
            descripcion=linea.descripcion,
            cantidad=linea.cantidad,
            precio_unitario=linea.precio_unitario,
            base=linea.base,
            igv=linea.igv,
            total=linea.total,
        )
    cotizacion.estado = Cotizacion.Estado.CONVERTIDA
    cotizacion.save(update_fields=["estado"])
    return venta

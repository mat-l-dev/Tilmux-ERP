"""Confirmación de ventas, notas de crédito y conversión de cotizaciones."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from contabilidad.servicios import Montos, postear
from inventario.servicios import entrar, salir
from tesoreria.servicios import registrar

from .models import (
    Cotizacion,
    NotaCredito,
    NotaCreditoLinea,
    NotaDebito,
    Venta,
    VentaLinea,
)

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
    motivo_codigo: str,
    cantidades: dict | None = None,
    reingresa_stock: bool = True,
    descripcion: str = "",
) -> NotaCredito:
    """Emite una nota de crédito total o por ítem, según las cantidades."""
    venta = Venta.objects.get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA:
        raise VentaError("Solo se acredita una venta confirmada.")

    lineas = list(venta.lineas.select_related("producto"))
    if not lineas:
        raise VentaError("La venta no tiene líneas.")

    if cantidades is None:
        cantidades = {linea.pk: linea.cantidad for linea in lineas}

    acreditado = {
        fila["venta_linea_id"]: fila["total"]
        for fila in NotaCreditoLinea.objects.filter(nota__venta=venta)
        .values("venta_linea_id")
        .annotate(total=Sum("cantidad"))
    }

    seleccion = []
    base_total = Decimal("0.00")
    igv_total = Decimal("0.00")
    costo_total = Decimal("0.00")

    for linea in lineas:
        pedida = Decimal(cantidades.get(linea.pk, 0) or 0)
        if pedida <= 0:
            continue
        disponible = linea.cantidad - acreditado.get(linea.pk, Decimal("0"))
        if pedida > disponible:
            raise VentaError(
                f"No puedes acreditar {pedida} de {linea.producto.sku}: "
                f"solo quedan {disponible}."
            )
        proporcion = pedida / linea.cantidad
        base = (linea.base * proporcion).quantize(CENT)
        igv = (linea.igv * proporcion).quantize(CENT)
        costo = (linea.costo_total * proporcion).quantize(CENT)
        seleccion.append((linea, pedida, base, igv, base + igv, costo))
        base_total += base
        igv_total += igv
        costo_total += costo

    if not seleccion:
        raise VentaError("No indicaste ninguna cantidad a acreditar.")

    nota = NotaCredito.objects.create(
        venta=venta,
        fecha=fecha,
        serie=serie,
        numero=numero,
        motivo=(descripcion or dict(NotaCredito.Motivo.choices)[motivo_codigo])[:200],
        motivo_codigo=motivo_codigo,
        base=base_total,
        igv=igv_total,
        total=base_total + igv_total,
        costo=costo_total,
        reingresa_stock=reingresa_stock,
    )

    for linea, pedida, base, igv, total, costo in seleccion:
        NotaCreditoLinea.objects.create(
            nota=nota,
            venta_linea=linea,
            cantidad=pedida,
            base=base,
            igv=igv,
            total=total,
            costo_total=costo,
        )
        if reingresa_stock:
            entrar(
                empresa=venta.empresa,
                producto=linea.producto,
                fecha=fecha,
                cantidad=pedida,
                costo_unitario=linea.costo_unitario,
                origen_tipo="NOTA_CREDITO",
                origen_id=nota.pk,
                glosa=f"Devolución {serie}-{numero}",
            )

    postear(
        empresa=venta.empresa,
        fecha=fecha,
        tipo="NOTA_CREDITO",
        glosa=f"Nota de crédito {serie}-{numero}",
        montos=Montos(
            base=base_total,
            igv=igv_total,
            total=base_total + igv_total,
            costo=costo_total,
        ),
        origen_tipo="NOTA_CREDITO",
        origen_id=nota.pk,
    )
    return nota


@transaction.atomic
def emitir_nota_debito(
    *,
    venta: Venta,
    fecha: date,
    serie: str,
    numero: str,
    motivo_codigo: str,
    base: Decimal,
    igv: Decimal,
    descripcion: str = "",
) -> NotaDebito:
    """Nota de débito: aumenta el importe del comprobante original."""
    venta = Venta.objects.get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA:
        raise VentaError("Solo se debita una venta confirmada.")

    base, igv = _cent(base), _cent(igv)
    total = base + igv
    if total <= 0:
        raise VentaError("La nota de débito debe tener un importe mayor a cero.")

    nota = NotaDebito.objects.create(
        venta=venta,
        fecha=fecha,
        serie=serie,
        numero=numero,
        motivo_codigo=motivo_codigo,
        descripcion=descripcion[:200],
        base=base,
        igv=igv,
        total=total,
    )

    postear(
        empresa=venta.empresa,
        fecha=fecha,
        tipo="NOTA_DEBITO",
        glosa=f"Nota de débito {serie}-{numero}",
        montos=Montos(base=base, igv=igv, total=total),
        origen_tipo="NOTA_DEBITO",
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

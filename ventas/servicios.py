"""Confirmación de ventas, notas de crédito y conversión de cotizaciones."""

from __future__ import annotations

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Trim, Upper
from django.utils import timezone

from catalogo.models import CuentaTesoreria, Serie
from contabilidad.servicios import Montos, postear
from core.models import Empresa
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

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
PRECISION_COSTO = Decimal("0.0000000001")
LIMITE_IDENTIFICACION = Decimal("700.00")
MOTIVOS_CREDITO_IMPLEMENTADOS = frozenset({"01", "06", "07"})


class VentaError(Exception):
    pass


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


def _validar_numeracion_nota(venta: Venta, modelo, serie: str, numero: str) -> tuple[str, str]:
    serie, numero = serie.strip().upper(), numero.strip()
    if not serie or not numero:
        raise VentaError("Indica la serie y el número de la nota.")
    normalizado = (numero.lstrip("0") or "0") if numero.isdecimal() else numero.upper()
    Empresa.objects.select_for_update().get(pk=venta.empresa_id)
    existentes = modelo.objects.filter(venta__empresa_id=venta.empresa_id).annotate(
        serie_normalizada=Upper(Trim("serie"))
    ).filter(serie_normalizada=serie).values_list("numero", flat=True)
    for existente in existentes:
        existente = existente.strip().upper()
        clave = (existente.lstrip("0") or "0") if existente.isdecimal() else existente
        if clave == normalizado:
            raise VentaError(f"La nota {serie}-{numero} ya está registrada para esta empresa.")
    return serie, numero


def _avanzar_serie(venta: Venta) -> None:
    """Mantiene el correlativo de la serie al día, sin tocar comprobantes aceptados."""
    try:
        numero = int(str(venta.numero).strip())
    except (TypeError, ValueError):
        return
    tipo = (
        Serie.Tipo.FACTURA
        if venta.tipo_doc == Venta.TipoDoc.FACTURA
        else Serie.Tipo.BOLETA
    )
    serie, _ = Serie.objects.get_or_create(
        empresa=venta.empresa,
        tipo=tipo,
        serie=venta.serie,
        defaults={"ultimo_numero": 0},
    )
    if numero > serie.ultimo_numero:
        serie.ultimo_numero = numero
        serie.save(update_fields=["ultimo_numero"])


@transaction.atomic
def confirmar(venta: Venta) -> Venta:
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.BORRADOR:
        raise VentaError("Solo se confirma una venta en borrador.")
    if venta.condicion not in Venta.Condicion.values or venta.tipo_doc not in Venta.TipoDoc.values:
        raise VentaError("Revisa el tipo de documento y la condición de pago.")
    Empresa.objects.select_for_update().get(pk=venta.empresa_id)

    lineas = list(venta.lineas.select_related("producto"))
    if not lineas:
        raise VentaError("La venta no tiene líneas.")
    for linea in lineas:
        if linea.cantidad <= 0 or linea.base <= 0 or linea.igv < 0 or linea.total != linea.base + linea.igv:
            raise VentaError("Revisa las líneas: cantidad y base positivas, IGV no negativo y total consistente.")
    if venta.moneda != "PEN":
        raise VentaError("La confirmación de ventas en moneda extranjera aún no está disponible.")

    base = _cent(sum((linea.base for linea in lineas), Decimal("0")))
    igv = _cent(sum((linea.igv for linea in lineas), Decimal("0")))
    total = base + igv

    if venta.condicion == Venta.Condicion.CREDITO:
        from .servicios_cuotas import validar_cuotas

        cuotas = list(venta.cuotas.values("vencimiento", "importe"))
        validar_cuotas(venta, cuotas, total)

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
    if venta.condicion == Venta.Condicion.CONTADO:
        cuenta = CuentaTesoreria.objects.select_for_update().get(pk=venta.cuenta_id)
        if (
            cuenta.empresa_id != venta.empresa_id or not cuenta.activa
            or cuenta.moneda != "PEN" or not cuenta.cuenta_contable_id
        ):
            raise VentaError("Selecciona una cuenta de tesorería activa en soles de la empresa, con cuenta contable.")
        if venta.canal not in CuentaTesoreria.Canal.values:
            raise VentaError("Selecciona un canal de cobro válido.")

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
    _avanzar_serie(venta)

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

    logger.info("venta confirmada %s-%s total=%s", venta.serie, venta.numero, total)
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
    # Serializa las notas de una misma venta antes de comprobar lo acreditado.
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA:
        raise VentaError("Solo se acredita una venta confirmada.")
    if fecha < venta.fecha:
        raise VentaError("La fecha de la nota no puede ser anterior a la venta.")
    if venta.cobros.filter(fecha__gt=fecha).exists():
        raise VentaError("La nota no puede tener una fecha anterior a un cobro registrado.")
    if motivo_codigo not in MOTIVOS_CREDITO_IMPLEMENTADOS:
        raise VentaError("Este motivo de nota de crédito todavía no está implementado.")
    serie, numero = _validar_numeracion_nota(venta, NotaCredito, serie, numero)

    lineas = list(venta.lineas.select_related("producto"))
    if not lineas:
        raise VentaError("La venta no tiene líneas.")

    if cantidades is None:
        cantidades = {linea.pk: linea.cantidad for linea in lineas}

    acreditado = {
        fila["venta_linea_id"]: fila
        for fila in NotaCreditoLinea.objects.filter(nota__venta=venta)
        .values("venta_linea_id")
        .annotate(
            cantidad_acreditada=Sum("cantidad"),
            base_acreditada=Sum("base"),
            igv_acreditado=Sum("igv"),
            costo_reingresado=Sum("costo_total"),
            cantidad_sin_reingreso=Sum("cantidad", filter=Q(nota__reingresa_stock=False)),
        )
    }
    if motivo_codigo in {"01", "06"} and (
        acreditado
        or any(Decimal(cantidades.get(linea.pk, 0) or 0) != linea.cantidad for linea in lineas)
    ):
        raise VentaError("La anulación o devolución total debe cubrir toda la venta sin notas previas.")

    seleccion = []
    base_total = Decimal("0.00")
    igv_total = Decimal("0.00")
    costo_total = Decimal("0.00")

    for linea in lineas:
        pedida = Decimal(cantidades.get(linea.pk, 0) or 0)
        if pedida <= 0:
            continue
        anterior = acreditado.get(linea.pk, {})
        cantidad_anterior = anterior.get("cantidad_acreditada") or Decimal("0")
        disponible = linea.cantidad - cantidad_anterior
        if pedida > disponible:
            raise VentaError(
                f"No puedes acreditar {pedida} de {linea.producto.sku}: "
                f"solo quedan {disponible}."
            )
        proporcion_acumulada = (cantidad_anterior + pedida) / linea.cantidad
        base = (linea.base * proporcion_acumulada).quantize(CENT) - (anterior.get("base_acreditada") or Decimal("0"))
        igv = (linea.igv * proporcion_acumulada).quantize(CENT) - (anterior.get("igv_acreditado") or Decimal("0"))
        costo = Decimal("0.00")
        if reingresa_stock:
            costo_acumulado = (linea.costo_total * proporcion_acumulada).quantize(CENT)
            if anterior.get("cantidad_sin_reingreso"):
                costo_anterior = (linea.costo_total * cantidad_anterior / linea.cantidad).quantize(CENT)
            else:
                costo_anterior = anterior.get("costo_reingresado") or Decimal("0")
            costo = costo_acumulado - costo_anterior
        if base < 0 or igv < 0 or costo < 0:
            raise VentaError("Las notas anteriores exceden el importe proporcional; revisa el historial de la venta.")
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
            costo_unitario = (costo / pedida).quantize(PRECISION_COSTO, rounding=ROUND_HALF_UP)
            if _cent(costo_unitario * pedida) != costo:
                raise VentaError("El costo de la devolución no se puede representar con la precisión disponible.")
            entrar(
                empresa=venta.empresa,
                producto=linea.producto,
                fecha=fecha,
                cantidad=pedida,
                costo_unitario=costo_unitario,
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
    venta = Venta.objects.select_for_update().get(pk=venta.pk)
    if venta.estado != Venta.Estado.CONFIRMADA:
        raise VentaError("Solo se debita una venta confirmada.")
    if fecha < venta.fecha:
        raise VentaError("La fecha de la nota no puede ser anterior a la venta.")
    if venta.cobros.filter(fecha__gt=fecha).exists():
        raise VentaError("La nota no puede tener una fecha anterior a un cobro registrado.")
    serie, numero = _validar_numeracion_nota(venta, NotaDebito, serie, numero)

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

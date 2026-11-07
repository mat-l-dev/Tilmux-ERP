"""Reversión interna y auditable de compras registradas por error."""

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from contabilidad.models import Asiento
from contabilidad.servicios import postear_lineas
from core.models import Empresa, HistorialDocumento, Periodo
from inventario.models import CapaFIFO, ConsumoCapa, MovimientoStock
from tesoreria.models import MovimientoTesoreria

from .models import Compra
from .servicios import CompraError, _cent


@transaction.atomic
def revertir_registro(*, empresa, compra_id, motivo, usuario):
    """Revierte un registro interno erróneo; no registra notas de crédito del proveedor."""
    motivo = (motivo or "").strip()
    if not 10 <= len(motivo) <= 1000:
        raise CompraError("Describe el error con entre 10 y 1000 caracteres.")
    compra = Compra.objects.select_for_update().filter(pk=compra_id, empresa=empresa).first()
    if not compra or compra.estado != Compra.Estado.CONFIRMADA:
        raise CompraError("Solo se puede revertir una compra confirmada de la empresa.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    if compra.moneda != "PEN" or compra.pagada or compra.monto_pagado != 0 or compra.revaluacion != 0:
        raise CompraError("La compra tiene pagos, revaluación o moneda extranjera y requiere otro tratamiento.")
    if (
        MovimientoTesoreria.objects.filter(
            empresa=empresa, origen_tipo__in=["COMPRA", "COMPRA_PAGO"], origen_id=compra.pk
        ).exists()
        or Asiento.objects.filter(
            empresa=empresa, origen_tipo__in=["COMPRA_PAGO", "REVALUACION", "REV_COMPRA"], origen_id=compra.pk
        ).exists()
    ):
        raise CompraError("Existen pagos, revaluaciones o reversiones vinculadas que requieren revisión.")
    if compra.fecha_anotacion and (compra.fecha_anotacion.year, compra.fecha_anotacion.month) != (
        compra.fecha.year,
        compra.fecha.month,
    ):
        raise CompraError("La anotación está en otro período y requiere revisión tributaria.")
    periodos_cerrados = Periodo.objects.filter(empresa=empresa, estado=Periodo.Estado.CERRADO).filter(
        Q(anio__gt=compra.fecha.year) | Q(anio=compra.fecha.year, mes__gte=compra.fecha.month)
    )
    if periodos_cerrados.exists():
        raise CompraError("Hay períodos cerrados desde la fecha de compra; revisa el historial antes de revertir.")
    asientos = list(
        Asiento.objects.filter(
            empresa=empresa,
            origen_tipo="COMPRA",
            origen_id=compra.pk,
            estado=Asiento.Estado.CONFIRMADO,
            tipo_operacion="COMPRA",
            fecha=compra.fecha,
        ).prefetch_related("lineas__cuenta")
    )
    if len(asientos) != 1:
        raise CompraError("La compra necesita exactamente un asiento original vigente para poder revertirse.")
    original = asientos[0]
    lineas = list(original.lineas.all())
    if (
        not lineas
        or sum((linea.debe for linea in lineas), Decimal("0")) != compra.total
        or sum((linea.haber for linea in lineas), Decimal("0")) != compra.total
        or sum((linea.haber - linea.debe for linea in lineas if linea.cuenta.codigo == "4212"), Decimal("0"))
        != compra.total
    ):
        raise CompraError("El asiento original no coincide con el total y la deuda de la compra.")
    if any(linea.monto_contable != linea.monto_tributario or linea.tipo_diferencia != "NINGUNA" for linea in lineas):
        raise CompraError("El asiento contiene diferencias tributarias que requieren revisión manual.")
    capas = list(
        CapaFIFO.objects.select_for_update()
        .filter(empresa=empresa, origen_tipo="COMPRA", origen_id=compra.pk)
        .select_related("producto")
        .order_by("pk")
    )
    if not capas or any(c.cantidad_restante != c.cantidad_inicial for c in capas):
        raise CompraError("El stock original falta o ya fue consumido; no se puede revertir automáticamente.")
    if ConsumoCapa.objects.filter(capa__in=capas).exists():
        raise CompraError("Las capas tienen consumos registrados y requieren revisión de inventario.")
    productos = {c.producto_id for c in capas}
    if MovimientoStock.objects.filter(
        empresa=empresa, producto_id__in=productos, tipo="SALIDA", fecha__gt=compra.fecha
    ).exists():
        raise CompraError("Hay salidas posteriores de los productos; revisa el historial PEPS.")
    cantidades = defaultdict(Decimal)
    for linea in compra.lineas.all():
        cantidades[linea.producto_id] += linea.cantidad
    cantidades_capas = defaultdict(Decimal)
    for capa in capas:
        cantidades_capas[capa.producto_id] += capa.cantidad_inicial
    entradas = MovimientoStock.objects.filter(
        empresa=empresa, origen_tipo="COMPRA", origen_id=compra.pk, tipo="ENTRADA"
    )
    entradas_por_producto = defaultdict(Decimal)
    for entrada in entradas:
        entradas_por_producto[entrada.producto_id] += entrada.cantidad
    if not cantidades or cantidades != cantidades_capas or cantidades != entradas_por_producto:
        raise CompraError("Las líneas, entradas y capas de la compra no coinciden.")
    costo = sum((_cent(c.cantidad_inicial * c.costo_unitario) for c in capas), Decimal("0"))
    costo_asiento = sum(
        (linea.debe - linea.haber for linea in lineas if linea.cuenta.codigo.startswith("20")), Decimal("0")
    )
    if costo != costo_asiento or sum((e.costo_total for e in entradas), Decimal("0")) != costo:
        raise CompraError("El costo de inventario no coincide con el asiento original.")
    inverso = postear_lineas(
        empresa=empresa,
        fecha=compra.fecha,
        tipo="COMPRA",
        glosa=f"Reversión de registro {compra.serie}-{compra.numero}",
        lineas=[(linea.cuenta, linea.haber, linea.debe, "Reversión de registro erróneo") for linea in lineas],
        origen_tipo="REV_COMPRA",
        origen_id=compra.pk,
        usuario=usuario,
    )
    for capa in capas:
        valor = _cent(capa.cantidad_inicial * capa.costo_unitario)
        salida = MovimientoStock.objects.create(
            empresa=empresa,
            producto=capa.producto,
            fecha=compra.fecha,
            tipo="SALIDA",
            cantidad=capa.cantidad_inicial,
            costo_unitario=capa.costo_unitario,
            costo_total=valor,
            origen_tipo="REV_COMPRA",
            origen_id=compra.pk,
            glosa="Reversión de registro erróneo",
        )
        ConsumoCapa.objects.create(
            movimiento=salida,
            capa=capa,
            cantidad=capa.cantidad_inicial,
            costo_unitario=capa.costo_unitario,
            costo_total=valor,
        )
        capa.cantidad_restante = 0
        capa.save(update_fields=["cantidad_restante"])
    compra.estado = Compra.Estado.ANULADA
    compra.save(update_fields=["estado"])
    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo="COMPRA",
        documento_id=compra.pk,
        usuario=usuario,
        accion="REVERSION",
        detalle=f"Registro erróneo: {motivo}. Asiento inverso {inverso.numero}.",
    )
    return compra

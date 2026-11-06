"""Apertura y cierre mensual con historial y bloqueo de la empresa."""

from django.db import transaction

from compras.models import Compra
from contabilidad.impuestos import asentar_renta
from contabilidad.models import Asiento
from contabilidad.servicios import ContabilidadError
from ventas.models import Venta

from .models import Empresa, HistorialDocumento, Periodo


@transaction.atomic
def cerrar_mes(*, empresa, pk, usuario):
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    periodo = Periodo.objects.select_for_update().get(pk=pk, empresa=empresa)
    if periodo.estado != Periodo.Estado.ABIERTO:
        raise ContabilidadError("El período ya está cerrado.")
    filtros = {"empresa": empresa, "fecha__year": periodo.anio, "fecha__month": periodo.mes}
    borradores = Compra.objects.filter(**filtros, estado=Compra.Estado.BORRADOR).count()
    borradores += Venta.objects.filter(**filtros, estado=Venta.Estado.BORRADOR).count()
    if borradores:
        raise ContabilidadError(f"No se puede cerrar: hay {borradores} borrador(es) sin confirmar en ese mes.")
    asentar_renta(empresa, periodo.anio, periodo.mes, usuario=usuario)
    periodo.estado = Periodo.Estado.CERRADO
    periodo.save(update_fields=["estado"])
    HistorialDocumento.objects.create(
        empresa=empresa, tipo=HistorialDocumento.Tipo.PERIODO, documento_id=periodo.pk,
        usuario=usuario, accion="CIERRE", detalle=f"Cierre de {periodo.etiqueta}.",
    )
    return periodo


@transaction.atomic
def reabrir_mes(*, empresa, pk, usuario, motivo):
    if usuario is None or not usuario.is_superuser:
        raise ContabilidadError("Solo el administrador puede reabrir un período.")
    motivo = motivo.strip()
    if not motivo:
        raise ContabilidadError("Indica el motivo de la reapertura.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    periodo = Periodo.objects.select_for_update().get(pk=pk, empresa=empresa)
    if periodo.estado != Periodo.Estado.CERRADO:
        raise ContabilidadError("El período ya está abierto.")
    if Asiento.objects.filter(
        empresa=empresa, origen_tipo="CIERRE", origen_id=periodo.anio, estado=Asiento.Estado.CONFIRMADO,
    ).exists():
        raise ContabilidadError("Revierte primero el cierre anual antes de reabrir un mes del ejercicio.")
    periodo.estado = Periodo.Estado.ABIERTO
    periodo.save(update_fields=["estado"])
    HistorialDocumento.objects.create(
        empresa=empresa, tipo=HistorialDocumento.Tipo.PERIODO, documento_id=periodo.pk,
        usuario=usuario, accion="REAPERTURA", detalle=f"Reapertura de {periodo.etiqueta}. Motivo: {motivo[:1000]}",
    )
    return periodo

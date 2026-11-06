"""Período de anotación tributaria de comprobantes ya registrados."""

from django.db import transaction

from core.models import Empresa, HistorialDocumento, Periodo

from .models import Compra
from .models_gasto import Gasto


class AnotacionError(Exception):
    pass


@transaction.atomic
def cambiar_fecha_anotacion(*, empresa, clase: str, pk: int, fecha, usuario):
    if clase == "compra":
        modelo, tipo = Compra, HistorialDocumento.Tipo.COMPRA
    elif clase == "gasto":
        modelo, tipo = Gasto, HistorialDocumento.Tipo.GASTO
    else:
        raise AnotacionError("Tipo de documento no válido.")
    documento = modelo.objects.select_for_update().filter(pk=pk, empresa=empresa).first()
    if documento is None:
        raise AnotacionError("No se encontró el documento de esta empresa.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    if clase == "compra" and documento.estado != Compra.Estado.CONFIRMADA:
        raise AnotacionError("Solo se anota una compra confirmada.")
    if clase == "gasto" and (documento.provision or documento.estado == Gasto.Estado.ANULADO):
        raise AnotacionError("Una provisión o gasto anulado no se anota como comprobante.")
    if not documento.serie.strip() or not documento.numero.strip():
        raise AnotacionError("El documento necesita serie y número para registrar la anotación.")
    if fecha and (fecha.year, fecha.month) < (documento.fecha.year, documento.fecha.month):
        raise AnotacionError("El período de anotación no puede ser anterior al mes de emisión.")
    anterior = documento.fecha_anotacion
    if anterior == fecha:
        return documento
    for dia in {anterior or documento.fecha, fecha or documento.fecha}:
        periodo = Periodo.objects.select_for_update().filter(empresa=empresa, anio=dia.year, mes=dia.month).first()
        if periodo and periodo.estado == Periodo.Estado.CERRADO:
            raise AnotacionError("No se puede cambiar la anotación de un período contable cerrado.")
    documento.fecha_anotacion = fecha
    documento.save(update_fields=["fecha_anotacion"])
    detalle = f"Anotación: {anterior or 'estimada por emisión'} → {fecha or 'estimada por emisión'}"
    HistorialDocumento.objects.create(
        empresa=empresa,
        tipo=tipo,
        documento_id=documento.pk,
        usuario=usuario,
        accion="ANOTACION",
        detalle=detalle,
    )
    return documento

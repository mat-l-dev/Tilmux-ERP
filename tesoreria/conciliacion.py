"""Búsqueda, confirmación y reversión auditada de conciliaciones."""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogo.models import CuentaTesoreria
from core.models import Empresa, Perfil

from .models import ConciliacionBancaria, MovimientoTesoreria


class ConciliacionError(Exception):
    pass


def _validar_usuario(usuario, empresa):
    if usuario is None or not usuario.is_authenticated or not usuario.is_active:
        raise ConciliacionError("La operación necesita un usuario autenticado.")
    perfil = getattr(usuario, "perfil", None)
    if not usuario.is_superuser and (
        perfil is None or perfil.empresa_id != empresa.pk or not perfil.empresa.activa
    ):
        raise ConciliacionError("El usuario no tiene acceso a esta empresa.")
    if perfil is not None and perfil.rol == Perfil.Rol.LECTOR:
        raise ConciliacionError("Tu usuario es de solo lectura.")


def buscar_candidatos(*, empresa, cuenta, fecha, tipo, importe):
    """Los candidatos coinciden en cuenta, importe, tipo y fechas cercanas."""
    return MovimientoTesoreria.objects.filter(
        empresa=empresa, cuenta=cuenta, cuenta__empresa=empresa,
        fecha__range=(fecha - timedelta(days=3), fecha + timedelta(days=3)),
        tipo=tipo, importe=importe,
    ).order_by("fecha", "pk")


@transaction.atomic
def confirmar(*, empresa, cuenta, fecha, tipo, importe, movimiento_id, referencia, usuario):
    _validar_usuario(usuario, empresa)
    referencia = " ".join(referencia.split()).upper()
    if not referencia or len(referencia) > 100:
        raise ConciliacionError("Indica una referencia bancaria de hasta 100 caracteres.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    cuenta = CuentaTesoreria.objects.select_for_update().filter(pk=cuenta.pk, empresa=empresa, moneda="PEN").first()
    if cuenta is None:
        raise ConciliacionError("La cuenta no está disponible para esta empresa o no está en soles.")
    movimiento = MovimientoTesoreria.objects.select_for_update().filter(
        pk=movimiento_id, empresa=empresa, cuenta=cuenta,
    ).first()
    if movimiento is None:
        raise ConciliacionError("No se encontró el movimiento de esta cuenta y empresa.")
    if (movimiento.tipo != tipo or movimiento.importe != importe
            or abs((movimiento.fecha - fecha).days) > 3):
        raise ConciliacionError("Los datos del banco no corresponden con el movimiento seleccionado.")
    if movimiento.conciliado or ConciliacionBancaria.objects.filter(movimiento=movimiento, activa=True).exists():
        raise ConciliacionError("El movimiento ya está marcado o conciliado; revisa su historial.")
    if ConciliacionBancaria.objects.filter(empresa=empresa, cuenta=cuenta, referencia=referencia, activa=True).exists():
        raise ConciliacionError("Esta referencia bancaria ya está vinculada a otro movimiento de la cuenta.")
    try:
        with transaction.atomic():
            conciliacion = ConciliacionBancaria.objects.create(
                empresa=empresa, cuenta=cuenta, movimiento=movimiento, fecha_banco=fecha,
                tipo=tipo, importe=importe, referencia=referencia, creado_por=usuario,
            )
            movimiento.conciliado = True
            movimiento.save(update_fields=["conciliado"])
    except IntegrityError as exc:
        raise ConciliacionError("Ya existe una conciliación activa para el movimiento o la referencia.") from exc
    return conciliacion


@transaction.atomic
def revertir(*, empresa, conciliacion_id, motivo, usuario):
    _validar_usuario(usuario, empresa)
    motivo = motivo.strip()
    if not motivo or len(motivo) > 1000:
        raise ConciliacionError("Indica un motivo de reversión de hasta 1000 caracteres.")
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    conciliacion = ConciliacionBancaria.objects.select_for_update().filter(
        pk=conciliacion_id, empresa=empresa,
    ).first()
    if conciliacion is None:
        raise ConciliacionError("No se encontró la conciliación de esta empresa.")
    if not conciliacion.activa:
        raise ConciliacionError("La conciliación ya fue revertida.")
    movimiento = MovimientoTesoreria.objects.select_for_update().get(pk=conciliacion.movimiento_id)
    if (movimiento.empresa_id != empresa.pk or movimiento.cuenta_id != conciliacion.cuenta_id
            or not movimiento.conciliado):
        raise ConciliacionError("La marca del movimiento es inconsistente; revisa el historial.")
    conciliacion.activa = False
    conciliacion.revertido_por = usuario
    conciliacion.revertido = timezone.now()
    conciliacion.motivo_reversion = motivo
    conciliacion.save(update_fields=["activa", "revertido_por", "revertido", "motivo_reversion"])
    movimiento.conciliado = False
    movimiento.save(update_fields=["conciliado"])
    return conciliacion

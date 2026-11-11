"""Estados del SIRE por período y por registro (RCE y RVIE separados).

La propuesta descargada no acredita nada: solo el registro generado con su
constancia de recepción cierra el período. Este módulo guarda las tres etapas:

(a) ``PropuestaSIRE``: archivo original, fecha de descarga y hash.
(b) ``AjusteSIRE``: qué se agregó o excluyó al complementar, con motivo.
(c) Constancia de recepción del registro generado, con N° de operación,
    fecha y hora y cantidad de registros, en ``EstadoSIRE``.

Una propuesta aceptada sin constancia sigue PENDIENTE.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.models import Empresa

from .models import AjusteSIRE, EstadoSIRE, PropuestaSIRE

REGISTROS = (EstadoSIRE.Registro.RCE, EstadoSIRE.Registro.RVIE)
ESTADOS = {
    "SIN PROPUESTA": "Sin propuesta descargada",
    "PROPUESTA": "Propuesta descargada",
    "COMPLEMENTADA": "Propuesta complementada",
    "GENERADO": "Registro generado con constancia",
}
CERO = Decimal("0.00")


class SireError(Exception):
    pass


def _registro_valido(registro: str) -> str:
    if registro not in REGISTROS:
        raise SireError("Indica si el registro es RCE (compras) o RVIE (ventas).")
    return registro


def estado_de(empresa: Empresa, anio: int, mes: int, registro: str) -> EstadoSIRE:
    registro = _registro_valido(registro)
    if not 1 <= int(mes) <= 12:
        raise SireError("El mes debe estar entre 1 y 12.")
    estado, _ = EstadoSIRE.objects.get_or_create(empresa=empresa, anio=int(anio), mes=int(mes), registro=registro)
    return estado


@transaction.atomic
def registrar_propuesta(
    *,
    empresa: Empresa,
    anio: int,
    mes: int,
    registro: str,
    archivo,
    filas: int,
    base: Decimal,
    igv: Decimal,
    total: Decimal,
    usuario=None,
) -> PropuestaSIRE:
    """Guarda el archivo original de la propuesta con su hash y sus totales."""
    import hashlib

    estado = estado_de(empresa, anio, mes, registro)
    contenido = archivo.read()
    archivo.seek(0)
    if not contenido:
        raise SireError("El archivo de la propuesta está vacío.")
    huella = hashlib.sha256(contenido).hexdigest()
    ultima = estado.propuestas.first()
    if ultima is not None and ultima.hash_sha256 == huella:
        # Volver a subir el mismo archivo no duplica la historia.
        return ultima

    propuesta = PropuestaSIRE(
        estado=estado,
        nombre_original=(archivo.name or "propuesta")[:255],
        hash_sha256=huella,
        tamano=len(contenido),
        filas=int(filas or 0),
        base=Decimal(base or CERO),
        igv=Decimal(igv or CERO),
        total=Decimal(total or CERO),
        descargada_por=usuario,
    )
    propuesta.archivo.save(propuesta.nombre_original, archivo, save=False)
    propuesta.save()
    return propuesta


@transaction.atomic
def registrar_ajuste(
    *,
    empresa: Empresa,
    anio: int,
    mes: int,
    registro: str,
    tipo: str,
    documento: str,
    tipo_doc: str = "OTRO",
    fecha: date | None = None,
    base: Decimal = CERO,
    igv: Decimal = CERO,
    total: Decimal | None = None,
    motivo: str,
    usuario=None,
) -> AjusteSIRE:
    """Registra un comprobante agregado o excluido al complementar la propuesta."""
    estado = estado_de(empresa, anio, mes, registro)
    if not estado.propuestas.exists():
        raise SireError("No hay propuesta descargada para este período: no se puede complementar lo que no existe.")
    if estado.cerrado:
        raise SireError(
            "El registro ya tiene constancia de recepción; un ajuste posterior exige "
            "una nueva propuesta y un nuevo registro generado."
        )
    if tipo not in AjusteSIRE.Tipo.values:
        raise SireError("Indica si el comprobante se agrega o se excluye.")
    documento = (documento or "").strip()[:60]
    if len(documento) < 3:
        raise SireError("Indica el comprobante que se agrega o excluye (serie y número).")
    motivo = (motivo or "").strip()[:300]
    if len(motivo) < 5:
        raise SireError("Explica el motivo del ajuste (al menos 5 caracteres).")
    try:
        base = Decimal(base or CERO)
        igv = Decimal(igv or CERO)
        total = Decimal(total) if total not in (None, "") else base + igv
    except InvalidOperation, TypeError, ValueError:
        raise SireError("Indica importes válidos para el ajuste.") from None
    if any(valor < 0 for valor in (base, igv, total)):
        raise SireError("Los importes del ajuste no pueden ser negativos.")
    if total <= 0:
        raise SireError("El ajuste debe tener un importe mayor que cero.")

    return AjusteSIRE.objects.create(
        estado=estado,
        tipo=tipo,
        documento=documento,
        tipo_doc=(tipo_doc or "OTRO")[:8],
        fecha=fecha,
        base=base,
        igv=igv,
        total=total,
        motivo=motivo,
        creado_por=usuario,
    )


@transaction.atomic
def registrar_generacion(
    *,
    empresa: Empresa,
    anio: int,
    mes: int,
    registro: str,
    constancia_recepcion: str,
    numero_operacion: str,
    registros: int,
    generado_en: datetime | None = None,
    usuario=None,
) -> EstadoSIRE:
    """Marca el registro como generado; exige constancia, operación y fecha/hora."""
    estado = estado_de(empresa, anio, mes, registro)
    if not estado.propuestas.exists():
        raise SireError(
            "No hay propuesta descargada para este período: primero descarga la propuesta del SIRE y regístrala."
        )
    constancia = (constancia_recepcion or "").strip()[:80]
    operacion = (numero_operacion or "").strip()[:60]
    if len(constancia) < 4:
        raise SireError("Indica el número de constancia de recepción del SIRE.")
    if len(operacion) < 3:
        raise SireError("Indica el número de operación del registro generado.")
    try:
        registros = int(registros)
    except TypeError, ValueError:
        raise SireError("Indica cuántos registros se generaron.") from None
    if registros <= 0:
        raise SireError("Indica cuántos registros se generaron: debe haber al menos uno.")
    generado_en = generado_en or timezone.now()
    if timezone.is_naive(generado_en):
        generado_en = timezone.make_aware(generado_en, timezone.get_current_timezone())

    estado.constancia_recepcion = constancia
    estado.numero_operacion = operacion
    estado.registros_generados = registros
    estado.generado_en = generado_en
    estado.generado_por = usuario
    estado.save(
        update_fields=[
            "constancia_recepcion",
            "numero_operacion",
            "registros_generados",
            "generado_en",
            "generado_por",
            "actualizado",
        ]
    )
    return estado


def resumen_periodo(empresa: Empresa, anio: int, mes: int) -> dict:
    """Estado de RCE y RVIE del período; el período solo cierra con los dos."""
    existentes = {
        estado.registro: estado
        for estado in EstadoSIRE.objects.filter(empresa=empresa, anio=int(anio), mes=int(mes)).prefetch_related(
            "propuestas", "ajustes"
        )
    }
    filas = []
    for registro in REGISTROS:
        estado = existentes.get(registro)
        filas.append(
            {
                "registro": registro,
                "etiqueta": EstadoSIRE.Registro(registro).label,
                "estado": estado.estado if estado else "SIN PROPUESTA",
                "estado_texto": ESTADOS[estado.estado if estado else "SIN PROPUESTA"],
                "cerrado": bool(estado and estado.cerrado),
                "obj": estado,
                "propuesta": estado.propuesta_actual if estado else None,
                "ajustes": list(estado.ajustes.all()) if estado else [],
            }
        )
    return {
        "anio": int(anio),
        "mes": int(mes),
        "registros": filas,
        "cerrado": all(fila["cerrado"] for fila in filas),
    }

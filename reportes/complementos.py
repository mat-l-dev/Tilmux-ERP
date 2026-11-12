"""Complemento del RCE para comprobantes que no van en la propuesta.

Caso típico: la boleta de venta electrónica tipo 03 (Tabla 11 del Anexo 1 de la
RS 040-2022) no se incluye en la propuesta y se incorpora por **Complementar**.
Una boleta **no da crédito fiscal** (RS 007-99, art. 4.3.2): todo su importe va
a compras no gravadas (casilla 120, Valor Adq No Grav), con base gravada e IGV
en cero. Este módulo impide que se registre como compra gravada.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from .estados_sire import SireError, registrar_ajuste
from .models import AjusteSIRE, EstadoSIRE

CERO = Decimal("0.00")
TIPOS_BOLETA = {"03": "BOLETA"}
CLASIF_OTROS_GASTOS = "5"  # Tabla 23: otros gastos no incluidos en el numeral 4.
MOTIVO_POR_DEFECTO = "Comprobante no incluido en la propuesta del RCE; se incorpora por Complementar."


def _digitos(valor) -> str:
    return "".join(caracter for caracter in str(valor or "") if caracter.isdigit())


def car_sunat(*, ruc: str, tipo_doc: str, serie: str, numero) -> str:
    """CAR del RCE: RUC 11 + tipo 2 + serie 4 + número a 10 dígitos (27)."""
    ruc_digitos = _digitos(ruc)
    if len(ruc_digitos) != 11:
        raise SireError("El RUC del emisor debe tener 11 dígitos.")
    tipo = str(tipo_doc or "").strip()
    if len(tipo) != 2 or not tipo.isdigit():
        raise SireError("El tipo de comprobante debe tener 2 dígitos (03 para boleta).")
    serie_texto = str(serie or "").strip().upper()
    if len(serie_texto) != 4 or not serie_texto.isalnum():
        raise SireError("La serie debe tener 4 caracteres, por ejemplo B001.")
    numero_digitos = _digitos(numero)
    if not 1 <= len(numero_digitos) <= 10:
        raise SireError("El número del comprobante debe tener entre 1 y 10 dígitos.")
    return f"{ruc_digitos}{tipo}{serie_texto}{numero_digitos.zfill(10)}"


def compras_no_gravadas(*, empresa, anio: int, mes: int) -> dict:
    """Casilla 120 del RCE: no gravado de la propuesta más los complementos."""
    estado = EstadoSIRE.objects.filter(empresa=empresa, anio=anio, mes=mes, registro="RCE").first()
    de_propuesta = CERO
    complementos = CERO
    if estado is not None:
        propuesta = estado.propuesta_actual
        if propuesta is not None:
            de_propuesta = max(
                Decimal(propuesta.total) - Decimal(propuesta.base) - Decimal(propuesta.igv),
                CERO,
            )
        complementos = (
            estado.ajustes.filter(tipo=AjusteSIRE.Tipo.AGREGADO).aggregate(suma=Sum("no_gravado"))["suma"] or CERO
        )
    return {
        "propuesta": de_propuesta,
        "complementos": complementos,
        "total": de_propuesta + complementos,
    }


def registrar_complemento(
    *,
    empresa,
    anio: int,
    mes: int,
    tipo_doc: str,
    serie: str,
    numero,
    ruc_emisor: str,
    razon_social: str,
    fecha: date | None,
    total,
    clasif_tabla23: str = CLASIF_OTROS_GASTOS,
    motivo: str = MOTIVO_POR_DEFECTO,
    base=CERO,
    igv=CERO,
    usuario=None,
) -> AjusteSIRE:
    """Registra un comprobante no propuesto, con su CAR, como no gravado.

    ``base`` e ``igv`` existen para poder rechazarlos: una boleta tipo 03 no
    lleva base gravada ni IGV. El importe completo va a ``no_gravado``.
    """
    tipo = str(tipo_doc or "").strip()
    if tipo not in TIPOS_BOLETA:
        raise SireError(
            "Este flujo complementa boletas de venta (tipo 03). Para otros comprobantes usa la propuesta del SIRE."
        )
    try:
        base = Decimal(base or CERO)
        igv = Decimal(igv or CERO)
        total = Decimal(total)
    except InvalidOperation, TypeError, ValueError:
        raise SireError("Indica un importe total válido.") from None
    if base != CERO or igv != CERO:
        raise SireError(
            "Una boleta tipo 03 no tiene base gravada ni IGV: todo el importe va a "
            "compras no gravadas (casilla 120, Valor Adq No Grav), con base e IGV "
            "en 0,00. No registres 167,83 de base ni 30,21 de IGV."
        )
    if total <= CERO:
        raise SireError("El importe total de la boleta debe ser mayor que cero.")
    if fecha is None:
        fecha = date(anio, mes, calendar.monthrange(anio, mes)[1])
    if (fecha.year, fecha.month) != (anio, mes):
        raise SireError("La fecha del comprobante debe pertenecer al período que se complementa.")
    ruc_digitos = _digitos(ruc_emisor)
    car = car_sunat(ruc=ruc_digitos, tipo_doc=tipo, serie=serie, numero=numero)
    numero_digitos = _digitos(numero)
    serie_texto = str(serie or "").strip().upper()
    razon = (razon_social or "").strip()[:200]
    if len(razon) < 3:
        raise SireError("Indica la razón social del emisor de la boleta.")
    clasif = str(clasif_tabla23 or CLASIF_OTROS_GASTOS).strip()[:2]
    if not clasif.isdigit():
        raise SireError("La clasificación de la Tabla 23 debe ser numérica (5 para comisiones).")

    estado = EstadoSIRE.objects.filter(empresa=empresa, anio=anio, mes=mes, registro="RCE").first()
    if estado is not None and estado.ajustes.filter(car=car).exists():
        raise SireError("Ese comprobante ya está complementado en el RCE.")

    ajuste = registrar_ajuste(
        empresa=empresa,
        anio=anio,
        mes=mes,
        registro="RCE",
        tipo=AjusteSIRE.Tipo.AGREGADO,
        documento=f"{serie_texto}-{numero_digitos}",
        tipo_doc=tipo,
        fecha=fecha,
        base=CERO,
        igv=CERO,
        total=total,
        motivo=motivo,
        usuario=usuario,
    )
    ajuste.car = car
    ajuste.ruc_emisor = ruc_digitos
    ajuste.razon_social = razon
    ajuste.serie = serie_texto
    ajuste.numero = numero_digitos.zfill(10)
    ajuste.no_gravado = total
    ajuste.moneda = "PEN"
    ajuste.tipo_cambio = Decimal("0.000")
    ajuste.fecha_vencimiento = fecha
    ajuste.clasif_tabla23 = clasif
    ajuste.anio_documento = ""
    ajuste.numero_final = ""
    ajuste.save(
        update_fields=[
            "car",
            "ruc_emisor",
            "razon_social",
            "serie",
            "numero",
            "no_gravado",
            "moneda",
            "tipo_cambio",
            "fecha_vencimiento",
            "clasif_tabla23",
            "anio_documento",
            "numero_final",
        ]
    )
    return ajuste

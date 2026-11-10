"""Restitución de deudas con el socio: 4411, 4419 y cuentas equivalentes.

Regla del flujo: sin voucher bancario no hay pago. La obligación queda PENDIENTE
mientras el saldo de la cuenta siga abierto; el pago postea D obligación / H
medio de pago y registra el movimiento de tesorería. Nunca pasa por 4212, gasto
ni dividendo.

Por qué es estricto (auditoría P0-3): un retiro a favor del socio sin obligación
de devolver sustentada puede ser dividendo presunto (art. 24-A inc. f LIR) y un
crédito a vinculadas sin sustento es reparo (RTF 06598-2-2012). El voucher —N°
de operación, fecha y hora, cuentas, importe exacto— es la prueba mínima.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from catalogo.models import CuentaTesoreria
from contabilidad.impuestos import saldo_cuenta
from contabilidad.models import Cuenta
from contabilidad.servicios import postear_lineas
from core.contexto import usuario_actual
from core.models import Empresa
from tesoreria.models import MovimientoTesoreria, RestitucionSocio
from tesoreria.servicios import anotar

CUENTAS_POR_TIPO = {
    RestitucionSocio.Tipo.PRESTAMO_SOCIO: "4411",
    RestitucionSocio.Tipo.REEMBOLSO_SOCIO: "4419",
    RestitucionSocio.Tipo.REEMBOLSO_DIRECTOR: "4429",
    RestitucionSocio.Tipo.REEMBOLSO_TERCERO: "4699",
}
CERO = Decimal("0.00")


class RestitucionError(Exception):
    pass


def saldo_obligacion(empresa: Empresa, tipo: str, hasta: date | None = None) -> Decimal:
    """Saldo pendiente de la cuenta de la obligación (positivo = se debe)."""
    codigo = CUENTAS_POR_TIPO.get(tipo)
    if codigo is None:
        raise RestitucionError("Tipo de obligación desconocido.")
    return saldo_cuenta(empresa, codigo, hasta or timezone.localdate())


def obligaciones(empresa: Empresa, hasta: date | None = None) -> list[dict]:
    """Obligaciones con saldo pendiente, listas para pagar con voucher."""
    pendientes = []
    for tipo, etiqueta in RestitucionSocio.Tipo.choices:
        codigo = CUENTAS_POR_TIPO[tipo]
        saldo = saldo_obligacion(empresa, tipo, hasta)
        if saldo > CERO:
            pendientes.append(
                {
                    "tipo": tipo,
                    "etiqueta": etiqueta,
                    "codigo": codigo,
                    "cuenta": Cuenta.objects.filter(version="2026", codigo=codigo).first(),
                    "saldo": saldo,
                    "estado": "PENDIENTE",
                }
            )
    return pendientes


def _texto_obligatorio(valor, campo: str, minimo: int = 3) -> str:
    limpio = (valor or "").strip()
    if len(limpio) < minimo:
        raise RestitucionError(f"El voucher exige {campo}. Sin ese dato la obligación sigue PENDIENTE.")
    return limpio


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(Decimal("0.01"))


def _cuenta_contable(codigo: str) -> Cuenta:
    cuenta = Cuenta.objects.filter(version="2026", codigo=codigo).first()
    if cuenta is None:
        raise RestitucionError(f"El PCGE 2026 no tiene la cuenta {codigo}.")
    return cuenta


@transaction.atomic
def registrar_restitucion(
    *,
    empresa: Empresa,
    tipo: str,
    cuenta: CuentaTesoreria,
    fecha_hora,
    numero_operacion: str,
    cuenta_destino: str,
    beneficiario: str,
    importe,
    concepto: str,
    usuario=None,
) -> RestitucionSocio:
    """Paga una obligación con el socio; exige el voucher completo."""
    usuario = usuario or usuario_actual.get()
    Empresa.objects.select_for_update().get(pk=empresa.pk)

    if tipo not in CUENTAS_POR_TIPO:
        raise RestitucionError("Tipo de obligación desconocido.")
    if fecha_hora is None:
        raise RestitucionError("El voucher exige la fecha y hora de la operación.")
    if timezone.is_naive(fecha_hora):
        fecha_hora = timezone.make_aware(fecha_hora, timezone.get_current_timezone())
    fecha = timezone.localtime(fecha_hora).date()
    if fecha > timezone.localdate():
        raise RestitucionError("La fecha del voucher no puede estar en el futuro.")

    numero_operacion = _texto_obligatorio(numero_operacion, "el número de operación")
    cuenta_destino = _texto_obligatorio(cuenta_destino, "la cuenta de destino del voucher", minimo=4)
    beneficiario = _texto_obligatorio(beneficiario, "el nombre del beneficiario")
    concepto = _texto_obligatorio(concepto, "el concepto de la operación", minimo=5)

    try:
        importe = _cent(Decimal(str(importe)))
    except InvalidOperation, TypeError, ValueError:
        raise RestitucionError("Indica un importe válido para la restitución.") from None
    if importe <= CERO:
        raise RestitucionError("El importe de la restitución debe ser mayor que cero.")

    if (
        cuenta.empresa_id != empresa.pk
        or not cuenta.activa
        or cuenta.moneda != "PEN"
        or cuenta.cuenta_contable_id is None
    ):
        raise RestitucionError("La cuenta de origen debe estar activa, en soles y con cuenta contable.")
    if MovimientoTesoreria.objects.filter(empresa=empresa, origen_tipo="RESTITUCION_SOCIO", fecha__gt=fecha).exists():
        raise RestitucionError("Ya hay restituciones posteriores; registra esta operación en orden cronológico.")
    if RestitucionSocio.objects.filter(empresa=empresa, numero_operacion=numero_operacion).exists():
        raise RestitucionError(f"La operación {numero_operacion} ya está registrada; revisa el voucher.")

    codigo = CUENTAS_POR_TIPO[tipo]
    saldo = saldo_cuenta(empresa, codigo, fecha)
    if saldo <= CERO:
        raise RestitucionError(f"La cuenta {codigo} no tiene saldo pendiente al {fecha:%d/%m/%Y}.")
    if importe > saldo:
        raise RestitucionError(f"El saldo pendiente de la {codigo} es S/ {saldo}; no se puede restituir S/ {importe}.")

    cuenta_contable = _cuenta_contable(codigo)
    restitucion = RestitucionSocio.objects.create(
        empresa=empresa,
        tipo=tipo,
        fecha=fecha,
        fecha_hora=fecha_hora,
        cuenta=cuenta,
        cuenta_contable=cuenta_contable,
        beneficiario=beneficiario,
        numero_operacion=numero_operacion,
        cuenta_destino=cuenta_destino,
        importe=importe,
        concepto=concepto,
        creado_por=usuario,
    )

    asiento = postear_lineas(
        empresa=empresa,
        fecha=fecha,
        tipo="RESTITUCION_SOCIO",
        glosa=f"Restitución a {beneficiario} · op. {numero_operacion}"[:255],
        lineas=[
            (cuenta_contable, importe, CERO, f"Pago de la obligación {codigo}"),
            (cuenta.cuenta_contable, CERO, importe, "Salida de dinero"),
        ],
        origen_tipo="RESTITUCION_SOCIO",
        origen_id=restitucion.pk,
        usuario=usuario,
    )
    anotar(
        empresa=empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo="EGRESO",
        importe=importe,
        concepto=f"Restitución {beneficiario} · op. {numero_operacion}",
        canal="TRANSFERENCIA",
        origen_tipo="RESTITUCION_SOCIO",
        origen_id=restitucion.pk,
    )
    restitucion.asiento = asiento
    restitucion.save(update_fields=["asiento"])
    return restitucion


def reembolsos_registrados(empresa: Empresa):
    return (
        RestitucionSocio.objects.filter(empresa=empresa)
        .select_related("cuenta", "cuenta_contable", "asiento", "creado_por")
        .order_by("-fecha_hora", "-pk")
    )

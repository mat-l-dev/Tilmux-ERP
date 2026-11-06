"""Confirmación de compras: stock, costo y asiento en una sola transacción."""

from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from contabilidad.models import Cuenta
from contabilidad.moneda import tipo_cambio_de
from contabilidad.servicios import Montos, postear, postear_lineas
from core.contexto import usuario_actual
from core.models import Empresa, TipoCambio
from inventario.servicios import entrar
from tesoreria.servicios import anotar

from .comprobantes import buscar_comprobante
from .models import Compra
from .models_gasto import Gasto

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
DIEZ = Decimal("0.0000000001")


class CompraError(Exception):
    pass


def validar_comprobante(*, empresa, proveedor, tipo_doc, serie, numero, compra_id=None):
    # El bloqueo serializa las comprobaciones y registros entre ambos módulos.
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    origen = buscar_comprobante(
        empresa=empresa, proveedor=proveedor, tipo_doc=tipo_doc,
        serie=serie, numero=numero, compra_id=compra_id,
    )
    if origen:
        raise CompraError(f"El comprobante {serie}-{numero} ya está registrado como {origen} para este proveedor.")


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def confirmar(compra: Compra) -> Compra:
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado == Compra.Estado.PENDIENTE:
        raise CompraError(
            "La compra está pendiente de factura: completa los datos y desmarca "
            "la pendiente antes de confirmar."
        )
    if compra.estado != Compra.Estado.BORRADOR:
        raise CompraError("Solo se confirma una compra en borrador.")
    validar_comprobante(
        empresa=compra.empresa, proveedor=compra.proveedor, tipo_doc=compra.tipo_doc,
        serie=compra.serie, numero=compra.numero, compra_id=compra.pk,
    )
    if compra.con_credito:
        if not compra.serie.strip() or not compra.numero.strip():
            raise CompraError(
                "Completa la serie y el número del comprobante antes de confirmar."
            )
        if len(compra.proveedor.numero_doc) != 11:
            raise CompraError(
                "Una compra con crédito fiscal exige el RUC de 11 dígitos del proveedor."
            )

    lineas = list(compra.lineas.select_related("producto", "producto__unidad"))
    if not lineas:
        raise CompraError("La compra no tiene líneas.")

    costos = list(compra.costos.all())
    asignado = {linea.pk: Decimal("0") for linea in lineas}

    for costo in costos:
        if costo.base <= 0:
            continue
        pesos = [
            linea.base if costo.criterio == costo.Criterio.VALOR else linea.cantidad
            for linea in lineas
        ]
        suma = sum(pesos, Decimal("0"))
        if suma <= 0:
            raise CompraError(
                f"No se puede prorratear «{costo.concepto}»: base cero."
            )
        acumulado = Decimal("0")
        for indice, linea in enumerate(lineas):
            if indice == len(lineas) - 1:
                parte = _cent(costo.base) - acumulado
            else:
                parte = _cent(costo.base * pesos[indice] / suma)
                acumulado += parte
            asignado[linea.pk] += parte

    for linea in lineas:
        if linea.cantidad <= 0:
            raise CompraError("Hay una línea con cantidad cero.")
        # Si el comprobante no da crédito fiscal, su IGV forma parte del costo.
        impuesto_al_costo = Decimal("0") if compra.con_credito else Decimal(linea.igv)
        costo_total_linea = Decimal(linea.base) + impuesto_al_costo + asignado[linea.pk]
        costo_unitario = (costo_total_linea / linea.cantidad).quantize(
            DIEZ, rounding=ROUND_HALF_UP
        )
        linea.costo_unitario_final = costo_unitario
        linea.save(update_fields=["costo_unitario_final"])
        entrar(
            empresa=compra.empresa,
            producto=linea.producto,
            fecha=compra.fecha,
            cantidad=linea.cantidad,
            costo_unitario=costo_unitario,
            origen_tipo="COMPRA",
            origen_id=compra.pk,
            glosa=f"Compra {compra.serie}-{compra.numero}".strip(" -"),
        )

    base = _cent(sum((linea.base for linea in lineas), Decimal("0")) + sum((c.base for c in costos), Decimal("0")))
    igv = _cent(sum((linea.igv for linea in lineas), Decimal("0")) + sum((c.igv for c in costos), Decimal("0")))
    total = base + igv

    compra.subtotal = base
    compra.igv = igv
    compra.total = total
    compra.total_moneda_origen = total
    compra.estado = Compra.Estado.CONFIRMADA
    compra.confirmado_en = timezone.now()
    compra.save(
        update_fields=[
            "subtotal",
            "igv",
            "total",
            "total_moneda_origen",
            "estado",
            "confirmado_en",
        ]
    )

    postear(
        empresa=compra.empresa,
        fecha=compra.fecha,
        tipo="COMPRA",
        glosa=f"Compra {compra.serie}-{compra.numero}".strip(" -"),
        montos=Montos(
            base=base if compra.con_credito else total,
            igv=igv if compra.con_credito else Decimal("0.00"),
            total=total,
        ),
        origen_tipo="COMPRA",
        origen_id=compra.pk,
    )
    logger.info("compra confirmada %s-%s total=%s", compra.serie, compra.numero, total)
    return compra


@transaction.atomic
def registrar_gasto(
    *,
    empresa,
    proveedor,
    fecha,
    tipo_doc: str,
    serie: str,
    numero: str,
    base,
    igv,
    total,
    cuenta,
    medio=None,
    glosa: str = "",
    origen_tipo: str = "",
    origen_id: int | None = None,
    con_credito: bool = True,
    deducible: bool = True,
    provision: bool = False,
    gasto_origen: Gasto | None = None,
    fecha_devengado=None,
    estado: str | None = None,
) -> Gasto:
    serie, numero = serie[:4], numero[:20]
    base, igv, total = _cent(base), _cent(igv), _cent(total)
    if base + igv != total:
        raise CompraError("El gasto no cuadra: base más IGV no da el total.")
    if not provision and medio is None:
        raise CompraError("El gasto necesita una cuenta de tesorería.")
    if cuenta is None:
        raise CompraError("El gasto necesita una cuenta contable.")
    if gasto_origen is not None and not provision:
        raise CompraError("Solo una provisión puede tener un gasto de origen.")
    if gasto_origen is not None and gasto_origen.empresa_id != empresa.pk:
        raise CompraError("La factura de origen pertenece a otra empresa.")

    if not provision:
        validar_comprobante(
            empresa=empresa, proveedor=proveedor, tipo_doc=tipo_doc,
            serie=serie, numero=numero,
        )

    estado_final = estado or (
        Gasto.Estado.PROVISION if provision else Gasto.Estado.PAGADO
    )
    gasto = Gasto.objects.create(
        creado_por=usuario_actual.get(),
        empresa=empresa,
        proveedor=proveedor,
        fecha=fecha,
        fecha_devengado=fecha_devengado,
        tipo_doc=tipo_doc,
        serie=serie,
        numero=numero,
        base=base,
        igv=igv,
        total=total,
        cuenta=cuenta,
        medio=medio,
        glosa=glosa[:255],
        con_credito=con_credito,
        deducible=deducible,
        provision=provision,
        gasto_origen=gasto_origen,
        estado=estado_final,
    )

    documento = f"{serie}-{numero}".strip(" -") or "sin comprobante"
    usa_credito = con_credito and igv > 0
    if provision:
        cuentas = {
            c.codigo: c
            for c in Cuenta.objects.filter(
                version="2026", codigo__in=["40111", "4212"]
            )
        }
        lineas = [
            (
                cuenta,
                base if usa_credito else total,
                Decimal("0.00"),
                "Gasto provisionado",
            )
        ]
        if usa_credito:
            lineas.append(
                (
                    cuentas["40111"],
                    igv,
                    Decimal("0.00"),
                    "IGV de la provisión",
                )
            )
        lineas.append(
            (cuentas["4212"], Decimal("0.00"), total, "Por pagar")
        )
        postear_lineas(
            empresa=empresa,
            fecha=fecha_devengado or fecha,
            tipo="PROVISION_GASTO",
            glosa=f"Provisión {documento} · {proveedor.nombre}"[:255],
            lineas=lineas,
            origen_tipo=origen_tipo or "GASTO",
            origen_id=origen_id or gasto.pk,
        )
        return gasto

    postear(
        empresa=empresa,
        fecha=fecha,
        tipo="GASTO_CON_IGV" if usa_credito else "GASTO_SIN_IGV",
        glosa=f"{documento} · {proveedor.nombre}"[:255],
        montos=Montos(
            base=base if usa_credito else total,
            igv=igv if usa_credito else Decimal("0.00"),
            total=total,
        ),
        origen_tipo=origen_tipo or "GASTO",
        origen_id=origen_id or gasto.pk,
        cuenta_medio=medio.cuenta_contable,
        cuenta_gasto=cuenta,
    )
    anotar(
        empresa=empresa,
        cuenta=medio,
        fecha=fecha,
        tipo="EGRESO",
        importe=total,
        concepto=glosa or f"Gasto {documento}",
        origen_tipo=origen_tipo or "GASTO",
        origen_id=origen_id or gasto.pk,
    )
    return gasto

CUENTA_DIFERENCIA_PERDIDA = "6761"
CUENTA_DIFERENCIA_GANANCIA = "7761"


@transaction.atomic
def pagar(
    compra: Compra,
    *,
    cuenta,
    fecha,
    canal: str = "TRANSFERENCIA",
    tipo_cambio_pago=None,
    importe=None,
):
    """Paga total o parcialmente una compra, con diferencia de cambio."""
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.CONFIRMADA:
        raise CompraError("Solo se paga una compra confirmada.")
    if cuenta.cuenta_contable is None:
        raise CompraError("La cuenta de tesorería no tiene cuenta contable.")

    total_pen = _cent(Decimal(compra.total) + Decimal(compra.revaluacion))
    pagado_previo = _cent(compra.monto_pagado)
    saldo = _cent(total_pen - pagado_previo)
    if saldo <= 0:
        raise CompraError("La compra ya está pagada.")

    monto = saldo if importe is None else _cent(importe)
    if monto <= 0:
        raise CompraError("El importe debe ser mayor a cero.")
    if monto > saldo:
        raise CompraError(f"El saldo pendiente es {saldo}.")

    if compra.moneda == "PEN":
        llevado = monto
        pagado = monto
        diferencia = Decimal("0.00")
    else:
        tasa = (
            Decimal(tipo_cambio_pago)
            if tipo_cambio_pago
            else tipo_cambio_de(fecha).venta
        )
        porcion = (
            Decimal(compra.total_moneda_origen) * monto / total_pen
        ).quantize(Decimal("0.0001"))
        pagado = _cent(porcion * tasa)
        llevado = monto
        diferencia = _cent(pagado - llevado)

    cuentas = {
        c.codigo: c
        for c in Cuenta.objects.filter(
            version="2026",
            codigo__in=["4212", CUENTA_DIFERENCIA_PERDIDA, CUENTA_DIFERENCIA_GANANCIA],
        )
    }
    documento = f"{compra.serie}-{compra.numero}".strip(" -")
    lineas = [
        (cuentas["4212"], llevado, Decimal("0.00"), f"Pago compra {documento}")
    ]
    if diferencia > 0:
        lineas.append(
            (
                cuentas[CUENTA_DIFERENCIA_PERDIDA],
                diferencia,
                Decimal("0.00"),
                "Diferencia de cambio",
            )
        )
    elif diferencia < 0:
        lineas.append(
            (
                cuentas[CUENTA_DIFERENCIA_GANANCIA],
                Decimal("0.00"),
                -diferencia,
                "Diferencia de cambio",
            )
        )
    lineas.append((cuenta.cuenta_contable, Decimal("0.00"), pagado, "Salida de dinero"))

    postear_lineas(
        empresa=compra.empresa,
        fecha=fecha,
        tipo="PAGO_PROVEEDOR",
        glosa=f"Pago compra {documento}",
        lineas=lineas,
        origen_tipo="COMPRA_PAGO",
        origen_id=compra.pk,
    )
    anotar(
        empresa=compra.empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo="EGRESO",
        importe=pagado,
        concepto=f"Pago compra {documento}",
        canal=canal,
        origen_tipo="COMPRA_PAGO",
        origen_id=compra.pk,
    )

    compra.monto_pagado = pagado_previo + llevado
    compra.pagada = compra.monto_pagado >= total_pen
    if compra.pagada:
        compra.fecha_pago = fecha
    compra.save(update_fields=["monto_pagado", "pagada", "fecha_pago"])
    return pagado, diferencia


@transaction.atomic
def revaluar(empresa, anio: int, mes: int):
    """Ajusta los saldos por pagar en moneda extranjera al cierre del mes."""
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    tasa = TipoCambio.del_dia(ultimo_dia).venta

    compras = (
        Compra.objects.select_for_update()
        .filter(
            empresa=empresa,
            estado=Compra.Estado.CONFIRMADA,
            pagada=False,
            fecha__lte=ultimo_dia,
        )
        .exclude(moneda="PEN")
    )

    cuentas = {
        c.codigo: c
        for c in Cuenta.objects.filter(
            version="2026",
            codigo__in=["4212", CUENTA_DIFERENCIA_PERDIDA, CUENTA_DIFERENCIA_GANANCIA],
        )
    }

    ajustadas = 0
    total = Decimal("0.00")

    for compra in compras:
        objetivo = _cent(Decimal(compra.total_moneda_origen) * tasa)
        llevado = _cent(Decimal(compra.total) + Decimal(compra.revaluacion))
        delta = _cent(objetivo - llevado)
        if delta == 0:
            continue

        documento = f"{compra.serie}-{compra.numero}".strip(" -")
        if delta > 0:
            lineas = [
                (
                    cuentas[CUENTA_DIFERENCIA_PERDIDA],
                    delta,
                    Decimal("0.00"),
                    "Pérdida por diferencia de cambio",
                ),
                (cuentas["4212"], Decimal("0.00"), delta, f"Revaluación {documento}"),
            ]
        else:
            lineas = [
                (cuentas["4212"], -delta, Decimal("0.00"), f"Revaluación {documento}"),
                (
                    cuentas[CUENTA_DIFERENCIA_GANANCIA],
                    Decimal("0.00"),
                    -delta,
                    "Ganancia por diferencia de cambio",
                ),
            ]

        postear_lineas(
            empresa=empresa,
            fecha=ultimo_dia,
            tipo="REVALUACION",
            glosa=f"Revaluación {documento}",
            lineas=lineas,
            origen_tipo="REVALUACION",
            origen_id=compra.pk,
        )

        compra.revaluacion = Decimal(compra.revaluacion) + delta
        compra.save(update_fields=["revaluacion"])
        total += delta
        ajustadas += 1

    return ajustadas, total

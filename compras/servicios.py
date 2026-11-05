"""Confirmación de compras: stock, costo y asiento en una sola transacción."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from contabilidad.servicios import Montos, postear
from inventario.servicios import entrar
from tesoreria.servicios import anotar

from .models import Compra
from .models_gasto import Gasto

CENT = Decimal("0.01")
DIEZ = Decimal("0.0000000001")


class CompraError(Exception):
    pass


def _cent(valor) -> Decimal:
    return Decimal(valor).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def confirmar(compra: Compra) -> Compra:
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.BORRADOR:
        raise CompraError("Solo se confirma una compra en borrador.")

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

    base = _cent(sum((l.base for l in lineas), Decimal("0")) + sum((c.base for c in costos), Decimal("0")))
    igv = _cent(sum((l.igv for l in lineas), Decimal("0")) + sum((c.igv for c in costos), Decimal("0")))
    total = base + igv

    compra.subtotal = base
    compra.igv = igv
    compra.total = total
    compra.estado = Compra.Estado.CONFIRMADA
    compra.confirmado_en = timezone.now()
    compra.save(
        update_fields=["subtotal", "igv", "total", "estado", "confirmado_en"]
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
) -> Gasto:
    base, igv, total = _cent(base), _cent(igv), _cent(total)
    if base + igv != total:
        raise CompraError("El gasto no cuadra: base más IGV no da el total.")
    if medio is None:
        raise CompraError("El gasto necesita una cuenta de tesorería.")
    if cuenta is None:
        raise CompraError("El gasto necesita una cuenta contable.")

    gasto = Gasto.objects.create(
        empresa=empresa,
        proveedor=proveedor,
        fecha=fecha,
        tipo_doc=tipo_doc,
        serie=serie[:4],
        numero=numero[:20],
        base=base,
        igv=igv,
        total=total,
        cuenta=cuenta,
        medio=medio,
        glosa=glosa[:255],
        con_credito=con_credito,
        deducible=deducible,
    )

    documento = f"{serie}-{numero}".strip(" -") or "sin comprobante"
    usa_credito = con_credito and igv > 0
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

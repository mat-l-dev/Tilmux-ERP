"""Nota de crédito del proveedor: devolución real de mercadería.

Este flujo NO es una reversión interna (`compras/reversion.py`): esa anula un
registro erróneo. Aquí el proveedor emite una nota de crédito por una devolución
y el ERP debe:

1. reducir la deuda de la cuenta 4212,
2. revertir el IGV de la cuenta 40111 y la base del RCE,
3. sacar del inventario las unidades de ESA compra, al costo de su capa PEPS
   original (no al promedio general),
4. registrar en tesorería el reembolso cuando el proveedor devuelve el dinero.

Limitaciones deliberadas, con aviso en vez de cifras inventadas:

- No se admite devolución de compras en moneda extranjera (depende de P0-4).
- No se admite devolución de compras con costos de internamiento prorrateados:
  el flete es de otro proveedor y su tratamiento en la nota no está definido.
- La devolución debe registrarse en orden cronológico: si ya hay una salida
  posterior del producto, el PEPS histórico cambiaría y el flujo se detiene.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from catalogo.models import CuentaTesoreria
from contabilidad.models import Cuenta
from contabilidad.servicios import postear_lineas
from core.contexto import usuario_actual
from core.models import HistorialDocumento
from inventario.servicios import salir_de_compra
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import anotar

from .models import Compra, CompraLinea, NotaCreditoCompra, NotaCreditoCompraLinea
from .servicios import CompraError, _cent

MOTIVOS_IMPLEMENTADOS = frozenset({"06", "07"})
CUENTA_INVENTARIO = "20111"
CUENTA_IGV = "40111"
CUENTA_POR_PAGAR = "4212"
CERO = Decimal("0.00")


def acreditado_de(compra: Compra) -> Decimal:
    """Total ya acreditado por notas de crédito del proveedor."""
    return _cent(compra.notas_credito.aggregate(s=Sum("total"))["s"] or CERO)


def reembolsado_de(compra: Compra) -> Decimal:
    """Dinero ya devuelto por el proveedor."""
    return _cent(compra.notas_credito.aggregate(s=Sum("importe_reembolsado"))["s"] or CERO)


def saldo_4212(compra: Compra) -> Decimal:
    """Saldo teórico de la deuda con el proveedor después de notas y reembolsos.

    Positivo: todavía se le debe. Negativo: el proveedor nos debe un reembolso.
    """
    return _cent(
        Decimal(compra.total)
        + Decimal(compra.revaluacion)
        - Decimal(compra.monto_pagado)
        - acreditado_de(compra)
        + reembolsado_de(compra)
    )


def _cuentas_contables() -> dict[str, Cuenta]:
    return {
        c.codigo: c
        for c in Cuenta.objects.filter(version="2026", codigo__in=[CUENTA_INVENTARIO, CUENTA_IGV, CUENTA_POR_PAGAR])
    }


def _validar_cuenta_reembolso(cuenta, empresa) -> None:
    if cuenta is None:
        raise CompraError("Elige la cuenta de tesorería donde entra el reembolso.")
    if (
        cuenta.empresa_id != empresa.pk
        or not cuenta.activa
        or cuenta.moneda != "PEN"
        or cuenta.cuenta_contable_id is None
    ):
        raise CompraError("La cuenta del reembolso debe estar activa, en soles y con cuenta contable.")


def _registrar_dinero(
    *,
    nota: NotaCreditoCompra,
    cuenta: CuentaTesoreria,
    fecha: date,
    importe: Decimal,
    canal: str,
    usuario,
) -> None:
    """Entrada de dinero del proveedor: asiento y movimiento, sin tocar lo pagado."""
    compra = nota.compra
    documento = f"{nota.serie}-{nota.numero}".strip(" -")
    cuentas = _cuentas_contables()
    postear_lineas(
        empresa=compra.empresa,
        fecha=fecha,
        tipo="REEMBOLSO_PROVEEDOR",
        glosa=f"Reembolso de {compra.proveedor.nombre} por {documento}"[:255],
        lineas=[
            (cuenta.cuenta_contable, importe, CERO, "Ingreso del reembolso"),
            (cuentas[CUENTA_POR_PAGAR], CERO, importe, "Deuda revertida"),
        ],
        origen_tipo="DEVOLUCION_PROVEEDOR",
        origen_id=nota.pk,
        usuario=usuario,
    )
    anotar(
        empresa=compra.empresa,
        cuenta=cuenta,
        fecha=fecha,
        tipo="INGRESO",
        importe=importe,
        concepto=f"Reembolso {compra.proveedor.nombre} por {documento}",
        canal=canal,
        origen_tipo="DEVOLUCION_PROVEEDOR",
        origen_id=nota.pk,
    )
    nota.importe_reembolsado = _cent(Decimal(nota.importe_reembolsado) + importe)
    nota.reembolsado = True
    nota.fecha_reembolso = fecha
    nota.save(update_fields=["importe_reembolsado", "reembolsado", "fecha_reembolso"])
    compra.pagada = saldo_4212(compra) <= 0
    compra.save(update_fields=["pagada"])


@transaction.atomic
def registrar_devolucion(
    *,
    compra: Compra,
    fecha: date,
    serie: str,
    numero: str,
    motivo_codigo: str,
    cantidades: dict | None = None,
    descripcion: str = "",
    fecha_anotacion: date | None = None,
    cuenta_reembolso: CuentaTesoreria | None = None,
    canal: str = "TRANSFERENCIA",
    usuario=None,
) -> NotaCreditoCompra:
    """Registra la NC del proveedor por devolución total o parcial de unidades."""
    usuario = usuario or usuario_actual.get()
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.estado != Compra.Estado.CONFIRMADA:
        raise CompraError("Solo se devuelve mercadería de una compra confirmada.")
    if compra.moneda != "PEN":
        raise CompraError(
            "La devolución de compras en moneda extranjera aún no está disponible; "
            "requiere el saldo en moneda de origen (P0-4)."
        )
    if fecha < compra.fecha:
        raise CompraError("La fecha de la nota no puede ser anterior a la compra.")
    if motivo_codigo not in MOTIVOS_IMPLEMENTADOS:
        raise CompraError("Este motivo de nota de crédito todavía no está implementado.")
    serie, numero = (serie or "").strip().upper()[:4], (numero or "").strip()[:20]
    if not serie or not numero:
        raise CompraError("Indica la serie y el número de la nota de crédito del proveedor.")
    if fecha_anotacion is not None and fecha_anotacion < fecha:
        raise CompraError("La fecha de anotación no puede ser anterior a la emisión de la nota.")
    if compra.costos.exists():
        raise CompraError(
            "La compra tiene costos de internamiento prorrateados: el flete es de otro "
            "proveedor y su tratamiento en la devolución está pendiente de definir."
        )
    if MovimientoTesoreria.objects.filter(
        empresa=compra.empresa, origen_tipo="COMPRA_PAGO", origen_id=compra.pk, fecha__gt=fecha
    ).exists():
        raise CompraError("Ya hay un pago posterior a la fecha de la nota; revisa el orden de las operaciones.")
    if compra.notas_credito.filter(fecha__gt=fecha).exists():
        raise CompraError("Ya hay una devolución posterior; registra las notas en orden cronológico.")
    if NotaCreditoCompra.objects.filter(
        compra__proveedor=compra.proveedor, serie__iexact=serie, numero__iexact=numero
    ).exists():
        raise CompraError(f"La nota {serie}-{numero} ya está registrada para este proveedor.")

    lineas = list(compra.lineas.select_related("producto", "producto__unidad"))
    if not lineas:
        raise CompraError("La compra no tiene líneas.")

    if cantidades is None:
        cantidades = {linea.pk: linea.cantidad for linea in lineas}

    previas = {
        fila["compra_linea_id"]: fila
        for fila in NotaCreditoCompraLinea.objects.filter(nota__compra=compra)
        .values("compra_linea_id")
        .annotate(
            cantidad_previa=Sum("cantidad"),
            base_previa=Sum("base"),
            igv_previo=Sum("igv"),
        )
    }

    seleccion: list[tuple[CompraLinea, Decimal]] = []
    for linea in lineas:
        pedida = Decimal(str(cantidades.get(linea.pk, 0) or 0))
        if pedida <= 0:
            continue
        anterior = previas.get(linea.pk, {})
        disponible = linea.cantidad - (anterior.get("cantidad_previa") or Decimal("0"))
        if pedida > disponible:
            raise CompraError(f"No puedes devolver {pedida} de {linea.producto.sku}: solo quedan {disponible}.")
        seleccion.append((linea, pedida))

    if not seleccion:
        raise CompraError("No indicaste ninguna cantidad a devolver.")

    if motivo_codigo == "06":
        if previas:
            raise CompraError("La devolución total debe cubrir toda la compra y no tener notas previas.")
        if len(seleccion) != len(lineas) or any(
            Decimal(str(cantidades.get(linea.pk, 0) or 0)) != linea.cantidad for linea in lineas
        ):
            raise CompraError("La devolución total debe cubrir todas las unidades de la compra.")

    nota = NotaCreditoCompra.objects.create(
        compra=compra,
        fecha=fecha,
        fecha_anotacion=fecha_anotacion,
        serie=serie,
        numero=numero,
        motivo_codigo=motivo_codigo,
        motivo=(descripcion or dict(NotaCreditoCompra.Motivo.choices)[motivo_codigo])[:200],
        creada_por=usuario,
    )

    base_total = CERO
    igv_total = CERO
    costo_total = CERO

    for linea, pedida in seleccion:
        anterior = previas.get(linea.pk, {})
        cantidad_previa = anterior.get("cantidad_previa") or Decimal("0")
        proporcion = (cantidad_previa + pedida) / linea.cantidad
        igv = _cent(linea.igv * proporcion) - (anterior.get("igv_previo") or CERO)
        movimiento = salir_de_compra(
            empresa=compra.empresa,
            producto=linea.producto,
            fecha=fecha,
            cantidad=pedida,
            compra_id=compra.pk,
            origen_id=nota.pk,
            glosa=f"Devolución {serie}-{numero}",
        )
        costo = _cent(movimiento.costo_total)
        if compra.con_credito:
            # Sin costos de internamiento, el costo de la capa es exactamente la base.
            base = costo
            total = base + igv
        else:
            base = _cent(linea.base * proporcion) - (anterior.get("base_previa") or CERO)
            total = costo
            igv = total - base
            if igv < 0 or base < 0:
                raise CompraError("La devolución no se puede representar con la precisión del centavo.")

        NotaCreditoCompraLinea.objects.create(
            nota=nota,
            compra_linea=linea,
            cantidad=pedida,
            base=base,
            igv=igv,
            total=total,
            costo_total=costo,
        )
        base_total += base
        igv_total += igv
        costo_total += costo

    nota.base = _cent(base_total)
    nota.igv = _cent(igv_total)
    nota.total = _cent(base_total + igv_total)
    nota.costo = _cent(costo_total)
    nota.save(update_fields=["base", "igv", "total", "costo"])

    cuentas = _cuentas_contables()
    documento = f"{serie}-{numero}"
    asiento_lineas = [
        (cuentas[CUENTA_POR_PAGAR], nota.total, CERO, f"Nota de crédito {documento}"),
        (cuentas[CUENTA_INVENTARIO], CERO, nota.costo, "Salida de inventario"),
    ]
    if nota.igv > 0:
        asiento_lineas.append((cuentas[CUENTA_IGV], CERO, nota.igv, "IGV devuelto"))
    asiento = postear_lineas(
        empresa=compra.empresa,
        fecha=fecha,
        tipo="DEVOLUCION_COMPRA",
        glosa=f"Devolución {documento} · {compra.proveedor.nombre}"[:255],
        lineas=asiento_lineas,
        origen_tipo="DEVOLUCION_COMPRA",
        origen_id=nota.pk,
        usuario=usuario,
    )

    if cuenta_reembolso is not None:
        _validar_cuenta_reembolso(cuenta_reembolso, compra.empresa)
        pendiente = max(CERO, -saldo_4212(compra))
        if pendiente <= 0:
            raise CompraError(
                "La compra no está pagada en exceso: no hay reembolso que registrar. "
                "La nota solo reduce la deuda pendiente."
            )
        _registrar_dinero(
            nota=nota,
            cuenta=cuenta_reembolso,
            fecha=fecha,
            importe=pendiente,
            canal=canal,
            usuario=usuario,
        )

    HistorialDocumento.objects.create(
        empresa=compra.empresa,
        tipo=HistorialDocumento.Tipo.COMPRA,
        documento_id=compra.pk,
        usuario=usuario,
        accion="DEVOLUCION",
        detalle=(
            f"Nota de crédito {documento} por S/ {nota.total}: "
            + ", ".join(f"{linea.producto.sku} × {cantidad}" for linea, cantidad in seleccion)
            + f". Asiento {asiento.numero}."
        )[:2000],
    )
    compra.pagada = saldo_4212(compra) <= 0
    compra.save(update_fields=["pagada"])
    return nota


@transaction.atomic
def registrar_reembolso(
    *,
    nota: NotaCreditoCompra,
    cuenta: CuentaTesoreria,
    fecha: date,
    canal: str = "TRANSFERENCIA",
    importe=None,
    usuario=None,
) -> Decimal:
    """Registra el dinero que el proveedor devuelve por una nota ya emitida."""
    usuario = usuario or usuario_actual.get()
    nota = NotaCreditoCompra.objects.select_for_update().select_related("compra").get(pk=nota.pk)
    compra = nota.compra
    if fecha < nota.fecha:
        raise CompraError("El reembolso no puede ser anterior a la nota de crédito.")
    pendiente = max(CERO, -saldo_4212(compra))
    if pendiente <= 0:
        raise CompraError("No hay reembolso pendiente para esta compra.")
    valor = pendiente if importe in (None, "") else _cent(Decimal(str(importe)))
    if valor <= 0:
        raise CompraError("El reembolso debe ser mayor que cero.")
    if valor > pendiente:
        raise CompraError(f"El reembolso pendiente es S/ {pendiente}.")

    _validar_cuenta_reembolso(cuenta, compra.empresa)
    _registrar_dinero(nota=nota, cuenta=cuenta, fecha=fecha, importe=valor, canal=canal, usuario=usuario)
    HistorialDocumento.objects.create(
        empresa=compra.empresa,
        tipo=HistorialDocumento.Tipo.COMPRA,
        documento_id=compra.pk,
        usuario=usuario,
        accion="REEMBOLSO",
        detalle=f"Reembolso de S/ {valor} por {nota.serie}-{nota.numero} en {cuenta.nombre}.",
    )
    return valor

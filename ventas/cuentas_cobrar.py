"""Consulta documental de ventas al crédito a una fecha de corte."""

from decimal import Decimal

from django.db.models import DecimalField, Exists, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from tesoreria.models import MovimientoTesoreria

from .models import CobroVenta, CuotaVenta, NotaCredito, NotaDebito, Venta


def _total_por_venta(modelo, campo, fecha):
    return (
        modelo.objects.filter(venta_id=OuterRef("pk"), fecha__lte=fecha)
        .order_by()
        .values("venta_id")
        .annotate(suma=Sum(campo))
        .values("suma")[:1]
    )


def cuentas_por_cobrar(*, empresa, fecha):
    """Usa las fechas de los documentos; no distribuye pagos entre cuotas."""
    importe = DecimalField(max_digits=18, decimal_places=2)
    cero = Value(Decimal("0"), output_field=importe)
    movimiento_previo = MovimientoTesoreria.objects.filter(
        empresa_id=OuterRef("empresa_id"),
        origen_tipo="VENTA",
        origen_id=OuterRef("pk"),
        tipo="INGRESO",
        fecha__lte=fecha,
    )
    primer_vencimiento = CuotaVenta.objects.filter(venta_id=OuterRef("pk")).order_by("vencimiento", "pk")
    return (
        Venta.objects.filter(
            empresa=empresa,
            estado=Venta.Estado.CONFIRMADA,
            condicion=Venta.Condicion.CREDITO,
            fecha__lte=fecha,
        )
        .select_related("cliente")
        .annotate(
            cobrado=Coalesce(Subquery(_total_por_venta(CobroVenta, "importe", fecha), output_field=importe), cero),
            credito=Coalesce(Subquery(_total_por_venta(NotaCredito, "total", fecha), output_field=importe), cero),
            debito=Coalesce(Subquery(_total_por_venta(NotaDebito, "total", fecha), output_field=importe), cero),
            primer_vencimiento=Subquery(primer_vencimiento.values("vencimiento")[:1]),
            requiere_revision=Exists(movimiento_previo),
        )
        .annotate(saldo_documentado=F("total") + F("debito") - F("credito") - F("cobrado"))
        .order_by("-fecha", "-pk")
    )

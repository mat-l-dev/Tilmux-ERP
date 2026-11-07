"""Enlaces a documentos de la misma empresa para movimientos conocidos."""

from collections import defaultdict

from django.urls import reverse

from compras.models import Compra
from compras.models_gasto import Gasto, PagoGasto
from ventas.models import CobroVenta, Venta


def enlazar_documentos(*, empresa, movimientos):
    ids = defaultdict(set)
    for movimiento in movimientos:
        if movimiento.origen_id:
            ids[movimiento.origen_tipo].add(movimiento.origen_id)

    destinos = {}
    for compra in Compra.objects.filter(empresa=empresa, pk__in=ids["COMPRA_PAGO"]):
        destinos[("COMPRA_PAGO", compra.pk)] = ("Compra", reverse("compras:detalle", args=[compra.pk]))
    for gasto in Gasto.objects.filter(empresa=empresa, pk__in=ids["GASTO"]):
        destinos[("GASTO", gasto.pk)] = ("Gasto", reverse("compras:detalle_gasto", args=[gasto.pk]))
    for pago in PagoGasto.objects.filter(gasto__empresa=empresa, pk__in=ids["PAGO_GASTO"]):
        destinos[("PAGO_GASTO", pago.pk)] = ("Gasto", reverse("compras:detalle_gasto", args=[pago.gasto_id]))
    for venta in Venta.objects.filter(empresa=empresa, pk__in=ids["VENTA"]):
        destinos[("VENTA", venta.pk)] = ("Venta", reverse("ventas:detalle", args=[venta.pk]))
    for cobro in CobroVenta.objects.filter(venta__empresa=empresa, pk__in=ids["COBRO_VENTA"]):
        destinos[("COBRO_VENTA", cobro.pk)] = ("Venta", reverse("ventas:detalle", args=[cobro.venta_id]))

    for movimiento in movimientos:
        movimiento.documento_etiqueta, movimiento.documento_url = destinos.get(
            (movimiento.origen_tipo, movimiento.origen_id), (None, None)
        )

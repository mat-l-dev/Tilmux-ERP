"""Identificación compartida de comprobantes de compras y gastos."""

from django.db.models.functions import Trim, Upper

from .models import Compra
from .models_gasto import Gasto


def _numero_normalizado(numero: str) -> str:
    numero = numero.strip().upper()
    return (numero.lstrip("0") or "0") if numero.isdecimal() else numero


def buscar_comprobante(*, empresa, proveedor, tipo_doc, serie, numero, compra_id=None):
    """Devuelve el origen de un comprobante ya registrado, sin contar provisiones."""
    serie = serie.strip().upper()
    numero = _numero_normalizado(numero)
    if not serie or not numero or tipo_doc not in {"FACTURA", "BOLETA"}:
        return None

    filtros = {"empresa": empresa, "proveedor": proveedor, "tipo_doc": tipo_doc}
    compras = Compra.objects.filter(**filtros).exclude(
        estado__in=[Compra.Estado.BORRADOR, Compra.Estado.PENDIENTE]
    )
    if compra_id is not None:
        compras = compras.exclude(pk=compra_id)
    gastos = Gasto.objects.filter(**filtros, provision=False)
    for etiqueta, queryset in (("compra", compras), ("gasto", gastos)):
        numeros = queryset.annotate(serie_normalizada=Upper(Trim("serie"))).filter(
            serie_normalizada=serie
        ).values_list("numero", flat=True)
        if any(_numero_normalizado(valor) == numero for valor in numeros):
            return etiqueta
    return None

"""Comparación acotada de facturas y boletas de la propuesta RCE."""

import calendar
from datetime import date, datetime

from django.db.models.functions import Coalesce
from django.urls import reverse

from compras.models import Compra
from compras.models_gasto import Gasto

from .sire import _cabecera, _es_fila_total, _normalizar, _numero_validado

ENCABEZADOS = {
    "tipo": "tipo cp/doc.",
    "serie": "serie del cdp",
    "numero": "nro cp o doc. nro inicial (rango)",
    "numero_final": "nro final (rango)",
    "tipo_identidad": "tipo doc identidad",
    "emisor": "nro doc identidad",
    "fecha": "fecha de emisión",
    "total": "total cp",
    "moneda": "moneda",
}
TIPOS = {"01": "FACTURA", "03": "BOLETA"}


def _texto(valor):
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor or "").strip().upper()


def _clave(emisor, tipo, serie, numero):
    emisor, serie, numero = _texto(emisor), _texto(serie), _texto(numero)
    if not (len(emisor) == 11 and emisor.isascii() and emisor.isdecimal()
            and serie and numero and numero.isascii() and numero.isdecimal()):
        return None
    return emisor, tipo, serie, numero.lstrip("0") or "0"


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def comparar_rce(*, filas, empresa, anio, mes):
    cabecera, *_ = _cabecera(filas)
    titulos = [_normalizar(celda) for celda in filas[cabecera]]
    if any(titulos.count(nombre) != 1 for nombre in ENCABEZADOS.values()):
        return None
    indices = {nombre: titulos.index(titulo) for nombre, titulo in ENCABEZADOS.items()}
    archivo, sistema = {}, {}
    omitidos_archivo = omitidos_sistema = 0
    for fila in filas[cabecera + 1:]:
        if not any(celda not in (None, "") for celda in fila) or _es_fila_total(fila):
            continue
        if len(fila) <= max(indices.values()):
            omitidos_archivo += 1
            continue
        datos = {nombre: fila[indice] for nombre, indice in indices.items()}
        tipo = TIPOS.get(_texto(datos["tipo"]).zfill(2))
        clave = _clave(datos["emisor"], tipo, datos["serie"], datos["numero"]) if tipo else None
        fecha = _fecha(datos["fecha"])
        total = _numero_validado(datos["total"])
        if (not clave or not fecha or total is None or _texto(datos["moneda"]) != "PEN"
                or _texto(datos["tipo_identidad"]) != "6" or _texto(datos["numero_final"])):
            omitidos_archivo += 1
            continue
        archivo.setdefault(clave, []).append({"fecha": fecha, "total": total})

    desde, hasta = date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])
    compras = Compra.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
        empresa=empresa, estado=Compra.Estado.CONFIRMADA, fecha_tributaria__range=(desde, hasta),
        tipo_doc__in=("FACTURA", "BOLETA"),
    ).select_related("proveedor")
    gastos = Gasto.objects.annotate(fecha_tributaria=Coalesce("fecha_anotacion", "fecha")).filter(
        empresa=empresa, provision=False, fecha_tributaria__range=(desde, hasta),
        tipo_doc__in=("FACTURA", "BOLETA"),
    ).exclude(estado=Gasto.Estado.ANULADO).select_related("proveedor")
    for clase, documentos in (("compra", compras), ("gasto", gastos)):
        for documento in documentos:
            clave = _clave(documento.proveedor.numero_doc, documento.tipo_doc, documento.serie, documento.numero)
            if not clave or documento.proveedor.tipo_doc != "RUC" or (clase == "compra" and documento.moneda != "PEN"):
                omitidos_sistema += 1
                continue
            sistema.setdefault(clave, []).append({
                "fecha": documento.fecha, "total": documento.total,
                "url": reverse("compras:detalle" if clase == "compra" else "compras:detalle_gasto",
                               args=[documento.pk]),
            })

    resultado = {"solo_archivo": [], "solo_sistema": [], "diferentes": [], "ambiguos": [],
                 "coinciden": 0, "omitidos_archivo": omitidos_archivo, "omitidos_sistema": omitidos_sistema}
    for clave in sorted(archivo.keys() | sistema.keys()):
        externos, internos = archivo.get(clave, []), sistema.get(clave, [])
        fila = {"ruc": clave[0], "tipo": clave[1], "documento": f"{clave[2]}-{clave[3]}",
                "archivo": externos[0] if len(externos) == 1 else None,
                "sistema": internos[0] if len(internos) == 1 else None}
        if len(externos) > 1 or len(internos) > 1:
            resultado["ambiguos"].append(fila)
        elif not externos:
            resultado["solo_sistema"].append(fila)
        elif not internos:
            resultado["solo_archivo"].append(fila)
        elif internos[0]["fecha"] != externos[0]["fecha"] or internos[0]["total"] != externos[0]["total"]:
            resultado["diferentes"].append(fila)
        else:
            resultado["coinciden"] += 1
    return resultado

"""Filtros seguros para la consulta de movimientos."""

from datetime import date

from django.db.models import Q


def filtrar_movimientos(queryset, parametros):
    errores = []
    texto = parametros.get("q", "").strip()
    if len(texto) > 200:
        errores.append("La búsqueda no puede tener más de 200 caracteres.")
    elif texto:
        queryset = queryset.filter(Q(concepto__icontains=texto) | Q(cuenta__nombre__icontains=texto))

    fechas = {}
    for campo, nombre in (("desde", "desde"), ("hasta", "hasta")):
        valor = parametros.get(campo, "").strip()
        if valor:
            try:
                fecha = date.fromisoformat(valor)
                if fecha.isoformat() != valor:
                    raise ValueError
                fechas[campo] = fecha
            except ValueError:
                errores.append(f"Indica una fecha válida en «{nombre}».")
    if fechas.get("desde") and fechas.get("hasta") and fechas["desde"] > fechas["hasta"]:
        errores.append("La fecha inicial no puede ser posterior a la final.")
    if "desde" in fechas:
        queryset = queryset.filter(fecha__gte=fechas["desde"])
    if "hasta" in fechas:
        queryset = queryset.filter(fecha__lte=fechas["hasta"])

    estado = parametros.get("conciliacion", "")
    if estado == "conciliado":
        queryset = queryset.filter(conciliado=True, conciliacion_activa=True)
    elif estado == "pendiente":
        queryset = queryset.filter(conciliado=False, conciliacion_activa=False)
    elif estado == "revisar":
        queryset = queryset.filter(Q(conciliado=True, conciliacion_activa=False)
                                   | Q(conciliado=False, conciliacion_activa=True))
    elif estado:
        errores.append("Selecciona un estado de conciliación válido.")
    return (queryset.none() if errores else queryset), errores

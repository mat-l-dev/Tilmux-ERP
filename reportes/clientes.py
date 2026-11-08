"""Datos del cliente para los reportes documentales de ventas."""

TIPOS_IDENTIDAD = {"DNI": "01", "CE": "04", "RUC": "06", "PAS": "07"}


def nombre_cliente(venta):
    if venta.cliente_nombre:
        return venta.cliente_nombre
    if venta.cliente:
        return venta.cliente.nombre
    return "Consumidor final"


def tipo_identidad_cliente(venta):
    if not venta.cliente or not venta.cliente.numero_doc:
        return ""
    return TIPOS_IDENTIDAD.get(venta.cliente.tipo_doc, "")

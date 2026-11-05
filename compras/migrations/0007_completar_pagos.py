"""Completa el monto en moneda de origen y marca las compras ya pagadas."""

from django.db import migrations


def completar(apps, schema_editor):
    Compra = apps.get_model("compras", "Compra")
    Movimiento = apps.get_model("tesoreria", "MovimientoTesoreria")

    for compra in Compra.objects.filter(total_moneda_origen=0):
        compra.total_moneda_origen = compra.total
        compra.save(update_fields=["total_moneda_origen"])

    for compra in Compra.objects.filter(pagada=False, estado="CONFIRMADA"):
        movimiento = (
            Movimiento.objects.filter(
                origen_tipo="COMPRA", origen_id=compra.pk, tipo="EGRESO"
            )
            .order_by("fecha")
            .first()
        )
        if movimiento:
            compra.pagada = True
            compra.fecha_pago = movimiento.fecha
            compra.save(update_fields=["pagada", "fecha_pago"])


class Migration(migrations.Migration):
    dependencies = [
        ("compras", "0006_compra_fecha_pago_compra_pagada_and_more"),
        ("tesoreria", "0001_initial"),
    ]
    operations = [migrations.RunPython(completar, migrations.RunPython.noop)]

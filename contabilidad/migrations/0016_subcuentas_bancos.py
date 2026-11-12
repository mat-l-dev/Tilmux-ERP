"""Subcuentas analíticas por banco bajo la 1061."""

from django.db import migrations


def crear(apps, schema_editor):
    Cuenta = apps.get_model("contabilidad", "Cuenta")
    CuentaTesoreria = apps.get_model("catalogo", "CuentaTesoreria")
    for cuenta in CuentaTesoreria.objects.filter(tipo="BANCO").order_by("pk"):
        actual = cuenta.cuenta_contable
        if actual is not None and len(actual.codigo) == 6 and actual.codigo.startswith("1061") and actual.codigo != "1061":
            continue
        version = actual.version if actual is not None else "2026"
        padre = Cuenta.objects.filter(version=version, codigo="1061").first()
        if padre is None:
            continue
        codigos = set(
            Cuenta.objects.filter(version=version, codigo__startswith="1061").values_list(
                "codigo", flat=True
            )
        )
        sufijos = [int(c[4:]) for c in codigos if len(c) == 6 and c[4:].isdigit()]
        siguiente = max(sufijos, default=0) + 1
        while f"1061{siguiente:02d}" in codigos:
            siguiente += 1
        subcuenta = Cuenta.objects.create(
            version=version,
            codigo=f"1061{siguiente:02d}",
            nombre=f"{cuenta.nombre} · subcuenta 1061",
            padre="1061",
            elemento=padre.elemento,
            naturaleza=padre.naturaleza,
            admite_movimiento=True,
            activa=True,
        )
        cuenta.cuenta_contable = subcuenta
        cuenta.save(update_fields=["cuenta_contable"])


class Migration(migrations.Migration):
    dependencies = [
        ("contabilidad", "0015_pagoigv621_declaracionigv621_casilla_100_and_more"),
        ("catalogo", "0001_initial"),
    ]

    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]


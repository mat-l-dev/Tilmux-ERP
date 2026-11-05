"""Las boletas ya registradas no otorgan crédito ni sustentan gasto."""

from django.db import migrations


def marcar_boletas(apps, schema_editor):
    Gasto = apps.get_model("compras", "Gasto")
    Gasto.objects.filter(tipo_doc="BOLETA").update(
        con_credito=False, deducible=False
    )


class Migration(migrations.Migration):
    dependencies = [("compras", "0003_gasto_con_credito_gasto_deducible")]
    operations = [migrations.RunPython(marcar_boletas, migrations.RunPython.noop)]

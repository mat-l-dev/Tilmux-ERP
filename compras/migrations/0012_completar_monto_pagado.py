"""Las compras ya marcadas como pagadas tienen su monto completo."""

from django.db import migrations


def completar(apps, schema_editor):
    Compra = apps.get_model("compras", "Compra")
    for compra in Compra.objects.filter(pagada=True, monto_pagado=0):
        compra.monto_pagado = compra.total
        compra.save(update_fields=["monto_pagado"])


class Migration(migrations.Migration):
    dependencies = [("compras", "0011_compra_monto_pagado")]
    operations = [migrations.RunPython(completar, migrations.RunPython.noop)]

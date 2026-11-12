"""Completa ``pagado_moneda_origen`` en compras en soles ya pagadas.

La migración ``compras/0021`` agregó el campo con default 0 pero no lo rellenó
en las compras históricas. En soles, ``pagado_moneda_origen`` debe coincidir
con ``monto_pagado`` para que ``saldo_moneda_origen`` no mienta.

No se tocan compras en moneda extranjera: su importe en la moneda de origen
depende de los pagos y del tipo de cambio realmente aplicado, y no se puede
deducir de ``monto_pagado`` (que está en soles).
"""

from django.db import migrations
from django.db.models import F, Q


def rellenar_pagado_moneda_origen(apps, schema_editor):
    Compra = apps.get_model("compras", "Compra")
    criterio = Q(moneda="PEN", monto_pagado__gt=0) & (Q(pagado_moneda_origen=0) | Q(pagado_moneda_origen__isnull=True))
    return (
        Compra.objects.using(schema_editor.connection.alias)
        .filter(criterio)
        .update(pagado_moneda_origen=F("monto_pagado"))
    )


def reversa_noop(apps, schema_editor):
    """El relleno no se deshace: no hay forma de distinguir el valor original.

    Revertir esta migración dejaría el campo en 0 otra vez y volvería a mentir
    sobre el saldo en moneda de origen. Se deja documentado como noop.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("compras", "0021_compra_pagado_moneda_origen"),
    ]

    operations = [
        migrations.RunPython(rellenar_pagado_moneda_origen, reversa_noop),
    ]

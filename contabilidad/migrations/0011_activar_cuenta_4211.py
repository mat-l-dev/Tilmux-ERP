from django.db import migrations


def activar(apps, schema_editor):
    cuenta = apps.get_model("contabilidad", "Cuenta")
    cuenta.objects.using(schema_editor.connection.alias).filter(version="2026", codigo="4211").update(activa=True)


class Migration(migrations.Migration):
    dependencies = [("contabilidad", "0010_alter_asiento_tipo_operacion_alter_regla_tipo")]
    operations = [migrations.RunPython(activar, migrations.RunPython.noop)]

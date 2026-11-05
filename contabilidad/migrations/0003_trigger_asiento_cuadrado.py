"""La base de datos impide que un asiento quede descuadrado."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION tilmux_asiento_cuadrado() RETURNS trigger AS $$
DECLARE
    total_debe numeric;
    total_haber numeric;
    objetivo bigint;
BEGIN
    objetivo := COALESCE(NEW.asiento_id, OLD.asiento_id);

    SELECT COALESCE(SUM(debe), 0), COALESCE(SUM(haber), 0)
      INTO total_debe, total_haber
      FROM contabilidad_asientolinea
     WHERE asiento_id = objetivo;

    IF total_debe <> total_haber THEN
        RAISE EXCEPTION
            'Asiento % descuadrado: debe % contra haber %',
            objetivo, total_debe, total_haber;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER asiento_cuadrado
AFTER INSERT OR UPDATE OR DELETE ON contabilidad_asientolinea
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION tilmux_asiento_cuadrado();
"""

REVERTIR = """
DROP TRIGGER IF EXISTS asiento_cuadrado ON contabilidad_asientolinea;
DROP FUNCTION IF EXISTS tilmux_asiento_cuadrado();
"""


class Migration(migrations.Migration):
    dependencies = [("contabilidad", "0002_regla_asiento_asientolinea_reglalinea_and_more")]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERTIR),
    ]

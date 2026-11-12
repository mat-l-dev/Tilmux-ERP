import importlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.db import connection

from compras.models import Compra

from .test_invariantes import BaseContable

migracion = importlib.import_module("compras.migrations.0022_backfill_pagado_moneda_origen")


class BackfillPagadoMonedaOrigenTest(BaseContable):
    def crear(self, numero, *, moneda="PEN", monto_pagado="0", pagado="0", pagada=False):
        return Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 10),
            tipo_doc="FACTURA",
            serie="F001",
            numero=numero,
            moneda=moneda,
            total=Decimal("118.00"),
            total_moneda_origen=Decimal("100.00") if moneda != "PEN" else Decimal("118.00"),
            monto_pagado=Decimal(monto_pagado),
            pagado_moneda_origen=Decimal(pagado),
            pagada=pagada,
        )

    def test_rellena_solo_compras_pen_pagadas_con_el_campo_en_cero(self):
        pen_pagada = self.crear("9001", monto_pagado="118.00", pagada=True)
        usd_pagada = self.crear("9002", moneda="USD", monto_pagado="50.00")
        pen_sin_pago = self.crear("9003")
        pen_ya_ok = self.crear("9004", monto_pagado="50.00", pagado="50.00")

        actualizados = migracion.rellenar_pagado_moneda_origen(
            apps=django_apps,
            schema_editor=SimpleNamespace(connection=connection),
        )

        self.assertEqual(actualizados, 1)
        pen_pagada.refresh_from_db()
        usd_pagada.refresh_from_db()
        pen_sin_pago.refresh_from_db()
        pen_ya_ok.refresh_from_db()
        self.assertEqual(pen_pagada.pagado_moneda_origen, pen_pagada.monto_pagado)
        self.assertEqual(pen_pagada.saldo_moneda_origen, Decimal("0"))
        self.assertEqual(usd_pagada.pagado_moneda_origen, Decimal("0"))
        self.assertEqual(pen_sin_pago.pagado_moneda_origen, Decimal("0"))
        self.assertEqual(pen_ya_ok.pagado_moneda_origen, Decimal("50.00"))

    def test_reversa_es_noop(self):
        pen_pagada = self.crear("9005", monto_pagado="118.00", pagada=True)
        migracion.rellenar_pagado_moneda_origen(
            apps=django_apps,
            schema_editor=SimpleNamespace(connection=connection),
        )
        migracion.reversa_noop(None, None)
        pen_pagada.refresh_from_db()
        self.assertEqual(pen_pagada.pagado_moneda_origen, Decimal("118.0000"))

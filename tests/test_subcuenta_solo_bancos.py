from datetime import date
from decimal import Decimal

from catalogo.models import CuentaTesoreria
from contabilidad.models import Asiento, Cuenta
from tesoreria.servicios import registrar, transferir
from tesoreria.subcuentas import saldo_contable, subcuenta_de

from .test_invariantes import BaseContable


class SubcuentaSoloBancosTest(BaseContable):
    def setUp(self):
        self.bcp = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="BCP")
        self.mp = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="Mercado Pago")
        self.caja = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="Caja")
        for cuenta, importe in ((self.bbva, "457.60"), (self.bcp, "444.00"), (self.mp, "1213.96")):
            registrar(
                empresa=self.empresa,
                cuenta=cuenta,
                fecha=date(2026, 11, 1),
                tipo="INGRESO",
                importe=Decimal(importe),
                concepto=f"Saldo inicial {cuenta.nombre}",
                tipo_regla="APORTE_CAPITAL",
            )

    def test_mp_a_bcp_asienta_contra_1031_sin_crear_subcuenta(self):
        cuentas_antes = Cuenta.objects.filter(version="2026").count()

        transferir(
            empresa=self.empresa,
            origen=self.mp,
            destino=self.bcp,
            fecha=date(2026, 11, 5),
            importe=Decimal("100.00"),
            concepto="Retiro de Mercado Pago a BCP",
        )

        asiento = Asiento.objects.filter(empresa=self.empresa, tipo_operacion="TRANSFERENCIA").latest("pk")
        self.assertEqual(asiento.lineas.get(cuenta__codigo="106102").debe, Decimal("100.00"))
        self.assertEqual(asiento.lineas.get(cuenta__codigo="1031").haber, Decimal("100.00"))
        self.assertEqual(Cuenta.objects.filter(version="2026").count(), cuentas_antes)
        self.assertFalse(Cuenta.objects.filter(version="2026", codigo="106103").exists())
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.cuenta_contable.codigo, "1031")

    def test_bcp_a_mp_asienta_contra_1031_sin_crear_subcuenta(self):
        cuentas_antes = Cuenta.objects.filter(version="2026").count()

        transferir(
            empresa=self.empresa,
            origen=self.bcp,
            destino=self.mp,
            fecha=date(2026, 11, 6),
            importe=Decimal("100.00"),
            concepto="Traspaso de BCP a Mercado Pago",
        )

        asiento = Asiento.objects.filter(empresa=self.empresa, tipo_operacion="TRANSFERENCIA").latest("pk")
        self.assertEqual(asiento.lineas.get(cuenta__codigo="1031").debe, Decimal("100.00"))
        self.assertEqual(asiento.lineas.get(cuenta__codigo="106102").haber, Decimal("100.00"))
        self.assertEqual(Cuenta.objects.filter(version="2026").count(), cuentas_antes)
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.cuenta_contable.codigo, "1031")

    def test_aceptacion_121396_de_mp_a_bcp_sin_106103(self):
        transferir(
            empresa=self.empresa,
            origen=self.mp,
            destino=self.bcp,
            fecha=date(2026, 11, 5),
            importe=Decimal("1213.96"),
            concepto="Retiro total de Mercado Pago a BCP",
        )

        self.assertEqual(saldo_contable(self.empresa, self.mp), Decimal("0.00"))
        self.assertEqual(saldo_contable(self.empresa, self.bcp), Decimal("1657.96"))
        self.assertEqual(saldo_contable(self.empresa, self.bbva), Decimal("457.60"))
        self.assertEqual(
            sum((saldo_contable(self.empresa, cuenta) for cuenta in (self.bbva, self.bcp)), Decimal("0")),
            Decimal("2115.56"),
        )
        self.assertFalse(Cuenta.objects.filter(version="2026", codigo="106103").exists())

    def test_subcuenta_de_no_toca_billetera_ni_caja(self):
        self.assertEqual(subcuenta_de(self.mp).codigo, "1031")
        self.assertEqual(subcuenta_de(self.caja).codigo, "101")
        cuentas_antes = Cuenta.objects.filter(version="2026").count()

        self.mp.nombre = "Mercado Pago (editada)"
        self.mp.save()
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.cuenta_contable.codigo, "1031")

        nueva = CuentaTesoreria.objects.create(
            empresa=self.empresa,
            nombre="Billetera de prueba",
            tipo=CuentaTesoreria.Tipo.BILLETERA,
            moneda="PEN",
            cuenta_contable=Cuenta.objects.get(version="2026", codigo="1031"),
        )
        nueva.refresh_from_db()
        self.assertEqual(nueva.cuenta_contable.codigo, "1031")
        self.assertEqual(Cuenta.objects.filter(version="2026").count(), cuentas_antes)

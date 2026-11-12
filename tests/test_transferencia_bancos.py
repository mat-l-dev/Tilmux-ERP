from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from catalogo.models import CuentaTesoreria
from contabilidad.impuestos import saldo_cuenta
from contabilidad.models import Asiento, Cuenta
from contabilidad.servicios import ContabilidadError, Montos, postear
from core.models import Perfil
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import registrar, transferir
from tesoreria.subcuentas import (
    reclasificar_historico,
    saldo_contable,
    saldo_tesoreria,
    subcuenta_de,
)

from .test_invariantes import BaseContable


class TransferenciaBancosTest(BaseContable):
    def setUp(self):
        self.bcp = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="BCP")
        self.registrar_saldos()

    def registrar_saldos(self):
        registrar(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=date(2026, 11, 1),
            tipo="INGRESO",
            importe=Decimal("457.60"),
            concepto="Saldo inicial BBVA",
            tipo_regla="APORTE_CAPITAL",
        )
        registrar(
            empresa=self.empresa,
            cuenta=self.bcp,
            fecha=date(2026, 11, 1),
            tipo="INGRESO",
            importe=Decimal("444.00"),
            concepto="Saldo inicial BCP",
            tipo_regla="APORTE_CAPITAL",
        )

    def transferir_200(self):
        return transferir(
            empresa=self.empresa,
            origen=self.bbva,
            destino=self.bcp,
            fecha=date(2026, 11, 15),
            importe=Decimal("200.00"),
            concepto="Traspaso a BCP",
        )

    def test_cada_banco_tiene_su_subcuenta_bajo_1061(self):
        subcuenta_bbva = subcuenta_de(self.bbva)
        subcuenta_bcp = subcuenta_de(self.bcp)

        self.assertTrue(subcuenta_bbva.codigo.startswith("1061"))
        self.assertTrue(subcuenta_bcp.codigo.startswith("1061"))
        self.assertNotEqual(subcuenta_bbva.codigo, "1061")
        self.assertNotEqual(subcuenta_bbva.pk, subcuenta_bcp.pk)
        self.assertEqual(subcuenta_bbva.padre, "1061")

    def test_saldos_iniciales_conciliados_por_banco(self):
        self.assertEqual(saldo_tesoreria(self.empresa, self.bbva), Decimal("457.60"))
        self.assertEqual(saldo_contable(self.empresa, self.bbva), Decimal("457.60"))
        self.assertEqual(saldo_tesoreria(self.empresa, self.bcp), Decimal("444.00"))
        self.assertEqual(saldo_contable(self.empresa, self.bcp), Decimal("444.00"))

    def test_transferencia_200_asienta_por_subcuenta_y_mantiene_el_total_1061(self):
        total_antes = saldo_cuenta(self.empresa, "1061", date(2026, 11, 30))

        self.transferir_200()

        total_despues = saldo_cuenta(self.empresa, "1061", date(2026, 11, 30))
        self.assertEqual(total_despues, total_antes)
        self.assertEqual(saldo_cuenta(self.empresa, "1061", date(2026, 11, 30)), Decimal("-901.60"))

        subcuenta_bbva = subcuenta_de(self.bbva)
        subcuenta_bcp = subcuenta_de(self.bcp)
        self.assertEqual(saldo_contable(self.empresa, self.bbva), Decimal("257.60"))
        self.assertEqual(saldo_contable(self.empresa, self.bcp), Decimal("644.00"))
        self.assertEqual(saldo_tesoreria(self.empresa, self.bbva), Decimal("257.60"))
        self.assertEqual(saldo_tesoreria(self.empresa, self.bcp), Decimal("644.00"))

        asiento = Asiento.objects.filter(empresa=self.empresa, tipo_operacion="TRANSFERENCIA").latest("pk")
        self.assertEqual(asiento.lineas.get(cuenta=subcuenta_bcp).debe, Decimal("200.00"))
        self.assertEqual(asiento.lineas.get(cuenta=subcuenta_bbva).haber, Decimal("200.00"))
        self.assertFalse(asiento.lineas.filter(cuenta__codigo="1061").exists())

    def test_transferencia_a_la_misma_cuenta_esta_bloqueada(self):
        with self.assertRaisesMessage(ContabilidadError, "no pueden ser la misma"):
            transferir(
                empresa=self.empresa,
                origen=self.bbva,
                destino=self.bbva,
                fecha=date(2026, 11, 15),
                importe=Decimal("10.00"),
                concepto="No debe registrarse",
            )

    def test_dos_cuentas_con_la_misma_subcuenta_estan_bloqueadas(self):
        subcuenta = subcuenta_de(self.bbva)
        CuentaTesoreria.objects.filter(pk__in=[self.bbva.pk, self.bcp.pk]).update(cuenta_contable=subcuenta)
        self.bbva.refresh_from_db()
        self.bcp.refresh_from_db()

        with self.assertRaisesMessage(ContabilidadError, "subcuenta contable distinta"):
            self.transferir_200()

    def test_varias_transferencias_mantienen_la_conciliacion_por_banco(self):
        self.transferir_200()
        transferir(
            empresa=self.empresa,
            origen=self.bcp,
            destino=self.bbva,
            fecha=date(2026, 11, 16),
            importe=Decimal("50.00"),
            concepto="Devolución parcial",
        )
        transferir(
            empresa=self.empresa,
            origen=self.bbva,
            destino=self.bcp,
            fecha=date(2026, 11, 17),
            importe=Decimal("30.00"),
            concepto="Segundo traspaso",
        )

        self.assertEqual(saldo_contable(self.empresa, self.bbva), Decimal("277.60"))
        self.assertEqual(saldo_tesoreria(self.empresa, self.bbva), Decimal("277.60"))
        self.assertEqual(saldo_contable(self.empresa, self.bcp), Decimal("624.00"))
        self.assertEqual(saldo_tesoreria(self.empresa, self.bcp), Decimal("624.00"))
        self.assertEqual(saldo_cuenta(self.empresa, "1061", date(2026, 11, 30)), Decimal("-901.60"))

    def test_solo_la_1061_agregada_no_cambia_ni_crea_cuentas_fuera(self):
        antes = saldo_cuenta(self.empresa, "1061", date(2026, 11, 30))
        self.transferir_200()

        self.assertEqual(saldo_cuenta(self.empresa, "1061", date(2026, 11, 30)), antes)
        self.assertEqual(Cuenta.objects.filter(version="2026", codigo__startswith="1061").count(), 3)

    def test_pantalla_de_tesoreria_muestra_la_subcuenta_y_su_saldo(self):
        usuario = get_user_model().objects.create_superuser(username="bancos", password="test")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()

        respuesta = self.client.get(reverse("tesoreria:movimientos"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, subcuenta_de(self.bbva).codigo)
        self.assertContains(respuesta, "Saldo contable")
        self.assertContains(respuesta, "457,60")


class ReclasificacionHistoricaTest(BaseContable):
    """Los saldos históricos asentados en la 1061 se mueven a cada subcuenta."""

    def test_reclasifica_el_saldo_historico_y_concilia_por_banco(self):
        padre = Cuenta.objects.get(version="2026", codigo="1061")
        bcp = CuentaTesoreria.objects.get(empresa=self.empresa, nombre="BCP")
        for banco, importe, nombre in (
            (self.bbva, Decimal("457.60"), "BBVA"),
            (bcp, Decimal("444.00"), "BCP"),
        ):
            postear(
                empresa=self.empresa,
                fecha=date(2026, 11, 1),
                tipo="APORTE_CAPITAL",
                glosa=f"Saldo histórico {nombre}",
                montos=Montos(total=importe),
                cuenta_medio=padre,
            )
            MovimientoTesoreria.objects.create(
                empresa=self.empresa,
                cuenta=banco,
                fecha=date(2026, 11, 1),
                tipo=MovimientoTesoreria.Tipo.INGRESO,
                importe=importe,
                concepto=f"Saldo histórico {nombre}",
            )
        total_antes = saldo_cuenta(self.empresa, "1061", date(2026, 11, 30))

        movimientos = reclasificar_historico(self.empresa, date(2026, 11, 30))

        self.assertEqual(len(movimientos), 2)
        self.assertEqual(saldo_contable(self.empresa, self.bbva), Decimal("457.60"))
        self.assertEqual(saldo_contable(self.empresa, bcp), Decimal("444.00"))
        self.assertEqual(saldo_cuenta(self.empresa, "1061", date(2026, 11, 30)), total_antes)
        self.assertEqual(reclasificar_historico(self.empresa, date(2026, 11, 30)), [])

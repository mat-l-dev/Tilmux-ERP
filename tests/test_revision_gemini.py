from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from contabilidad.impuestos import _igv_del_periodo, pagar_igv
from contabilidad.servicios import ContabilidadError
from tesoreria.servicios import transferir


class ValidacionesRevisionTest(SimpleTestCase):
    def setUp(self):
        self.empresa = SimpleNamespace(pk=1)
        self.origen = SimpleNamespace(
            pk=1, empresa_id=1, activa=True, cuenta_contable_id=1,
            cuenta_contable=object(), moneda="PEN", nombre="Origen",
        )
        self.destino = SimpleNamespace(
            pk=2, empresa_id=1, activa=True, cuenta_contable_id=2,
            cuenta_contable=object(), moneda="PEN", nombre="Destino",
        )

    def transferencia(self, importe):
        return transferir.__wrapped__(
            empresa=self.empresa, origen=self.origen, destino=self.destino,
            fecha=date(2026, 11, 1), importe=importe, concepto="Prueba",
        )

    @patch("tesoreria.servicios.postear")
    @patch("tesoreria.servicios.MovimientoTesoreria.objects.create")
    def test_transferencia_en_dolares_no_registra_asiento_sin_conversion(self, crear, postear):
        self.origen.moneda = self.destino.moneda = "USD"
        with self.assertRaises(ContabilidadError):
            self.transferencia(Decimal("10"))
        crear.assert_not_called()
        postear.assert_not_called()

    @patch("tesoreria.servicios.postear")
    @patch("tesoreria.servicios.MovimientoTesoreria.objects.create")
    def test_transferencia_no_redondea_importes_silenciosamente(self, crear, postear):
        with self.assertRaises(ContabilidadError):
            self.transferencia(Decimal("1.005"))
        crear.assert_not_called()
        postear.assert_not_called()

    @patch("contabilidad.impuestos.HistorialDocumento.objects.create")
    @patch("contabilidad.impuestos.asiento_igv", return_value=None)
    @patch("tesoreria.servicios.registrar")
    @patch("contabilidad.impuestos.igv_pendiente", return_value=Decimal("10"))
    @patch("contabilidad.impuestos.Periodo.objects.filter")
    @patch("contabilidad.impuestos.periodo_de")
    @patch("contabilidad.impuestos.Empresa.objects.select_for_update")
    def test_pago_igv_no_acepta_saldo_temporal_como_base(self, *mocks):
        with self.assertRaises(ContabilidadError):
            pagar_igv.__wrapped__(
                self.empresa, date(2026, 11, 1), Decimal("1"), self.origen,
                2026, 10, saldo_favor_anterior=Decimal("0"),
            )

    @patch("contabilidad.impuestos.calculo", return_value={"resultado": Decimal("215.38")})
    def test_comparacion_rechaza_saldo_negativo(self, calculo):
        with self.assertRaises(ContabilidadError):
            _igv_del_periodo(self.empresa, 2026, 10, Decimal("-1"))

    @patch("tesoreria.servicios.postear")
    @patch("tesoreria.servicios.MovimientoTesoreria.objects.create")
    def test_transferencia_en_soles_conserva_importe(self, crear, postear):
        self.transferencia(Decimal("10.25"))
        self.assertEqual(crear.call_count, 2)
        self.assertEqual(postear.call_args.kwargs["montos"].total, Decimal("10.25"))

    @patch("contabilidad.impuestos.HistorialDocumento.objects.create")
    @patch("contabilidad.impuestos.asiento_igv", return_value=None)
    @patch("tesoreria.servicios.registrar")
    @patch("contabilidad.impuestos.igv_pendiente", return_value=Decimal("10"))
    @patch("contabilidad.impuestos.Periodo.objects.filter")
    @patch("contabilidad.impuestos.periodo_de")
    @patch("contabilidad.impuestos.Empresa.objects.select_for_update")
    def test_pago_igv_no_usa_cuenta_en_dolares(self, bloquear, *mocks):
        self.origen.moneda = "USD"
        with self.assertRaises(ContabilidadError):
            pagar_igv.__wrapped__(
                self.empresa, date(2026, 11, 1), Decimal("1"), self.origen, 2026, 10,
            )
        bloquear.assert_not_called()

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.models import Compra
from compras.reversion import revertir_registro
from compras.servicios import CompraError, pagar
from contabilidad.models import Asiento
from core.models import HistorialDocumento, Periodo
from inventario.models import CapaFIFO, ConsumoCapa, MovimientoStock

from .test_invariantes import BaseContable


class ReversionCompraTest(BaseContable):
    def setUp(self):
        self.compra = self.comprar("2", "50")

    def revertir(self):
        return revertir_registro(
            empresa=self.empresa, compra_id=self.compra.pk, motivo="Registro duplicado por error", usuario=None
        )

    def test_reversion_preserva_historia_y_compensa_contabilidad_y_stock(self):
        original = Asiento.objects.get(origen_tipo="COMPRA", origen_id=self.compra.pk)
        capa = CapaFIFO.objects.get(origen_tipo="COMPRA", origen_id=self.compra.pk)
        entrada = MovimientoStock.objects.get(origen_tipo="COMPRA", origen_id=self.compra.pk)
        self.revertir()
        self.compra.refresh_from_db()
        capa.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.ANULADA)
        self.assertEqual(capa.cantidad_restante, 0)
        self.assertTrue(MovimientoStock.objects.filter(pk=entrada.pk).exists())
        salida = MovimientoStock.objects.get(origen_tipo="REV_COMPRA", origen_id=self.compra.pk)
        self.assertEqual(salida.costo_total, entrada.costo_total)
        self.assertTrue(ConsumoCapa.objects.filter(capa=capa, movimiento=salida).exists())
        inverso = Asiento.objects.get(origen_tipo="REV_COMPRA", origen_id=self.compra.pk)
        original_lineas = {linea.cuenta_id: (linea.debe, linea.haber) for linea in original.lineas.all()}
        inverso_lineas = {linea.cuenta_id: (linea.haber, linea.debe) for linea in inverso.lineas.all()}
        self.assertEqual(original_lineas, inverso_lineas)
        self.assertTrue(
            HistorialDocumento.objects.filter(tipo="COMPRA", documento_id=self.compra.pk, accion="REVERSION").exists()
        )
        with self.assertRaises(CompraError):
            self.revertir()

    def test_bloquea_pago_o_salida_y_no_deja_reversion_parcial(self):
        pagar(self.compra, cuenta=self.bbva, fecha=date(2026, 11, 11), importe=Decimal("1"))
        with self.assertRaisesMessage(CompraError, "pagos"):
            self.revertir()
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.CONFIRMADA)
        self.assertFalse(Asiento.objects.filter(origen_tipo="REV_COMPRA").exists())
        self.assertFalse(MovimientoStock.objects.filter(origen_tipo="REV_COMPRA").exists())

    def test_bloquea_capas_consumidas(self):
        self.vender("1", "100", fecha=date(2026, 11, 20))
        with self.assertRaisesMessage(CompraError, "consumido"):
            self.revertir()
        self.assertFalse(Asiento.objects.filter(origen_tipo="REV_COMPRA").exists())

    def test_bloquea_periodo_posterior_cerrado(self):
        Periodo.objects.create(empresa=self.empresa, anio=2026, mes=12, estado=Periodo.Estado.CERRADO)
        with self.assertRaisesMessage(CompraError, "períodos cerrados"):
            self.revertir()
        self.assertFalse(Asiento.objects.filter(origen_tipo="REV_COMPRA").exists())

    def test_formulario_exige_confirmacion_explicita_y_deja_rastro_del_usuario(self):
        usuario = get_user_model().objects.create_superuser(username="revisor", password="test")
        self.client.force_login(usuario)
        url = reverse("compras:anular", args=[self.compra.pk])
        self.client.post(url, {"motivo": "Compra registrada por error"})
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.CONFIRMADA)
        self.client.post(url, {"motivo": "Compra registrada por error", "confirmo_error": "on"})
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.estado, Compra.Estado.ANULADA)
        self.assertTrue(
            HistorialDocumento.objects.filter(
                tipo="COMPRA", documento_id=self.compra.pk, accion="REVERSION", usuario=usuario
            ).exists()
        )

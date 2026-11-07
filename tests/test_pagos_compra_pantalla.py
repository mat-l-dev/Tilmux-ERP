from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.models import Compra
from core.models import Perfil
from tesoreria.models import MovimientoTesoreria
from tests.test_invariantes import BaseContable


class PagoCompraPantallaTest(BaseContable):
    def setUp(self):
        usuario = get_user_model().objects.create_user(username="pago_compra")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()
        self.compra = self.comprar("1", "100")
        self.url = reverse("compras:pagar", args=[self.compra.pk])

    def datos(self):
        formulario = self.client.get(self.url)
        return {"operacion": formulario.context["operacion"], "cuenta": self.bbva.pk,
                "fecha": "2026-11-11", "importe": "30", "canal": "TRANSFERENCIA"}

    def test_reenvio_no_duplica_pago_parcial_y_detalle_muestra_saldo(self):
        datos = self.datos()
        self.assertEqual(self.client.post(self.url, datos).status_code, 302)
        self.assertEqual(self.client.post(self.url, datos).status_code, 302)
        compra = Compra.objects.get(pk=self.compra.pk)
        self.assertEqual(compra.monto_pagado, Decimal("30"))
        self.assertEqual(MovimientoTesoreria.objects.filter(origen_tipo="COMPRA_PAGO", origen_id=compra.pk).count(), 1)
        detalle = self.client.get(reverse("compras:detalle", args=[compra.pk]))
        self.assertContains(detalle, "Pagos de la compra")
        self.assertContains(detalle, self.bbva.nombre)
        self.assertEqual(detalle.context["saldo_compra"], Decimal("88"))

    def test_sin_importe_o_identificador_no_se_registra_pago(self):
        datos = self.datos()
        datos["importe"] = ""
        self.assertContains(self.client.post(self.url, datos), "Indica el importe")
        datos["importe"] = "30"
        datos["operacion"] = ""
        self.assertContains(self.client.post(self.url, datos), "operación no es válida")
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="COMPRA_PAGO").exists())

"""Registro manual de gastos pagados con efecto contable."""

from django.contrib.auth import get_user_model
from django.urls import reverse

from catalogo.models import CuentaTesoreria
from compras.models_gasto import Gasto
from contabilidad.models import Asiento, Cuenta
from core.models import Empresa, HistorialDocumento
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class GastoManualTest(BaseContable):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="gastos")
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def datos(self):
        return {
            "fecha": "2026-11-10",
            "proveedor": self.proveedor.pk,
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "123",
            "base": "100.00",
            "igv": "18.00",
            "cuenta": Cuenta.objects.get(version="2026", codigo="6391").pk,
            "medio": self.bbva.pk,
            "glosa": "Comisión de prueba",
            "con_credito": "on",
        }

    def test_registro_genera_gasto_asiento_y_movimiento(self):
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), self.datos())
        gasto = Gasto.objects.get(empresa=self.empresa, serie="F001", numero="123")
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[gasto.pk]))
        self.assertTrue(Asiento.objects.filter(empresa=self.empresa, origen_tipo="GASTO", origen_id=gasto.pk).exists())
        self.assertTrue(
            MovimientoTesoreria.objects.filter(empresa=self.empresa, origen_tipo="GASTO", origen_id=gasto.pk).exists()
        )
        self.assertTrue(
            HistorialDocumento.objects.filter(
                empresa=self.empresa, tipo="GASTO", documento_id=gasto.pk, usuario=self.usuario, accion="REGISTRO"
            ).exists()
        )

    def test_no_registra_factura_sin_numero(self):
        datos = self.datos()
        datos["numero"] = ""
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, serie="F001").exists())

    def test_no_repite_un_comprobante(self):
        datos = self.datos()
        self.assertEqual(self.client.post(reverse("compras:nuevo_gasto"), datos).status_code, 302)
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), datos)
        self.assertContains(respuesta, "ya está registrado")
        self.assertEqual(Gasto.objects.filter(empresa=self.empresa, serie="F001").count(), 1)
        self.assertEqual(MovimientoTesoreria.objects.filter(empresa=self.empresa, origen_tipo="GASTO").count(), 1)

    def test_rechaza_medio_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra SAC", ruc="20123456780")
        cuenta = CuentaTesoreria.objects.create(
            empresa=otra, nombre="Otra caja", cuenta_contable=self.bbva.cuenta_contable
        )
        datos = self.datos()
        datos["medio"] = cuenta.pk
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, serie="F001").exists())

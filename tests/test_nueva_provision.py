from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.models_gasto import Gasto
from contabilidad.models import Asiento, Cuenta
from core.models import HistorialDocumento, Perfil, Periodo
from reportes.casillas import calcular
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class NuevaProvisionTest(BaseContable):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="provision")
        self.perfil = Perfil.objects.create(usuario=self.usuario, empresa=self.empresa)
        self.client.force_login(self.usuario)
        self.url = reverse("compras:nueva_provision")
        self.datos = {
            "fecha": "2026-11-10",
            "proveedor": self.proveedor.pk,
            "importe": "28.00",
            "cuenta": Cuenta.objects.get(version="2026", codigo="6391").pk,
            "glosa": "Comisión devengada",
            "confirmado": "on",
            "operacion": str(uuid4()),
        }

    def test_crea_asiento_sin_pago_ni_credito_y_evitar_repeticion(self):
        antes = calcular(self.empresa, 2026, 11)
        respuesta = self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertEqual(provision.fecha_devengado, date(2026, 11, 10))
        self.assertEqual(provision.total, Decimal("28"))
        self.assertFalse(provision.con_credito)
        self.assertFalse(provision.deducible)
        asiento = Asiento.objects.get(empresa=self.empresa, origen_tipo="GASTO", origen_id=provision.pk)
        lineas = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(lineas["6391"], (Decimal("28"), Decimal("0")))
        self.assertEqual(lineas["4212"], (Decimal("0"), Decimal("28")))
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="GASTO", origen_id=provision.pk).exists())
        self.assertTrue(
            HistorialDocumento.objects.filter(
                empresa=self.empresa, tipo="GASTO", documento_id=provision.pk, usuario=self.usuario, accion="PROVISION"
            ).exists()
        )
        detalle = self.client.get(reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertContains(detalle, "Gasto devengado registrado sin comprobante")
        self.assertNotContains(detalle, self.datos["operacion"])
        self.assertEqual(calcular(self.empresa, 2026, 11), antes)
        respuesta = self.client.post(self.url, self.datos)
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertEqual(Gasto.objects.filter(empresa=self.empresa, provision=True).count(), 1)
        self.assertEqual(
            Asiento.objects.filter(empresa=self.empresa, origen_tipo="GASTO", origen_id=provision.pk).count(), 1
        )

    def test_periodo_cerrado_o_falta_de_confirmacion_no_registran(self):
        periodo, _ = Periodo.objects.get_or_create(empresa=self.empresa, anio=2026, mes=11)
        periodo.estado = Periodo.Estado.CERRADO
        periodo.save(update_fields=["estado"])
        respuesta = self.client.post(self.url, self.datos)
        self.assertContains(respuesta, "cerrado")
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())
        periodo.estado = Periodo.Estado.ABIERTO
        periodo.save(update_fields=["estado"])
        datos = self.datos.copy()
        datos.pop("confirmado")
        self.assertEqual(self.client.post(self.url, datos).status_code, 200)
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())

    def test_liquida_la_provision_con_comprobante_sin_duplicar_el_gasto(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {
            "fecha": "2026-11-11",
            "proveedor": self.proveedor.pk,
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "19",
            "base": "28",
            "igv": "0",
            "cuenta": self.datos["cuenta"],
            "medio": self.bbva.pk,
            "glosa": "Comisión facturada",
            "provisiones": [provision.pk],
        }
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), datos)
        self.assertEqual(respuesta.status_code, 302)
        factura = Gasto.objects.get(empresa=self.empresa, serie="F001", numero="19")
        provision.refresh_from_db()
        self.assertEqual(provision.gasto_origen_id, factura.pk)
        lineas = Asiento.objects.filter(empresa=self.empresa, estado="CONFIRMADO").values_list(
            "lineas__cuenta__codigo", "lineas__debe", "lineas__haber"
        )
        gasto = sum((debe - haber for codigo, debe, haber in lineas if codigo == "6391"), Decimal("0"))
        self.assertEqual(gasto, Decimal("28"))
        self.assertTrue(MovimientoTesoreria.objects.filter(origen_tipo="GASTO", origen_id=factura.pk).exists())

    def test_usuario_lector_no_puede_registrar(self):
        self.perfil.rol = Perfil.Rol.LECTOR
        self.perfil.save(update_fields=["rol"])
        self.assertRedirects(self.client.post(self.url, self.datos), reverse("core:panel"))
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())

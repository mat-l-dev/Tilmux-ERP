from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, HistorialDocumento, Perfil
from tesoreria.models import MovimientoTesoreria


class Declaracion621Test(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.usuario = get_user_model().objects.create_user(username="declarador")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)

    def setUp(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()

    def datos(self, **cambios):
        datos = {
            "anio": "2026", "mes": "10", "tipo": "ORIGINAL", "numero_orden": "123456",
            "fecha_presentacion": date(2026, 11, 8).isoformat(),
            "casilla_140": "215", "casilla_145": "110", "casilla_184": "105",
        }
        datos.update(cambios)
        return datos

    def test_registro_y_rectificacion_conservan_historial_sin_crear_pago(self):
        from contabilidad.models import DeclaracionIGV621

        url = reverse("reportes:registrar_declaracion_igv")
        self.client.post(url, self.datos())
        self.client.post(url, self.datos(tipo="RECTIFICATORIA", numero_orden="123457", casilla_184="106",
                                        casilla_140="216"))
        versiones = DeclaracionIGV621.objects.filter(empresa=self.empresa).order_by("pk")
        self.assertEqual(versiones.count(), 2)
        self.assertEqual(versiones.first().casilla_184, Decimal("105"))
        self.assertEqual(versiones.last().casilla_184, Decimal("106"))
        self.assertEqual(HistorialDocumento.objects.filter(empresa=self.empresa, accion="REGISTRO_621").count(), 2)
        self.assertFalse(MovimientoTesoreria.objects.filter(empresa=self.empresa).exists())
        respuesta = self.client.get(reverse("reportes:impuestos"), {"periodo": "2026-10"})
        self.assertContains(respuesta, "123456")
        self.assertContains(respuesta, "123457")

    def test_no_acepta_casillas_incompatibles_ni_numero_repetido(self):
        from contabilidad.models import DeclaracionIGV621

        url = reverse("reportes:registrar_declaracion_igv")
        self.client.post(url, self.datos(casilla_184="106"))
        self.assertFalse(DeclaracionIGV621.objects.exists())
        self.client.post(url, self.datos())
        self.client.post(url, self.datos())
        self.assertEqual(DeclaracionIGV621.objects.count(), 1)

    def test_usuario_solo_lectura_no_registra_declaraciones(self):
        from contabilidad.models import DeclaracionIGV621

        Perfil.objects.filter(usuario=self.usuario).update(rol=Perfil.Rol.LECTOR)
        respuesta = self.client.post(reverse("reportes:registrar_declaracion_igv"), self.datos(), follow=True)
        self.assertContains(respuesta, "Tu usuario es de solo lectura.")
        self.assertFalse(DeclaracionIGV621.objects.exists())

    def test_saldo_favor_y_aislamiento_entre_empresas(self):
        from contabilidad.models import DeclaracionIGV621

        url = reverse("reportes:registrar_declaracion_igv")
        self.client.post(url, self.datos(casilla_140="-20", casilla_145="110", casilla_184="-130"))
        DeclaracionIGV621.objects.create(
            empresa=self.otra, anio=2026, mes=10, tipo="ORIGINAL", numero_orden="AJENO",
            fecha_presentacion=date(2026, 11, 8), casilla_140=0, casilla_145=0, casilla_184=0,
        )
        respuesta = self.client.get(reverse("reportes:impuestos"), {"periodo": "2026-10"})
        self.assertContains(respuesta, "123456")
        self.assertNotContains(respuesta, "AJENO")
        self.assertEqual(DeclaracionIGV621.objects.get(empresa=self.empresa).casilla_184, Decimal("-130"))
        ajena = DeclaracionIGV621.objects.get(empresa=self.otra)
        respuesta = self.client.post(reverse("reportes:anular_registro_621", args=[ajena.pk]), {"motivo": "Error"})
        self.assertEqual(respuesta.status_code, 404)
        ajena.refresh_from_db()
        self.assertFalse(ajena.anulada)

    def test_corregir_error_anula_solo_el_registro_interno_con_motivo(self):
        from contabilidad.models import DeclaracionIGV621

        self.client.post(reverse("reportes:registrar_declaracion_igv"), self.datos())
        registro = DeclaracionIGV621.objects.get()
        url = reverse("reportes:anular_registro_621", args=[registro.pk])
        self.client.post(url, {"motivo": ""})
        registro.refresh_from_db()
        self.assertFalse(registro.anulada)
        self.client.post(url, {"motivo": "Número digitado por error"})
        registro.refresh_from_db()
        self.assertTrue(registro.anulada)
        self.assertEqual(registro.motivo_anulacion, "Número digitado por error")
        self.client.post(reverse("reportes:registrar_declaracion_igv"), self.datos())
        self.assertEqual(DeclaracionIGV621.objects.count(), 2)
        self.assertTrue(HistorialDocumento.objects.filter(accion="ANULAR_REG_621").exists())

"""Aislamiento de perfiles asignados y de documentos de venta."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, Perfil
from ventas.models import Venta
from ventas.models_guia import GuiaRemision


class EmpresasPermisosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.usuario = get_user_model().objects.create_user(username="asignado")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa, rol=Perfil.Rol.REGISTRADOR)
        cls.admin = get_user_model().objects.create_superuser(username="admin_empresa", password="prueba")
        Perfil.objects.create(usuario=cls.admin, empresa=cls.empresa, rol=Perfil.Rol.ADMIN)
        cls.venta_ajena = Venta.objects.create(
            empresa=cls.otra, fecha=date(2026, 11, 6), serie="E001", numero="1",
            estado=Venta.Estado.BORRADOR,
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.otra.pk
        session.save()

    def test_sesion_manipulada_se_corrige_y_lista_solo_empresa_asignada(self):
        respuesta = self.client.get(reverse("core:panel"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["empresa_activa"], self.empresa)
        self.assertEqual([empresa.pk for empresa in respuesta.context["empresas"]], [self.empresa.pk])
        self.assertEqual(self.client.session["empresa_id"], self.empresa.pk)

    def test_no_puede_cambiar_a_otra_empresa_ni_redirigir_fuera(self):
        respuesta = self.client.post(reverse("core:cambiar_empresa"), {
            "empresa_id": self.otra.pk, "siguiente": "https://ejemplo.invalid/",
        })
        self.assertEqual(respuesta.url, reverse("core:panel"))
        respuesta = self.client.get(reverse("core:panel"))
        self.assertEqual(respuesta.context["empresa_activa"], self.empresa)

    def test_documentos_de_otra_empresa_no_se_ven_ni_modifican(self):
        for accion, metodo in [("detalle", "get"), ("confirmar", "post"), ("nota_credito", "get"),
                               ("nota_credito", "post"), ("nota_debito", "get"), ("nota_debito", "post")]:
            with self.subTest(accion=accion, metodo=metodo):
                respuesta = getattr(self.client, metodo)(reverse(f"ventas:{accion}", args=[self.venta_ajena.pk]))
                self.assertEqual(respuesta.status_code, 404)
        self.venta_ajena.refresh_from_db()
        self.assertEqual(self.venta_ajena.estado, Venta.Estado.BORRADOR)

    def test_guia_de_sesion_de_otra_empresa_no_se_guarda(self):
        session = self.client.session
        session["guia_pendiente"] = {"empresa_id": self.otra.pk}
        session.save()
        respuesta = self.client.post(reverse("compras:vincular_guia"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(GuiaRemision.objects.exists())

    def test_empresa_asignada_inactiva_no_da_acceso_a_otra(self):
        self.empresa.activa = False
        self.empresa.save(update_fields=["activa"])
        respuesta = self.client.get(reverse("core:panel"))
        self.assertIsNone(respuesta.context["empresa_activa"])
        self.assertEqual(respuesta.context["empresas"], [])

    def test_superusuario_con_perfil_puede_cambiar_de_empresa(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(reverse("core:cambiar_empresa"), {
            "empresa_id": self.otra.pk, "siguiente": reverse("core:panel"),
        })
        self.assertEqual(respuesta.url, reverse("core:panel"))
        self.assertEqual(self.client.session["empresa_id"], self.otra.pk)
        respuesta = self.client.get(reverse("core:panel"))
        self.assertEqual(respuesta.context["empresa_activa"], self.otra)

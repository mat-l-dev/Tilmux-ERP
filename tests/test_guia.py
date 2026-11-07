from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, Perfil


class GuiaTest(TestCase):
    def test_guia_requiere_sesion_y_muestra_los_recorridos(self):
        url = reverse("core:guia")
        self.assertEqual(self.client.get(url).status_code, 302)
        usuario = get_user_model().objects.create_user(username="lector_guia")
        empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa SAC", ruc="20123456789")
        Perfil.objects.create(usuario=usuario, empresa=empresa, rol=Perfil.Rol.LECTOR)
        self.client.force_login(usuario)
        respuesta = self.client.get(url)
        self.assertContains(respuesta, "¿Qué quieres hacer?")
        self.assertContains(respuesta, "Gastos por pagar")
        self.assertContains(respuesta, "no se distribuyen automáticamente entre sus cuotas")
        self.assertContains(respuesta, reverse("reportes:conciliacion"))
        self.assertContains(respuesta, reverse("core:guia"))

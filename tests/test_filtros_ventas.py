from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Empresa, Perfil
from ventas.models import Venta


class FiltrosVentaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        usuario = get_user_model().objects.create_user(username="venta")
        Perfil.objects.create(usuario=usuario, empresa=empresa)
        cls.usuario = usuario
        Venta.objects.create(empresa=empresa, fecha=date(2026, 10, 1), serie="F001", numero="123")

    def test_filtros_invalidos_no_producen_error_de_servidor_ni_resultados(self):
        self.client.force_login(self.usuario)
        url = reverse("ventas:lista")
        for filtros in (
            {"periodo": "2026-13"}, {"periodo": "2026-abc"}, {"periodo": "2026-1"},
            {"producto": "no-es-numero"}, {"producto": "9" * 40},
        ):
            respuesta = self.client.get(url, filtros)
            self.assertEqual(respuesta.status_code, 200)
            self.assertNotContains(respuesta, "F001-123")
            self.assertTrue(respuesta.context["errores_filtro"])
        self.assertContains(self.client.get(url, {"periodo": "2026-10"}), "F001-123")

    def test_lista_distingue_resultados_filtrados_y_muestra_condicion(self):
        self.client.force_login(self.usuario)
        url = reverse("ventas:lista")
        listado = self.client.get(url, {"periodo": "2026-10"})
        self.assertContains(listado, "Contado")
        self.assertContains(listado, "PEN")
        self.assertContains(listado, "Limpiar filtros")
        vacio = self.client.get(url, {"q": "cliente-inexistente"})
        self.assertContains(vacio, "No hay ventas para los filtros elegidos")
        self.assertNotContains(vacio, "F001-123")

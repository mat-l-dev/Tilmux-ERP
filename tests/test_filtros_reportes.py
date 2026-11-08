from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contabilidad.models import Asiento
from core.models import Empresa, HistorialDocumento, Perfil
from reportes.eeff import construir
from tesoreria.models import MovimientoTesoreria


class FiltrosReportesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.usuario = get_user_model().objects.create_user(username="reportes")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_rangos_invalidos_no_generan_reporte_ni_exportacion(self):
        rutas = (
            "balance", "mayor", "registro_ventas", "registro_compras", "impuestos", "eeff",
            "exportar_ventas", "exportar_compras", "exportar_eeff", "exportar_eeff_pdf",
        )
        for ruta in rutas:
            for datos in (
                {"periodo": "2026-13"},
                {"desde": "2026-10-20", "hasta": "2026-10-01"},
                {"desde": "no-es-fecha"},
                {"periodo": "2026-10", "desde": "2026-10-01"},
            ):
                with self.subTest(ruta=ruta, datos=datos):
                    respuesta = self.client.get(reverse(f"reportes:{ruta}"), datos)
                    self.assertEqual(respuesta.status_code, 400)
                    self.assertContains(respuesta, "Revisar fechas", status_code=400)

    def test_estados_financieros_usan_el_mes_seleccionado(self):
        with patch("reportes.eeff.construir", wraps=construir) as calcular:
            respuesta = self.client.get(reverse("reportes:eeff"), {"periodo": "2026-10"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(calcular.call_args_list[0].args, (self.empresa, date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(respuesta.context["desde"], date(2026, 10, 1))
        self.assertEqual(respuesta.context["hasta"], date(2026, 10, 31))
        self.assertContains(respuesta, "desde=2026-10-01&hasta=2026-10-31")

    def test_impuestos_no_presenta_un_mes_entero_como_si_fueran_dias_parciales(self):
        url = reverse("reportes:impuestos")
        respuesta = self.client.get(url, {"desde": "2026-10-10", "hasta": "2026-10-20"})
        self.assertContains(respuesta, "requiere un mes completo", status_code=400)
        respuesta = self.client.get(url, {"desde": "2026-10-01", "hasta": "2026-11-30"})
        self.assertContains(respuesta, "requiere un mes completo", status_code=400)
        respuesta = self.client.get(url, {"periodo": "2026-10"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["desde"], date(2026, 10, 1))
        self.assertEqual(respuesta.context["hasta"], date(2026, 10, 31))
        self.assertIsNone(respuesta.context["c303"])
        self.assertIsNone(respuesta.context["c304"])
        self.assertContains(respuesta, "No verificado")
        self.assertContains(respuesta, "No determinado")

    def test_compara_saldo_declarado_con_libro_sin_guardar_ni_cambiar_calculo(self):
        url = reverse("reportes:impuestos") + "?periodo=2026-10"
        antes = (Asiento.objects.count(), MovimientoTesoreria.objects.count(), HistorialDocumento.objects.count())
        with patch("reportes.views.saldo_cuenta", return_value=Decimal("-110.28")):
            respuesta = self.client.post(url, {"saldo_declarado": "110.00"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["comparacion_saldo"], {
            "declarado": Decimal("110.00"), "libro": Decimal("110.28"), "diferencia": Decimal("-0.28"),
        })
        self.assertEqual(respuesta.context["c145"], Decimal("110.28"))
        self.assertEqual(respuesta.context["c184"], Decimal("-110.28"))
        self.assertContains(respuesta, "Hay una diferencia por revisar")
        self.assertEqual(antes, (Asiento.objects.count(), MovimientoTesoreria.objects.count(),
                                 HistorialDocumento.objects.count()))

    def test_rechaza_saldo_invalido_y_admite_cero(self):
        url = reverse("reportes:impuestos") + "?periodo=2026-10"
        for valor in ("-110", "NaN", "1.001"):
            with self.subTest(valor=valor):
                respuesta = self.client.post(url, {"saldo_declarado": valor})
                self.assertIsNone(respuesta.context["comparacion_saldo"])
                self.assertTrue(respuesta.context["formulario_saldo"].errors)
        respuesta = self.client.post(url, {"saldo_declarado": "0"})
        self.assertEqual(respuesta.context["comparacion_saldo"]["declarado"], Decimal("0"))

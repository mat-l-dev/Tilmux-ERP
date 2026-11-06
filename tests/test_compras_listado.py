"""Compras y gastos disponibles desde el mismo módulo."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Producto, Tercero, UnidadMedida
from compras.models import Compra
from compras.models_gasto import Gasto
from compras.servicios import CompraError
from contabilidad.models import Cuenta
from core.models import Empresa


class ListadoComprasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa SAC", ruc="20123456789")
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra SAC", ruc="20123456780")
        proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cuenta = Cuenta.objects.create(codigo="6391", nombre="Comisiones", elemento=6, naturaleza="D")
        cls.compra = Compra.objects.create(
            empresa=cls.empresa, proveedor=proveedor, fecha=date(2026, 10, 1), serie="F001", numero="123"
        )
        cls.gasto = Gasto.objects.create(
            empresa=cls.empresa,
            proveedor=proveedor,
            cuenta=cuenta,
            fecha=date(2026, 10, 2),
            serie="F002",
            numero="456",
            glosa="Comisión de plataforma",
            total=Decimal("18"),
        )
        Gasto.objects.create(
            empresa=otra, proveedor=proveedor, cuenta=cuenta, fecha=date(2026, 10, 3), serie="F003", numero="789"
        )
        cls.usuario = get_user_model().objects.create_user(username="lista")

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_lista_compra_y_gasto_de_empresa_activa(self):
        respuesta = self.client.get(reverse("compras:lista"), {"periodo": "2026-10"})
        self.assertContains(respuesta, "F001-123")
        self.assertContains(respuesta, "F002-456")
        self.assertContains(respuesta, "Comisión de plataforma")
        self.assertNotContains(respuesta, "F003-789")
        self.assertContains(respuesta, reverse("compras:detalle_gasto", args=[self.gasto.pk]))

    def test_busca_concepto_y_filtra_por_tipo(self):
        respuesta = self.client.get(reverse("compras:lista"), {"q": "comisión", "tipo": "gasto"})
        self.assertContains(respuesta, "F002-456")
        self.assertNotContains(respuesta, "F001-123")

    def test_detalle_gasto_muestra_informacion_sin_acceso_a_otra_empresa(self):
        respuesta = self.client.get(reverse("compras:detalle_gasto", args=[self.gasto.pk]))
        self.assertContains(respuesta, "Comisión de plataforma")
        otro = Gasto.objects.exclude(empresa=self.empresa).get()
        self.assertEqual(self.client.get(reverse("compras:detalle_gasto", args=[otro.pk])).status_code, 404)

    def test_paginacion_combina_gastos_y_compras(self):
        Gasto.objects.bulk_create(
            [
                Gasto(
                    empresa=self.empresa,
                    proveedor=self.gasto.proveedor,
                    cuenta=self.gasto.cuenta,
                    fecha=date(2026, 10, 3),
                    glosa=f"Gasto {indice}",
                )
                for indice in range(25)
            ]
        )
        url = reverse("compras:lista")
        primera = self.client.get(url, {"periodo": "2026-10"})
        segunda = self.client.get(url, {"periodo": "2026-10", "page": 2})
        self.assertEqual(primera.context["page_obj"].paginator.count, 27)
        self.assertEqual(len(primera.context["compras"]), 25)
        self.assertContains(segunda, "F001-123")
        self.assertContains(segunda, "F002-456")

    def test_provision_muestra_vinculo_a_factura(self):
        provision = Gasto.objects.create(
            empresa=self.empresa,
            proveedor=self.gasto.proveedor,
            cuenta=self.gasto.cuenta,
            fecha=date(2026, 10, 1),
            provision=True,
            estado=Gasto.Estado.PROVISION,
            gasto_origen=self.gasto,
            glosa="Provisión de comisión",
        )
        respuesta = self.client.get(reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertContains(respuesta, "Esta provisión está vinculada")
        self.assertContains(respuesta, reverse("compras:detalle_gasto", args=[self.gasto.pk]))
        listado = self.client.get(reverse("compras:lista"), {"q": "Provisión de comisión"})
        self.assertContains(listado, "Provisión")

    def test_importacion_fallida_no_deja_compra_incompleta(self):
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        producto = Producto.objects.create(sku="TEST-XML", nombre="Producto", unidad=unidad)
        session = self.client.session
        session["xml_pendiente"] = {
            "tipo": "FACTURA", "serie": "F010", "numero": "123", "fecha": "2026-10-01", "moneda": "PEN",
            "emisor_ruc": "20100000099", "emisor_nombre": "Nuevo proveedor", "igv": "1.80",
            "base": "10.00", "total": "11.80", "lineas": [
                {"descripcion": "Producto", "cantidad": "1", "valor_unitario": "10", "base": "10"}
            ],
        }
        session.save()
        with patch("compras.views.confirmar", side_effect=CompraError("Ya registrado")):
            respuesta = self.client.post(reverse("compras:importar_compra"), {"producto": str(producto.pk)})
        self.assertContains(respuesta, "Ya registrado")
        self.assertFalse(Compra.objects.filter(serie="F010", numero="123").exists())
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000099").exists())
        self.assertIn("xml_pendiente", self.client.session)

    def test_admin_no_modifica_gastos_sin_contabilizar(self):
        self.usuario.is_staff = True
        self.usuario.is_superuser = True
        self.usuario.save(update_fields=["is_staff", "is_superuser"])
        cambio = reverse("admin:compras_gasto_change", args=[self.gasto.pk])
        alta = reverse("admin:compras_gasto_add")
        self.assertEqual(self.client.get(cambio).status_code, 200)
        self.assertEqual(self.client.post(cambio, {"total": "999"}).status_code, 403)
        self.assertEqual(self.client.post(alta, {}).status_code, 403)
        self.gasto.refresh_from_db()
        self.assertEqual(self.gasto.total, Decimal("18"))

    def test_admin_no_edita_compras_fuera_del_flujo_contable(self):
        self.usuario.is_staff = True
        self.usuario.is_superuser = True
        self.usuario.save(update_fields=["is_staff", "is_superuser"])
        cambio = reverse("admin:compras_compra_change", args=[self.compra.pk])
        self.assertEqual(self.client.get(cambio).status_code, 200)
        self.assertEqual(self.client.post(cambio, {"total": "999"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:compras_compra_add"), {}).status_code, 403)
        self.compra.refresh_from_db()
        self.assertEqual(self.compra.total, Decimal("0"))

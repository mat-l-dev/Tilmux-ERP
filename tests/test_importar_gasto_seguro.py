"""La importación no presume el pago ni derechos tributarios."""

from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria, Tercero
from compras.models_gasto import Gasto
from compras.servicios import CompraError
from contabilidad.models import Cuenta
from core.models import Empresa, Perfil
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class ImportarGastoSeguroTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20615841961")
        cls.usuario = get_user_model().objects.create_user(username="xml")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.cuenta = Cuenta.objects.create(
            codigo="6391", nombre="Comisiones", elemento=6, naturaleza="D", admite_movimiento=True, activa=True,
        )
        cls.banco = Cuenta.objects.create(codigo="1061", nombre="Banco", elemento=1, naturaleza="D")
        cls.medio = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco", cuenta_contable=cls.banco)

    def setUp(self):
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion["xml_pendiente"] = {
            "tipo": "FACTURA", "serie": "F001", "numero": "12", "fecha": "2026-10-01",
            "moneda": "PEN", "empresa_id": self.empresa.pk, "receptor_ruc": self.empresa.ruc,
            "emisor_ruc": "20100000001", "emisor_nombre": "Proveedor nuevo",
            "base": "100", "igv": "18", "total": "118", "lineas": [],
        }
        sesion.save()

    def datos(self):
        return {"cuenta": self.cuenta.pk, "medio": self.medio.pk, "canal": "TRANSFERENCIA", "pago_confirmado": "on"}

    def test_requiere_confirmacion_de_pago(self):
        datos = self.datos()
        datos.pop("pago_confirmado")
        with patch("compras.views.registrar_gasto") as registrar:
            respuesta = self.client.post(reverse("compras:importar_preview"), datos)
        self.assertEqual(respuesta.status_code, 200)
        registrar.assert_not_called()
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())

    def test_no_presume_credito_ni_deducibilidad_y_guarda_historia(self):
        with patch("compras.views.registrar_gasto") as registrar:
            registrar.return_value.pk = 4321
            respuesta = self.client.post(reverse("compras:importar_preview"), self.datos())
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(registrar.call_args.kwargs["con_credito"])
        self.assertFalse(registrar.call_args.kwargs["deducible"])
        self.assertTrue(self.empresa.historial.filter(documento_id=4321, accion="REGISTRO").exists())

    def test_rechaza_moneda_extranjera_y_cuentas_inadecuadas(self):
        sesion = self.client.session
        xml = sesion["xml_pendiente"]
        xml["moneda_original"] = "USD"
        sesion["xml_pendiente"] = xml
        sesion.save()
        with patch("compras.views.registrar_gasto") as registrar:
            respuesta = self.client.post(reverse("compras:importar_preview"), self.datos())
        self.assertContains(respuesta, "moneda extranjera")
        registrar.assert_not_called()
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())

    def test_error_contable_revierte_creacion_del_proveedor(self):
        with patch("compras.views.registrar_gasto", side_effect=CompraError("Error de prueba")):
            respuesta = self.client.post(reverse("compras:importar_preview"), self.datos())
        self.assertContains(respuesta, "Error de prueba")
        self.assertFalse(Tercero.objects.filter(numero_doc="20100000001").exists())
        self.assertFalse(Gasto.objects.exists())

    def test_rechaza_xml_de_otra_empresa(self):
        xml = (Path(__file__).parent / "fixtures" / "boleta_ml.xml").read_bytes()
        xml = xml.replace(b"20615841961", b"20123456789")
        respuesta = self.client.post(reverse("compras:importar"), {
            "archivo": SimpleUploadedFile("comprobante.xml", xml, content_type="application/xml"),
        })
        self.assertContains(respuesta, "receptor del XML")
        self.assertFalse(Gasto.objects.exists())

    def test_no_permite_reutilizar_xml_tras_cambiar_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", razon_social="Otra", ruc="20123456789")
        admin = get_user_model().objects.create_superuser(username="xml_admin", password="prueba")
        self.client.force_login(admin)
        sesion = self.client.session
        sesion["empresa_id"] = otra.pk
        sesion.save()
        respuesta = self.client.post(reverse("compras:importar_preview"), self.datos())
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Gasto.objects.exists())


class ImportarGastoContableTest(BaseContable):
    def test_factura_pagada_sin_credito_crea_gasto_y_movimiento(self):
        usuario = get_user_model().objects.create_user(username="xml_contable")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion["xml_pendiente"] = {
            "tipo": "FACTURA", "serie": "F002", "numero": "12", "fecha": "2026-11-10",
            "moneda": "PEN", "empresa_id": self.empresa.pk, "receptor_ruc": self.empresa.ruc,
            "emisor_ruc": self.proveedor.numero_doc, "emisor_nombre": self.proveedor.nombre,
            "base": "100", "igv": "18", "total": "118", "lineas": [],
        }
        sesion.save()
        respuesta = self.client.post(reverse("compras:importar_preview"), {
            "cuenta": Cuenta.objects.get(version="2026", codigo="6391").pk,
            "medio": self.bbva.pk, "canal": "YAPE", "pago_confirmado": "on",
        })
        self.assertEqual(respuesta.status_code, 302)
        gasto = Gasto.objects.get(empresa=self.empresa, serie="F002", numero="12")
        self.assertFalse(gasto.con_credito)
        self.assertTrue(
            MovimientoTesoreria.objects.filter(origen_tipo="GASTO", origen_id=gasto.pk, canal="YAPE").exists()
        )
        self.assertTrue(self.empresa.historial.filter(tipo="GASTO", documento_id=gasto.pk, usuario=usuario).exists())

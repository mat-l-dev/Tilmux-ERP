"""Cierre y reapertura mensual deben ser auditables y aislar empresas."""

from datetime import date
from decimal import Decimal
from threading import Event, Thread
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from contabilidad.models import Asiento, Cuenta
from contabilidad.servicios import ContabilidadError, postear_lineas
from core.models import Empresa, HistorialDocumento, Perfil, Periodo
from core.periodos import cerrar_mes


class PeriodosSeguridadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.admin = get_user_model().objects.create_superuser(username="admin_periodos", password="prueba")
        cls.usuario = get_user_model().objects.create_user(username="usuario_periodos")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.periodo = Periodo.objects.create(empresa=cls.empresa, anio=2026, mes=10)
        cls.ajeno = Periodo.objects.create(empresa=cls.otra, anio=2026, mes=10)

    def setUp(self):
        self.client.force_login(self.admin)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()

    def test_acciones_no_afectan_otras_empresas(self):
        for accion in ("cerrar_periodo", "revaluar_periodo", "reabrir_periodo"):
            with self.subTest(accion=accion):
                respuesta = self.client.post(reverse(f"core:{accion}", args=[self.ajeno.pk]), {"motivo": "Revisión"})
                self.assertEqual(respuesta.status_code, 404)
        self.ajeno.refresh_from_db()
        self.assertEqual(self.ajeno.estado, Periodo.Estado.ABIERTO)
        self.assertFalse(HistorialDocumento.objects.filter(empresa=self.otra).exists())

    def test_cierre_y_reapertura_se_guardan_con_usuario_y_motivo(self):
        respuesta = self.client.post(reverse("core:cerrar_periodo", args=[self.periodo.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.CERRADO)
        historial = HistorialDocumento.objects.get(tipo="PERIODO", documento_id=self.periodo.pk, accion="CIERRE")
        self.assertEqual(historial.usuario, self.admin)

        respuesta = self.client.post(reverse("core:reabrir_periodo", args=[self.periodo.pk]), {"motivo": " "})
        self.assertEqual(respuesta.status_code, 302)
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.CERRADO)
        self.client.post(reverse("core:reabrir_periodo", args=[self.periodo.pk]), {"motivo": "Corregir factura"})
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.ABIERTO)
        historial = HistorialDocumento.objects.get(tipo="PERIODO", documento_id=self.periodo.pk, accion="REAPERTURA")
        self.assertEqual(historial.usuario, self.admin)
        self.assertIn("Corregir factura", historial.detalle)
        respuesta = self.client.get(reverse("core:periodos"))
        self.assertContains(respuesta, "Corregir factura")

    def test_error_de_renta_no_cierra_ni_guarda_historia(self):
        with patch("core.periodos.asentar_renta", side_effect=ContabilidadError("No cuadra")):
            with self.assertRaises(ContabilidadError):
                cerrar_mes(empresa=self.empresa, pk=self.periodo.pk, usuario=self.admin)
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.ABIERTO)
        self.assertFalse(HistorialDocumento.objects.filter(tipo="PERIODO", documento_id=self.periodo.pk).exists())

    def test_no_reabre_si_existe_cierre_anual_activo(self):
        self.periodo.estado = Periodo.Estado.CERRADO
        self.periodo.save(update_fields=["estado"])
        Asiento.objects.create(
            empresa=self.empresa, periodo=self.periodo, numero=1, fecha=date(2026, 10, 31),
            tipo_operacion="CIERRE", glosa="Cierre", origen_tipo="CIERRE", origen_id=2026,
        )
        self.client.post(reverse("core:reabrir_periodo", args=[self.periodo.pk]), {"motivo": "Corregir"})
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.CERRADO)
        self.assertFalse(HistorialDocumento.objects.filter(tipo="PERIODO").exists())

    def test_no_admin_no_reabre_y_no_se_asienta_en_periodo_cerrado(self):
        self.periodo.estado = Periodo.Estado.CERRADO
        self.periodo.save(update_fields=["estado"])
        self.client.force_login(self.usuario)
        self.client.post(reverse("core:reabrir_periodo", args=[self.periodo.pk]), {"motivo": "Corregir"})
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.estado, Periodo.Estado.CERRADO)
        cuenta = Cuenta.objects.create(codigo="101", nombre="Caja", elemento=1, naturaleza="D")
        with self.assertRaisesMessage(ContabilidadError, "cerrado"):
            postear_lineas(
                empresa=self.empresa, fecha=date(2026, 10, 1), tipo="APORTE_CAPITAL", glosa="Prueba",
                lineas=[(cuenta, Decimal("1"), Decimal("1"), "")],
            )


@skipUnless(connection.vendor == "postgresql", "Requiere bloqueos de PostgreSQL")
class CierreConcurrenteTest(TransactionTestCase):
    def test_asiento_espera_cierre_y_no_entra_en_periodo_cerrado(self):
        empresa = Empresa.objects.create(nombre="Concurrencia", razon_social="Concurrencia", ruc="20123456781")
        periodo = Periodo.objects.create(empresa=empresa, anio=2026, mes=10)
        cuenta = Cuenta.objects.create(codigo="101", nombre="Caja", elemento=1, naturaleza="D")
        cerrado_pendiente, intento, liberar, terminado = Event(), Event(), Event(), Event()
        errores = []

        def cerrar_en_transaccion():
            close_old_connections()
            try:
                with transaction.atomic():
                    Empresa.objects.select_for_update().get(pk=empresa.pk)
                    Periodo.objects.filter(pk=periodo.pk).update(estado=Periodo.Estado.CERRADO)
                    cerrado_pendiente.set()
                    if not liberar.wait(15):
                        errores.append("No se liberó el cierre")
            except Exception as exc:
                errores.append(str(exc))
                cerrado_pendiente.set()
            finally:
                close_old_connections()

        def intentar_asiento():
            close_old_connections()
            try:
                if not cerrado_pendiente.wait(15):
                    errores.append("No empezó el cierre")
                    return
                intento.set()
                try:
                    postear_lineas(
                        empresa=empresa, fecha=date(2026, 10, 1), tipo="APORTE_CAPITAL", glosa="Prueba",
                        lineas=[(cuenta, Decimal("1"), Decimal("1"), "")],
                    )
                    errores.append("Se creó un asiento en período cerrado")
                except ContabilidadError as exc:
                    if "cerrado" not in str(exc):
                        errores.append(str(exc))
            except Exception as exc:
                errores.append(str(exc))
            finally:
                terminado.set()
                close_old_connections()

        cierre = Thread(target=cerrar_en_transaccion, daemon=True)
        asiento = Thread(target=intentar_asiento, daemon=True)
        cierre.start()
        asiento.start()
        try:
            self.assertTrue(intento.wait(20))
            self.assertFalse(terminado.wait(0.5), "El asiento no esperó a que terminara el cierre")
        finally:
            liberar.set()
            cierre.join(20)
            asiento.join(20)
        self.assertFalse(cierre.is_alive())
        self.assertFalse(asiento.is_alive())
        self.assertEqual(errores, [])
        self.assertFalse(Asiento.objects.filter(empresa=empresa).exists())

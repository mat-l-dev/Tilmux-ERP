"""Conciliación explícita, única por operación y reversible con historial."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria
from core.models import Empresa, Perfil
from tesoreria.conciliacion import ConciliacionError, confirmar
from tesoreria.models import ConciliacionBancaria, MovimientoTesoreria


class ConciliacionBancariaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Empresa", razon_social="Empresa", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="Otra", razon_social="Otra", ruc="20123456780")
        cls.usuario = get_user_model().objects.create_user(username="conciliador")
        Perfil.objects.create(usuario=cls.usuario, empresa=cls.empresa)
        cls.lector = get_user_model().objects.create_user(username="lector_conciliacion")
        Perfil.objects.create(usuario=cls.lector, empresa=cls.empresa, rol=Perfil.Rol.LECTOR)
        cls.cuenta = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco", moneda="PEN")
        cls.otra_cuenta = CuentaTesoreria.objects.create(empresa=cls.otra, nombre="Otro banco", moneda="PEN")
        cls.movimiento = MovimientoTesoreria.objects.create(
            empresa=cls.empresa, cuenta=cls.cuenta, fecha=date(2026, 11, 4),
            tipo="EGRESO", importe=Decimal("10"), concepto="Cargo de prueba",
        )
        cls.segundo = MovimientoTesoreria.objects.create(
            empresa=cls.empresa, cuenta=cls.cuenta, fecha=date(2026, 11, 4),
            tipo="EGRESO", importe=Decimal("10"), concepto="Otro cargo",
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def datos(self, **cambios):
        return {
            "cuenta": self.cuenta.pk, "fecha": "2026-11-04", "tipo": "EGRESO", "importe": "10.00",
            "movimiento_id": self.movimiento.pk, "referencia": " op  123 ", "confirmo": "on",
        } | cambios

    def test_confirma_una_vez_y_revierte_sin_borrar_historia_ni_crear_movimiento(self):
        antes = MovimientoTesoreria.objects.count()
        busqueda = self.client.post(reverse("tesoreria:comparar_banco"), {
            "cuenta": self.cuenta.pk, "fecha": "2026-11-04", "tipo": "EGRESO", "importe": "10.00",
        })
        self.assertContains(busqueda, 'name="importe" value="10.00"')
        respuesta = self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        self.assertRedirects(respuesta, reverse("tesoreria:historial_conciliaciones"))
        conciliacion = ConciliacionBancaria.objects.get()
        self.movimiento.refresh_from_db()
        self.assertTrue(self.movimiento.conciliado)
        self.assertEqual(conciliacion.referencia, "OP 123")
        self.assertEqual(conciliacion.creado_por, self.usuario)
        self.assertEqual(MovimientoTesoreria.objects.count(), antes)
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        self.assertEqual(ConciliacionBancaria.objects.count(), 1)
        self.client.post(reverse("tesoreria:revertir_conciliacion", args=[conciliacion.pk]), {"motivo": " "})
        conciliacion.refresh_from_db()
        self.assertTrue(conciliacion.activa)
        self.client.post(reverse("tesoreria:revertir_conciliacion", args=[conciliacion.pk]), {"motivo": "Error"})
        conciliacion.refresh_from_db()
        self.movimiento.refresh_from_db()
        self.assertFalse(conciliacion.activa)
        self.assertFalse(self.movimiento.conciliado)
        self.assertEqual(conciliacion.revertido_por, self.usuario)
        self.assertEqual(conciliacion.motivo_reversion, "Error")
        self.assertContains(self.client.get(reverse("tesoreria:historial_conciliaciones")), "Error")
        self.assertEqual(MovimientoTesoreria.objects.count(), antes)

    def test_referencia_no_puede_vincular_dos_movimientos(self):
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos(movimiento_id=self.segundo.pk))
        self.segundo.refresh_from_db()
        self.assertFalse(self.segundo.conciliado)
        self.assertEqual(ConciliacionBancaria.objects.count(), 1)

    def test_tras_reversion_se_puede_usar_referencia_y_conservar_anterior(self):
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        anterior = ConciliacionBancaria.objects.get()
        self.client.post(reverse("tesoreria:revertir_conciliacion", args=[anterior.pk]), {"motivo": "Revisado"})
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos(movimiento_id=self.segundo.pk))
        self.assertEqual(ConciliacionBancaria.objects.count(), 2)
        self.assertEqual(ConciliacionBancaria.objects.filter(activa=True).count(), 1)

    def test_datos_distintos_y_marca_anterior_no_se_concilian(self):
        for cambios in [
            {"importe": "11"}, {"fecha": "2026-11-09"}, {"tipo": "INGRESO"},
            {"cuenta": self.otra_cuenta.pk}, {"confirmo": ""}, {"referencia": " "},
        ]:
            with self.subTest(cambios=cambios):
                self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos(**cambios))
        self.movimiento.conciliado = True
        self.movimiento.save(update_fields=["conciliado"])
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        self.assertFalse(ConciliacionBancaria.objects.exists())

    def test_lector_no_puede_confirmar_ni_revertir(self):
        self.client.force_login(self.lector)
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        self.assertFalse(ConciliacionBancaria.objects.exists())
        self.client.force_login(self.usuario)
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        conciliacion = ConciliacionBancaria.objects.get()
        self.client.force_login(self.lector)
        self.client.post(reverse("tesoreria:revertir_conciliacion", args=[conciliacion.pk]), {"motivo": "Error"})
        conciliacion.refresh_from_db()
        self.assertTrue(conciliacion.activa)
        with self.assertRaisesMessage(ConciliacionError, "solo lectura"):
            confirmar(
                empresa=self.empresa, cuenta=self.cuenta, fecha=date(2026, 11, 4), tipo="EGRESO",
                importe=Decimal("10"), movimiento_id=self.segundo.pk, referencia="124", usuario=self.lector,
            )

    def test_servicio_rechaza_movimiento_de_otra_cuenta(self):
        with self.assertRaises(ConciliacionError):
            confirmar(
                empresa=self.otra, cuenta=self.otra_cuenta, fecha=date(2026, 11, 4), tipo="EGRESO",
                importe=Decimal("10"), movimiento_id=self.movimiento.pk, referencia="123", usuario=self.usuario,
            )

    def test_restriccion_en_base_impide_referencia_duplicada(self):
        self.client.post(reverse("tesoreria:confirmar_conciliacion"), self.datos())
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConciliacionBancaria.objects.create(
                empresa=self.empresa, cuenta=self.cuenta, movimiento=self.segundo,
                fecha_banco=date(2026, 11, 4), tipo="EGRESO", importe=10, referencia="OP 123",
            )

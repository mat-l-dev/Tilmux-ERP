from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from contabilidad.impuestos import igv_pendiente, monto_igv_pagado, pagar_igv
from contabilidad.models import DeclaracionIGV621, PagoIGV621
from contabilidad.servicios import ContabilidadError
from core.models import Empresa, HistorialDocumento, Perfil
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


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


class ConstanciaVigenteTest(BaseContable):
    """P0-5: la deuda y el pago salen de la constancia vigente, no del libro."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(
            username="constancia", password="test"
        )
        self.client.force_login(self.usuario)
        # Libros de octubre: ventas 1.196,62 / IGV 215,38 y crédito 110 -> 105,38.
        self.comprar("2", "305.555", fecha=date(2026, 10, 5))
        self.vender("1", "706", fecha=date(2026, 10, 29))
        self.vender("1", "706", fecha=date(2026, 10, 30))

    def datos(self, **cambios):
        datos = {
            "anio": "2026", "mes": "10", "tipo": "ORIGINAL", "numero_orden": "621-202610-1",
            "fecha_presentacion": "2026-11-10",
            "casilla_100": "1197", "casilla_101": "215", "casilla_107": "611",
            "casilla_108": "110", "casilla_120": "0",
            "casilla_140": "215", "casilla_145": "110", "casilla_184": "105",
            "casilla_301": "1197", "casilla_312": "18",
        }
        datos.update(cambios)
        return datos

    def registrar(self, **cambios):
        return self.client.post(reverse("reportes:registrar_declaracion_igv"), self.datos(**cambios))

    def test_registra_casillas_completas_y_redondeo_auditable(self):
        self.registrar()

        declaracion = DeclaracionIGV621.objects.get(empresa=self.empresa)
        self.assertTrue(declaracion.vigente)
        self.assertEqual(declaracion.casilla_100, Decimal("1197"))
        self.assertEqual(declaracion.casilla_101, Decimal("215"))
        self.assertEqual(declaracion.casilla_107, Decimal("611"))
        self.assertEqual(declaracion.casilla_108, Decimal("110"))
        self.assertEqual(declaracion.casilla_301, Decimal("1197"))
        self.assertEqual(declaracion.casilla_312, Decimal("18"))
        # 105 (constancia, enteros) - 105,38 (libros) = -0,38.
        self.assertEqual(declaracion.redondeo_deuda, Decimal("-0.38"))
        self.assertEqual(
            HistorialDocumento.objects.filter(
                empresa=self.empresa, accion="REGISTRO_621"
            ).count(),
            1,
        )

    def test_el_pendiente_y_el_pago_maximo_son_los_de_la_constancia(self):
        self.registrar()

        self.assertEqual(igv_pendiente(self.empresa, 2026, 10), Decimal("105"))

        with self.assertRaises(ContabilidadError):
            pagar_igv(
                self.empresa, date(2026, 11, 15), Decimal("106"), self.bbva, 2026, 10
            )

        pagar_igv(
            self.empresa, date(2026, 11, 15), Decimal("60"), self.bbva, 2026, 10
        )
        self.assertEqual(igv_pendiente(self.empresa, 2026, 10), Decimal("45"))
        pago = PagoIGV621.objects.get(empresa=self.empresa)
        self.assertEqual(pago.declaracion, DeclaracionIGV621.objects.get(empresa=self.empresa))
        self.assertEqual(pago.importe, Decimal("60"))

        pagar_igv(
            self.empresa, date(2026, 11, 16), Decimal("45"), self.bbva, 2026, 10
        )
        self.assertEqual(igv_pendiente(self.empresa, 2026, 10), Decimal("0"))
        self.assertEqual(monto_igv_pagado(self.empresa, 2026, 10), Decimal("105"))
        self.assertEqual(PagoIGV621.objects.count(), 2)

    def test_sin_constancia_vigente_no_se_paga(self):
        with self.assertRaisesMessage(ContabilidadError, "constancia vigente"):
            pagar_igv(
                self.empresa, date(2026, 11, 15), Decimal("10"), self.bbva, 2026, 10
            )
        self.assertFalse(PagoIGV621.objects.exists())
        self.assertFalse(
            MovimientoTesoreria.objects.filter(origen_tipo="PAGO_IGV").exists()
        )

    def test_rectificatoria_reemplaza_y_recalcula_el_pendiente(self):
        self.registrar()
        pagar_igv(
            self.empresa, date(2026, 11, 15), Decimal("60"), self.bbva, 2026, 10
        )

        self.registrar(
            tipo="RECTIFICATORIA", numero_orden="621-202610-2", casilla_184="100",
            casilla_140="210",
        )

        original, rectificatoria = list(
            DeclaracionIGV621.objects.filter(empresa=self.empresa).order_by("pk")
        )
        self.assertFalse(original.vigente)
        self.assertTrue(rectificatoria.vigente)
        self.assertEqual(igv_pendiente(self.empresa, 2026, 10), Decimal("40"))
        self.assertEqual(monto_igv_pagado(self.empresa, 2026, 10), Decimal("60"))
        self.assertEqual(
            DeclaracionIGV621.objects.filter(
                empresa=self.empresa, vigente=True, anulada=False
            ).count(),
            1,
        )

    def test_anular_la_vigente_bloquea_el_pago(self):
        self.registrar()
        declaracion = DeclaracionIGV621.objects.get(empresa=self.empresa)
        self.client.post(
            reverse("reportes:anular_registro_621", args=[declaracion.pk]),
            {"motivo": "Número de orden equivocado"},
        )
        declaracion.refresh_from_db()
        self.assertTrue(declaracion.anulada)
        self.assertFalse(declaracion.vigente)

        with self.assertRaisesMessage(ContabilidadError, "constancia vigente"):
            pagar_igv(
                self.empresa, date(2026, 11, 15), Decimal("10"), self.bbva, 2026, 10
            )

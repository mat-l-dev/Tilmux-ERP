from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from contabilidad.models import Asiento
from core.models import Perfil
from tesoreria.models import MovimientoTesoreria, RestitucionSocio
from tesoreria.restituciones import (
    RestitucionError,
    obligaciones,
    registrar_restitucion,
    saldo_obligacion,
)
from tesoreria.servicios import registrar

from .test_invariantes import BaseContable, importes_por_cuenta


class RestitucionSocioTest(BaseContable):
    """Pago de 4411/4419 con voucher obligatorio, sin tocar 4212 ni gasto."""

    def setUp(self):
        registrar(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=date(2026, 9, 18),
            tipo="INGRESO",
            importe=Decimal("500.00"),
            concepto="Préstamo del socio para abrir la cuenta BCP",
            tipo_regla="PRESTAMO_SOCIO",
        )
        registrar(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=date(2026, 10, 3),
            tipo="INGRESO",
            importe=Decimal("39.00"),
            concepto="Token BCP pagado por el socio",
            tipo_regla="REEMBOLSO_SOCIO",
        )

    def pagar(self, **extra):
        datos = {
            "empresa": self.empresa,
            "tipo": RestitucionSocio.Tipo.PRESTAMO_SOCIO,
            "cuenta": self.bbva,
            "fecha_hora": datetime(2026, 11, 9, 15, 30),
            "numero_operacion": "6675",
            "cuenta_destino": "00110455010001234567",
            "beneficiario": "Socio accionista",
            "importe": Decimal("500.00"),
            "concepto": "Restitución del préstamo de setiembre",
        }
        datos.update(extra)
        return registrar_restitucion(**datos)

    def test_sin_voucher_no_marca_pagado(self):
        with self.assertRaisesMessage(RestitucionError, "número de operación"):
            self.pagar(numero_operacion="   ")
        with self.assertRaisesMessage(RestitucionError, "cuenta de destino"):
            self.pagar(cuenta_destino="")
        with self.assertRaisesMessage(RestitucionError, "concepto"):
            self.pagar(concepto="")

        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("500.00"))
        self.assertFalse(RestitucionSocio.objects.exists())
        self.assertFalse(Asiento.objects.filter(tipo_operacion="RESTITUCION_SOCIO").exists())
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="RESTITUCION_SOCIO").exists())

    def test_paga_el_prestamo_4411_con_voucher_sin_tocar_4212_ni_gasto(self):
        restitucion = self.pagar()

        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("0.00"))
        asiento = Asiento.objects.get(tipo_operacion="RESTITUCION_SOCIO", origen_id=restitucion.pk)
        importes = importes_por_cuenta(asiento)
        self.assertEqual(importes["4411"], (Decimal("500.00"), Decimal("0.00")))
        self.assertEqual(importes["1061"], (Decimal("0.00"), Decimal("500.00")))
        self.assertNotIn("4212", importes)
        self.assertFalse([codigo for codigo in importes if codigo.startswith("6")])

        movimiento = MovimientoTesoreria.objects.get(origen_tipo="RESTITUCION_SOCIO", origen_id=restitucion.pk)
        self.assertEqual(movimiento.tipo, MovimientoTesoreria.Tipo.EGRESO)
        self.assertEqual(movimiento.importe, Decimal("500.00"))
        self.assertEqual(movimiento.cuenta_id, self.bbva.pk)
        self.assertEqual(restitucion.numero_operacion, "6675")
        self.assertEqual(restitucion.asiento_id, asiento.pk)
        self.assertTrue(restitucion.cuenta_destino_visible.endswith("4567"))

    def test_paga_el_reembolso_4419_del_token(self):
        restitucion = self.pagar(
            tipo=RestitucionSocio.Tipo.REEMBOLSO_SOCIO,
            importe=Decimal("39.00"),
            numero_operacion="0416457",
            beneficiario="Padre del gerente (socio)",
            concepto="Reembolso del token físico BCP",
        )

        self.assertEqual(saldo_obligacion(self.empresa, "REEMBOLSO_SOCIO"), Decimal("0.00"))
        asiento = restitucion.asiento
        importes = importes_por_cuenta(asiento)
        self.assertEqual(importes["4419"], (Decimal("39.00"), Decimal("0.00")))
        self.assertEqual(importes["1061"], (Decimal("0.00"), Decimal("39.00")))
        self.assertNotIn("4212", importes)
        self.assertFalse([codigo for codigo in importes if codigo.startswith("6")])

    def test_no_permite_restituir_mas_que_el_saldo(self):
        with self.assertRaisesMessage(RestitucionError, "saldo pendiente"):
            self.pagar(importe=Decimal("600.00"))
        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("500.00"))
        self.assertFalse(RestitucionSocio.objects.exists())

    def test_no_permite_sin_saldo_en_la_cuenta(self):
        with self.assertRaisesMessage(RestitucionError, "no tiene saldo pendiente"):
            self.pagar(tipo=RestitucionSocio.Tipo.REEMBOLSO_TERCERO, importe=Decimal("10.00"))

    def test_no_permite_repetir_la_operacion_del_voucher(self):
        self.pagar(importe=Decimal("100.00"))
        with self.assertRaisesMessage(RestitucionError, "ya está registrada"):
            self.pagar(importe=Decimal("100.00"))

    def test_pago_parcial_deja_la_obligacion_pendiente(self):
        self.pagar(importe=Decimal("200.00"))

        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("300.00"))
        pendientes = {fila["tipo"]: fila for fila in obligaciones(self.empresa)}
        self.assertEqual(pendientes["PRESTAMO_SOCIO"]["estado"], "PENDIENTE")
        self.assertEqual(pendientes["PRESTAMO_SOCIO"]["saldo"], Decimal("300.00"))
        # El reembolso de S/ 39 sigue pendiente: no se pagó nada de esa cuenta.
        self.assertEqual(pendientes["REEMBOLSO_SOCIO"]["estado"], "PENDIENTE")
        self.assertEqual(pendientes["REEMBOLSO_SOCIO"]["saldo"], Decimal("39.00"))

    def test_la_pantalla_muestra_pendiente_y_paga_con_voucher(self):
        usuario = get_user_model().objects.create_superuser(username="socios", password="test")
        self.client.force_login(usuario)

        lista = self.client.get(reverse("tesoreria:obligaciones_socios"))
        self.assertEqual(lista.status_code, 200)
        self.assertContains(lista, "PENDIENTE")
        self.assertContains(lista, "4411")

        respuesta = self.client.post(
            reverse("tesoreria:restitucion_socio"),
            {
                "tipo": RestitucionSocio.Tipo.PRESTAMO_SOCIO,
                "fecha_hora": "2026-11-09T15:30",
                "cuenta": self.bbva.pk,
                "beneficiario": "Socio accionista",
                "numero_operacion": "6675",
                "cuenta_destino": "00110455010001234567",
                "importe": "500.00",
                "concepto": "Restitución del préstamo de setiembre",
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("0.00"))
        self.assertTrue(RestitucionSocio.objects.filter(numero_operacion="6675").exists())

    def test_el_formulario_sin_voucher_no_registra(self):
        usuario = get_user_model().objects.create_superuser(username="socios2", password="test")
        self.client.force_login(usuario)

        respuesta = self.client.post(
            reverse("tesoreria:restitucion_socio"),
            {
                "tipo": RestitucionSocio.Tipo.PRESTAMO_SOCIO,
                "fecha_hora": "2026-11-09T15:30",
                "cuenta": self.bbva.pk,
                "beneficiario": "Socio accionista",
                "numero_operacion": "",
                "cuenta_destino": "",
                "importe": "500.00",
                "concepto": "",
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(RestitucionSocio.objects.exists())
        self.assertEqual(saldo_obligacion(self.empresa, "PRESTAMO_SOCIO"), Decimal("500.00"))

    def test_lector_no_puede_registrar_la_restitucion(self):
        lector = get_user_model().objects.create_user(username="lector", password="test")
        Perfil.objects.create(usuario=lector, empresa=self.empresa, rol=Perfil.Rol.LECTOR)
        self.client.force_login(lector)

        respuesta = self.client.post(reverse("tesoreria:restitucion_socio"), {})
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(RestitucionSocio.objects.exists())

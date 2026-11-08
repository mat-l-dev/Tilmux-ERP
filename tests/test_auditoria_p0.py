"""Pruebas de las correcciones P0 de la auditoría."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from catalogo.models import Serie, Tercero
from compras.models_gasto import Gasto
from compras.servicios import registrar_gasto
from contabilidad.impuestos import (
    igv_pendiente,
    monto_igv_pagado,
    pagar_igv,
)
from contabilidad.models import Asiento, Cuenta
from contabilidad.servicios import (
    ContabilidadError,
    anular_asiento,
    postear_lineas,
)
from core.contexto import usuario_actual
from core.models import HistorialDocumento, Perfil, Periodo
from reportes.casillas import calcular
from reportes.eeff import construir
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class CorreccionAsientos(BaseContable):
    def test_anular_asiento_conserva_lineas_y_deja_historial(self) -> None:
        compra = self.comprar("1", "100")
        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        lineas_antes = asiento.lineas.count()

        anular_asiento(asiento, "Prueba de anulación", usuario=usuario_actual.get())

        asiento.refresh_from_db()
        self.assertEqual(asiento.estado, Asiento.Estado.ANULADO)
        self.assertEqual(asiento.lineas.count(), lineas_antes)
        historial = HistorialDocumento.objects.get(
            tipo=HistorialDocumento.Tipo.ASIENTO,
            documento_id=asiento.pk,
            accion="ANULACION",
        )
        self.assertIn("Prueba de anulación", historial.detalle)

    def test_anular_asiento_es_idempotente(self) -> None:
        compra = self.comprar("1", "100")
        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)

        anular_asiento(asiento, "Primera anulación")
        anular_asiento(asiento, "Segunda anulación")

        self.assertEqual(
            HistorialDocumento.objects.filter(
                tipo=HistorialDocumento.Tipo.ASIENTO,
                documento_id=asiento.pk,
                accion="ANULACION",
            ).count(),
            1,
        )

    def test_anular_asiento_rechaza_periodo_cerrado(self) -> None:
        compra = self.comprar("1", "100", fecha=date(2026, 11, 10))
        asiento = Asiento.objects.get(origen_tipo="COMPRA", origen_id=compra.pk)
        Periodo.objects.filter(
            empresa=self.empresa, anio=2026, mes=11
        ).update(estado=Periodo.Estado.CERRADO)

        with self.assertRaises(ContabilidadError):
            anular_asiento(asiento, "No debe permitirse")


class Provisiones(BaseContable):
    def test_facturas_con_igual_numero_de_distintos_proveedores(self) -> None:
        otro = Tercero.objects.create(
            rol="PROVEEDOR", tipo_doc="RUC", numero_doc="20100000002", nombre="Otro proveedor"
        )
        datos = {
            "empresa": self.empresa,
            "fecha": date(2026, 10, 5),
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "123",
            "cuenta": Cuenta.objects.get(version="2026", codigo="6391"),
        }
        Gasto.objects.create(proveedor=self.proveedor, **datos)
        Gasto.objects.create(proveedor=otro, **datos)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gasto.objects.create(proveedor=self.proveedor, **datos)

    def test_gasto_anulado_no_aparece_en_casilla_120(self) -> None:
        Gasto.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 5),
            tipo_doc="FACTURA",
            serie="F001",
            numero="ANULADA",
            base=Decimal("18.00"),
            total=Decimal("18.00"),
            cuenta=Cuenta.objects.get(version="2026", codigo="6391"),
            estado=Gasto.Estado.ANULADO,
        )
        self.assertEqual(calcular(self.empresa, 2026, 10)["no_gravado"], Decimal("0"))

    def test_la_provision_no_mueve_tesoreria_y_se_excluye_del_621(self) -> None:
        provision = registrar_gasto(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 11, 10),
            fecha_devengado=date(2026, 11, 10),
            tipo_doc="FACTURA",
            serie="F001",
            numero="PROV-1",
            base=Decimal("50.00"),
            igv=Decimal("0.00"),
            total=Decimal("50.00"),
            cuenta=Cuenta.objects.get(version="2026", codigo="6391"),
            medio=None,
            glosa="Provisión de prueba",
            provision=True,
            estado=Gasto.Estado.PROVISION,
        )

        self.assertTrue(provision.provision)
        self.assertEqual(provision.estado, Gasto.Estado.PROVISION)
        self.assertFalse(
            MovimientoTesoreria.objects.filter(
                empresa=self.empresa,
                origen_tipo="GASTO",
                origen_id=provision.pk,
            ).exists()
        )
        asiento = Asiento.objects.get(
            origen_tipo="GASTO",
            origen_id=provision.pk,
            tipo_operacion="PROVISION_GASTO",
        )
        self.assertEqual(
            asiento.lineas.get(cuenta__codigo="4211").haber,
            Decimal("50.00"),
        )
        self.assertEqual(calcular(self.empresa, 2026, 11)["no_gravado"], Decimal("0"))

    def test_estimacion_621_no_adelanta_factura_a_fecha_de_devengo(self) -> None:
        registrar_gasto(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 5),
            fecha_devengado=date(2026, 9, 30),
            tipo_doc="FACTURA",
            serie="FV20",
            numero="01490476",
            base=Decimal("18.00"),
            igv=Decimal("0.00"),
            total=Decimal("18.00"),
            cuenta=Cuenta.objects.get(version="2026", codigo="6391"),
            medio=self.bbva,
            glosa="Mantenimiento BCP setiembre",
        )

        self.assertEqual(
            calcular(self.empresa, 2026, 9)["no_gravado"], Decimal("0")
        )
        self.assertEqual(calcular(self.empresa, 2026, 10)["no_gravado"], Decimal("18.00"))


class NumeracionSeries(BaseContable):
    def test_el_correlativo_avanza_al_confirmar_la_venta(self) -> None:
        self.comprar("10", "100")
        primera = self.vender("1", "250")
        serie = Serie.objects.get(
            empresa=self.empresa, tipo=Serie.Tipo.FACTURA, serie="E001"
        )
        self.assertEqual(serie.ultimo_numero, int(primera.numero))

        segunda = self.vender("1", "250")
        serie.refresh_from_db()
        self.assertEqual(serie.ultimo_numero, int(segunda.numero))
        self.assertGreater(serie.ultimo_numero, int(primera.numero))


class PagoIGV(BaseContable):
    def test_paga_periodo_cerrado_en_mes_posterior_abierto(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        Periodo.objects.filter(empresa=self.empresa, anio=2026, mes=11).update(
            estado=Periodo.Estado.CERRADO
        )
        movimiento = pagar_igv(
            self.empresa, date(2026, 12, 10), Decimal("10.00"), self.bbva, 2026, 11
        )
        self.assertEqual(movimiento.fecha, date(2026, 12, 10))
        self.assertEqual(monto_igv_pagado(self.empresa, 2026, 11), Decimal("10.00"))
        self.assertEqual(
            Periodo.objects.get(empresa=self.empresa, anio=2026, mes=11).estado,
            Periodo.Estado.CERRADO,
        )

    def test_pantalla_permite_elegir_fecha_de_pago_para_periodo_cerrado(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        Periodo.objects.filter(empresa=self.empresa, anio=2026, mes=11).update(
            estado=Periodo.Estado.CERRADO
        )
        usuario = get_user_model().objects.create_user(username="pago_cerrado")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("reportes:impuestos"), {"periodo": "2026-11"})
        self.assertContains(respuesta, "Registrar pago de IGV")

    def test_pago_parcial_de_igv(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        pendiente = igv_pendiente(self.empresa, 2026, 11)
        self.assertGreater(pendiente, Decimal("0"))

        pagar_igv(
            self.empresa,
            date(2026, 11, 25),
            Decimal("10.00"),
            self.bbva,
            2026,
            11,
            usuario=usuario_actual.get(),
        )

        self.assertEqual(
            monto_igv_pagado(self.empresa, 2026, 11), Decimal("10.00")
        )
        self.assertEqual(
            igv_pendiente(self.empresa, 2026, 11), pendiente - Decimal("10.00")
        )
        self.assertTrue(
            MovimientoTesoreria.objects.filter(
                empresa=self.empresa,
                origen_tipo="PAGO_IGV",
                origen_id=202611,
            ).exists()
        )
        self.assertTrue(
            Asiento.objects.filter(
                empresa=self.empresa,
                tipo_operacion="IGV_MENSUAL",
                origen_id=202611,
                estado=Asiento.Estado.CONFIRMADO,
            ).exists()
        )
        self.assertTrue(
            HistorialDocumento.objects.filter(
                empresa=self.empresa,
                tipo=HistorialDocumento.Tipo.IMPUESTO,
                documento_id=202611,
                accion="PAGO",
            ).exists()
        )

    def test_rechaza_sobrepago(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        pendiente = igv_pendiente(self.empresa, 2026, 11)

        with self.assertRaises(ContabilidadError):
            pagar_igv(
                self.empresa,
                date(2026, 11, 25),
                pendiente + Decimal("0.01"),
                self.bbva,
                2026,
                11,
            )

    def test_rechaza_periodo_cerrado(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        Periodo.objects.filter(
            empresa=self.empresa, anio=2026, mes=11
        ).update(estado=Periodo.Estado.CERRADO)

        with self.assertRaises(ContabilidadError):
            pagar_igv(
                self.empresa,
                date(2026, 11, 25),
                Decimal("10.00"),
                self.bbva,
                2026,
                11,
            )

    def test_la_pantalla_de_impuestos_ofrece_el_pago(self) -> None:
        self.comprar("10", "100")
        self.vender("10", "250")
        usuario = get_user_model().objects.create_user(
            username="probador", password="secreto"
        )
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)

        respuesta = self.client.get(
            reverse("reportes:impuestos"), {"periodo": "2026-11"}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Registrar pago de IGV")
        self.assertContains(respuesta, reverse("reportes:pagar_igv"))
        self.assertContains(respuesta, "no paga ni declara ante SUNAT")
        self.assertContains(respuesta, "Pendiente estimado según el libro")
        self.assertContains(respuesta, '<input type="number" name="importe" step="0.01" min="0.01" required>',
                            html=True)


class PresentacionEEFF(TestCase):
    """Un saldo deudor de 4212 no debe presentarse como activo."""

    @classmethod
    def setUpTestData(cls) -> None:
        from django.core.management import call_command

        call_command("cargar_pcge", verbosity=0)
        call_command("sembrar_tilmux", verbosity=0)
        call_command("sembrar_base", verbosity=0)
        call_command("sembrar_reglas", verbosity=0)
        from core.models import Empresa

        cls.empresa = Empresa.objects.get(ruc="20615841961")

    def test_saldo_deudor_de_4212_reduce_el_pasivo(self) -> None:
        cuentas = {
            c.codigo: c
            for c in Cuenta.objects.filter(version="2026", codigo__in=["4212", "1061"])
        }
        postear_lineas(
            empresa=self.empresa,
            fecha=date(2026, 11, 15),
            tipo="PAGO_PROVEEDOR",
            glosa="Prueba de saldo deudor 4212",
            lineas=[
                (cuentas["4212"], Decimal("10.00"), Decimal("0.00"), "Deudor"),
                (cuentas["1061"], Decimal("0.00"), Decimal("10.00"), "Banco"),
            ],
            origen_tipo="PRUEBA",
            origen_id=1,
        )

        eeff = construir(self.empresa, date(2026, 1, 1), date(2026, 11, 30))

        self.assertFalse(
            any(item["codigo"] == "4212" for item in eeff["activo_corriente"])
        )
        self.assertTrue(
            any(item["codigo"] == "4212" for item in eeff["pasivo"])
        )

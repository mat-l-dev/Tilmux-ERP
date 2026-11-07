from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.gastos_pendientes import pagar_gasto, registrar_pendiente
from compras.models_gasto import Gasto, PagoGasto
from compras.servicios import CompraError
from contabilidad.models import Asiento, Cuenta
from core.models import Perfil, Periodo
from tesoreria.models import MovimientoTesoreria
from tests.test_invariantes import BaseContable


class GastosPendientesTests(BaseContable):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.usuario = get_user_model().objects.create_user(username="gastos")
        cls.cuenta_gasto = Cuenta.objects.filter(
            version="2026", elemento=6, activa=True, admite_movimiento=True
        ).first()

    def crear(self):
        return registrar_pendiente(
            empresa=self.empresa, proveedor=self.proveedor, fecha=date(2026, 11, 10),
            tipo_doc="FACTURA", serie="F001", numero="12345", base=Decimal("100"),
            igv=Decimal("18"), cuenta=self.cuenta_gasto, glosa="Servicio", con_credito=True,
            deducible=True, usuario=self.usuario,
        )

    def pagar(self, gasto, importe, operacion=None, fecha=date(2026, 11, 11)):
        return pagar_gasto(empresa=self.empresa, gasto_id=gasto.pk, fecha=fecha, importe=Decimal(importe),
                           cuenta=self.bbva, operacion=operacion or uuid4(), usuario=self.usuario)

    def test_deuda_y_pagos_parciales_no_duplican_gasto(self):
        gasto = self.crear()
        self.assertEqual(gasto.estado, Gasto.Estado.REGISTRADO)
        self.assertEqual(MovimientoTesoreria.objects.count(), 0)
        asiento = Asiento.objects.get(origen_tipo="GASTO_PENDIENTE", origen_id=gasto.pk)
        self.assertEqual(sum(x.debe for x in asiento.lineas.all()), Decimal("118"))
        self.assertEqual(sum(x.haber for x in asiento.lineas.all()), Decimal("118"))
        token = uuid4()
        pago, creado = self.pagar(gasto, "50", token)
        self.assertTrue(creado)
        self.assertEqual(self.pagar(gasto, "50", token), (pago, False))
        with self.assertRaises(CompraError):
            self.pagar(gasto, "68.01")
        self.pagar(gasto, "68")
        gasto.refresh_from_db()
        self.assertEqual(gasto.estado, Gasto.Estado.PAGADO)
        self.assertEqual(PagoGasto.objects.count(), 2)
        self.assertEqual(MovimientoTesoreria.objects.filter(origen_tipo="PAGO_GASTO").count(), 2)
        self.assertEqual(Asiento.objects.filter(origen_tipo="PAGO_GASTO").count(), 2)
        with self.assertRaises(CompraError):
            self.pagar(gasto, "1")

    def test_no_permite_duplicados_ni_pagos_a_gastos_antiguos(self):
        gasto = self.crear()
        with self.assertRaises(CompraError):
            self.crear()
        Asiento.objects.filter(origen_tipo="GASTO_PENDIENTE", origen_id=gasto.pk).update(origen_tipo="GASTO")
        with self.assertRaises(CompraError):
            self.pagar(gasto, "1")
        self.assertFalse(PagoGasto.objects.exists())

    def test_periodo_cerrado_revierte_pago(self):
        gasto = self.crear()
        Periodo.objects.filter(empresa=self.empresa, anio=2026, mes=11).update(estado=Periodo.Estado.CERRADO)
        from contabilidad.servicios import ContabilidadError
        with self.assertRaises(ContabilidadError):
            self.pagar(gasto, "10")
        self.assertFalse(PagoGasto.objects.exists())
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="PAGO_GASTO").exists())

    def test_pantallas_muestran_saldo_y_ultimo_pago(self):
        Perfil.objects.create(usuario=self.usuario, empresa=self.empresa)
        self.client.force_login(self.usuario)
        sesion = self.client.session
        sesion["empresa_id"] = self.empresa.pk
        sesion.save()
        gasto = self.crear()
        self.pagar(gasto, "50")
        listado = self.client.get(reverse("compras:lista"), {"q": "12345"})
        self.assertContains(listado, "Por pagar")
        self.assertEqual(listado.context["compras"].object_list[0]["saldo"], Decimal("68"))
        detalle = self.client.get(reverse("compras:detalle_gasto", args=[gasto.pk]))
        self.assertContains(detalle, "Ver pagos registrados")
        self.assertContains(detalle, "Registrar pago")
        pantalla_pago = self.client.get(reverse("compras:pagar_gasto", args=[gasto.pk]))
        self.assertContains(pantalla_pago, self.proveedor.nombre)
        self.assertContains(pantalla_pago, "Saldo pendiente")
        self.assertEqual(pantalla_pago.context["saldo"], Decimal("68"))
        self.assertEqual(pantalla_pago.context["formulario"].initial["importe"], Decimal("68"))
        self.pagar(gasto, "68")
        respuesta = self.client.get(reverse("compras:pagar_gasto", args=[gasto.pk]))
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[gasto.pk]))

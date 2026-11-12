from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from contabilidad.models import Asiento
from contabilidad.servicios import ContabilidadError
from core.models import Periodo
from tesoreria.models import MovimientoTesoreria
from ventas.asignacion_cobros import asignar_cobro
from ventas.models import CuotaVenta, NotaCredito, Venta, VentaLinea
from ventas.servicios import VentaError, confirmar, emitir_nota_credito
from ventas.servicios_cobro import cobrar_venta, saldo_pendiente

from .test_invariantes import BaseContable


class CobrosVentaTest(BaseContable):
    def setUp(self):
        self.comprar("2", "50")
        self.venta = Venta.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            cliente_nombre=self.cliente.nombre,
            fecha=date(2026, 11, 20),
            tipo_doc="FACTURA",
            serie="E001",
            numero="1",
            condicion="CREDITO",
        )
        VentaLinea.objects.create(
            venta=self.venta, producto=self.producto, cantidad=1, precio_unitario=118, base=100, igv=18, total=118
        )
        CuotaVenta.objects.create(venta=self.venta, numero=1, vencimiento=date(2026, 12, 20), importe=118)
        self.venta = confirmar(self.venta)

    def cobrar(self, importe, **opciones):
        datos = dict(
            venta=self.venta,
            fecha=date(2026, 11, 21),
            importe=Decimal(importe),
            cuenta=self.bbva,
            canal="TRANSFERENCIA",
        )
        datos.update(opciones)
        return cobrar_venta(**datos)

    def test_cobros_parciales_vinculan_tesoreria_y_asiento(self):
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="VENTA", origen_id=self.venta.pk).exists())
        primero = self.cobrar("50")
        self.assertEqual(saldo_pendiente(self.venta), Decimal("68"))
        segundo = self.cobrar("68")
        self.assertEqual(saldo_pendiente(self.venta), Decimal("0"))
        for cobro in (primero, segundo):
            self.assertEqual(
                MovimientoTesoreria.objects.filter(
                    origen_tipo="COBRO_VENTA", origen_id=cobro.pk, importe=cobro.importe
                ).count(),
                1,
            )
            self.assertEqual(Asiento.objects.filter(origen_tipo="COBRO_VENTA", origen_id=cobro.pk).count(), 1)
        with self.assertRaises(VentaError):
            self.cobrar("0.01")

    def test_asigna_cobros_a_cuotas_sin_superar_lo_pactado(self):
        cuota = self.venta.cuotas.get(numero=1)
        cuota.importe = Decimal("50")
        cuota.save(update_fields=["importe"])
        segunda = CuotaVenta.objects.create(
            venta=self.venta, numero=2, vencimiento=date(2027, 1, 20), importe=68,
        )
        primero = self.cobrar("40", cuota=cuota)
        self.assertEqual(primero.cuota_id, cuota.pk)
        with self.assertRaisesMessage(VentaError, "supera el importe disponible"):
            self.cobrar("11", cuota=cuota)
        self.cobrar("10", cuota=cuota)
        self.cobrar("68", cuota=segunda)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("0"))
        self.assertEqual(cuota.cobros_asignados.count(), 2)
        self.assertEqual(segunda.cobros_asignados.count(), 1)

    def test_no_asigna_cuota_ajena_ni_con_cobros_anteriores_sin_asignar(self):
        otra_venta = Venta.objects.create(empresa=self.empresa, fecha=self.venta.fecha, serie="F002", numero="2")
        otra_cuota = CuotaVenta.objects.create(venta=otra_venta, numero=1, vencimiento=date(2026, 12, 20), importe=118)
        with self.assertRaisesMessage(VentaError, "cuota no pertenece"):
            self.cobrar("10", cuota=otra_cuota)
        self.cobrar("10", asignar_automaticamente=False)
        with self.assertRaisesMessage(VentaError, "cobros sin asignar"):
            self.cobrar("10", cuota=self.venta.cuotas.get())
        self.assertEqual(self.venta.cobros.count(), 1)

    def test_nota_de_credito_impide_inferir_la_asignacion_a_cuotas(self):
        NotaCredito.objects.create(venta=self.venta, fecha=self.venta.fecha, serie="FC01", numero="1",
                                   motivo="Ajuste", total=10)
        with self.assertRaisesMessage(VentaError, "notas que requieren revisión"):
            self.cobrar("10", cuota=self.venta.cuotas.get())
        self.assertFalse(self.venta.cobros.exists())

    def test_asigna_cobro_existente_sin_crear_otro_movimiento(self):
        usuario = get_user_model().objects.create_user(username="asignador")
        cobro = self.cobrar("50", asignar_automaticamente=False)
        cuota = self.venta.cuotas.get()
        movimientos = MovimientoTesoreria.objects.count()
        asientos = Asiento.objects.count()
        self.assertTrue(asignar_cobro(venta=self.venta, cobro_id=cobro.pk, cuota_id=cuota.pk, usuario=usuario))
        self.assertFalse(asignar_cobro(venta=self.venta, cobro_id=cobro.pk, cuota_id=cuota.pk, usuario=usuario))
        cobro.refresh_from_db()
        self.assertEqual(cobro.cuota_id, cuota.pk)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("68"))
        self.assertEqual(MovimientoTesoreria.objects.count(), movimientos)
        self.assertEqual(Asiento.objects.count(), asientos)
        self.assertTrue(self.empresa.historial.filter(tipo="VENTA", documento_id=self.venta.pk,
                                                       accion="ASIGNAR_CUOTA", usuario=usuario).exists())

    def test_no_asigna_con_nota_periodo_cerrado_o_movimiento_inconsistente(self):
        usuario = get_user_model().objects.create_user(username="revisor")
        cobro = self.cobrar("50", asignar_automaticamente=False)
        cuota = self.venta.cuotas.get()
        kwargs = {"venta": self.venta, "cobro_id": cobro.pk, "cuota_id": cuota.pk, "usuario": usuario}
        movimiento = MovimientoTesoreria.objects.get(origen_tipo="COBRO_VENTA", origen_id=cobro.pk)
        movimiento.importe = Decimal("49")
        movimiento.save(update_fields=["importe"])
        with self.assertRaisesMessage(VentaError, "movimiento de este cobro necesita revisión"):
            asignar_cobro(**kwargs)
        movimiento.importe = Decimal("50")
        movimiento.save(update_fields=["importe"])
        periodo = Periodo.objects.get(empresa=self.empresa, anio=2026, mes=11)
        periodo.estado = Periodo.Estado.CERRADO
        periodo.save(update_fields=["estado"])
        with self.assertRaisesMessage(VentaError, "período del cobro está cerrado"):
            asignar_cobro(**kwargs)
        periodo.estado = Periodo.Estado.ABIERTO
        periodo.save(update_fields=["estado"])
        NotaCredito.objects.create(venta=self.venta, fecha=self.venta.fecha, serie="FC01", numero="1",
                                   motivo="Ajuste", total=10)
        with self.assertRaisesMessage(VentaError, "venta tiene notas"):
            asignar_cobro(**kwargs)
        cobro.refresh_from_db()
        self.assertIsNone(cobro.cuota_id)

    def test_no_asigna_un_cobro_mayor_a_cuota_ni_cuota_de_otra_venta(self):
        usuario = get_user_model().objects.create_user(username="asignacion_limites")
        cobro = self.cobrar("50", asignar_automaticamente=False)
        cuota = self.venta.cuotas.get()
        cuota.importe = Decimal("40")
        cuota.save(update_fields=["importe"])
        otra = Venta.objects.create(empresa=self.empresa, fecha=self.venta.fecha, serie="F002", numero="3")
        cuota_ajena = CuotaVenta.objects.create(venta=otra, numero=1, vencimiento=date(2026, 12, 20), importe=100)
        with self.assertRaisesMessage(VentaError, "supera el importe disponible"):
            asignar_cobro(venta=self.venta, cobro_id=cobro.pk, cuota_id=cuota.pk, usuario=usuario)
        with self.assertRaisesMessage(VentaError, "no pertenecen a esta venta"):
            asignar_cobro(venta=self.venta, cobro_id=cobro.pk, cuota_id=cuota_ajena.pk, usuario=usuario)
        cobro.refresh_from_db()
        self.assertIsNone(cobro.cuota_id)

    def test_pantalla_exige_confirmacion_para_asignar(self):
        usuario = get_user_model().objects.create_superuser(username="asignador_web", password="test")
        self.client.force_login(usuario)
        cobro = self.cobrar("50", asignar_automaticamente=False)
        cuota = self.venta.cuotas.get()
        url = reverse("ventas:asignar_cuota", args=[self.venta.pk, cobro.pk])
        self.assertContains(self.client.get(url), "no registra otra entrada de dinero")
        self.assertEqual(self.client.post(url, {"cuota": cuota.pk}).status_code, 200)
        cobro.refresh_from_db()
        self.assertIsNone(cobro.cuota_id)
        respuesta = self.client.post(url, {"cuota": cuota.pk, "confirmado": "on"})
        self.assertRedirects(respuesta, reverse("ventas:detalle", args=[self.venta.pk]))
        cobro.refresh_from_db()
        self.assertEqual(cobro.cuota_id, cuota.pk)

    def test_rechaza_cobro_retroactivo_excesivo_o_cuenta_inactiva(self):
        for importe, opciones in [("119", {}), ("1", {"fecha": date(2026, 11, 19)})]:
            with self.assertRaises(VentaError):
                self.cobrar(importe, **opciones)
        self.bbva.activa = False
        self.bbva.save(update_fields=["activa"])
        with self.assertRaises(VentaError):
            self.cobrar("1")
        self.assertFalse(self.venta.cobros.exists())

    def test_movimiento_historico_no_bloquea_y_reduce_el_saldo(self):
        MovimientoTesoreria.objects.create(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=self.venta.fecha,
            tipo="INGRESO",
            importe=10,
            origen_tipo="VENTA",
            origen_id=self.venta.pk,
        )
        self.assertEqual(saldo_pendiente(self.venta), Decimal("108"))
        cobro = self.cobrar("50")
        self.assertEqual(saldo_pendiente(self.venta), Decimal("58"))
        self.assertEqual(cobro.cuota_id, self.venta.cuotas.get().pk)

    def test_nota_posterior_a_cobro_muestra_saldo_a_favor(self):
        self.cobrar("50")
        datos = dict(venta=self.venta, serie="FC01", numero="1", motivo_codigo="06")
        with self.assertRaisesMessage(VentaError, "anterior a un cobro"):
            emitir_nota_credito(fecha=date(2026, 11, 20), **datos)
        emitir_nota_credito(fecha=date(2026, 11, 22), **datos)
        self.assertEqual(saldo_pendiente(self.venta), Decimal("-50"))
        with self.assertRaises(VentaError):
            self.cobrar("1", fecha=date(2026, 11, 22))

    def test_periodo_cerrado_no_deja_cobro_ni_movimiento(self):
        Periodo.objects.filter(empresa=self.empresa, anio=2026, mes=11).update(estado=Periodo.Estado.CERRADO)
        with self.assertRaises(ContabilidadError):
            self.cobrar("10", cuota=self.venta.cuotas.get())
        self.assertFalse(self.venta.cobros.exists())
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="COBRO_VENTA").exists())

    def test_detalle_muestra_saldo_y_formulario_registra_cobro(self):
        user = get_user_model().objects.create_superuser(username="cobrador", password="test")
        self.client.force_login(user)
        detalle = self.client.get(reverse("ventas:detalle", args=[self.venta.pk]))
        self.assertContains(detalle, "Saldo pendiente")
        url = reverse("ventas:cobrar", args=[self.venta.pk])
        formulario = self.client.get(url)
        datos = {"fecha": "2026-11-21", "importe": "50.00", "cuenta": self.bbva.pk,
                 "canal": "TRANSFERENCIA", "cuota": self.venta.cuotas.get().pk,
                 "operacion": str(formulario.context["formulario"].initial["operacion"])}
        response = self.client.post(
            url, datos,
        )
        self.assertRedirects(response, reverse("ventas:detalle", args=[self.venta.pk]))
        self.assertRedirects(self.client.post(url, datos), reverse("ventas:detalle", args=[self.venta.pk]))
        self.assertEqual(saldo_pendiente(self.venta), Decimal("68"))
        self.assertEqual(self.venta.cobros.count(), 1)
        self.assertEqual(self.venta.cobros.get().cuota_id, self.venta.cuotas.get().pk)
        self.assertEqual(MovimientoTesoreria.objects.filter(origen_tipo="COBRO_VENTA").count(), 1)
        self.assertContains(self.client.get(reverse("ventas:detalle", args=[self.venta.pk])), "Cobros asignados")

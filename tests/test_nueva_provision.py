from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.urls import reverse

from compras.models_gasto import Gasto
from contabilidad.models import Asiento, Cuenta
from core.models import HistorialDocumento, Perfil, Periodo
from reportes.casillas import calcular
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable


class NuevaProvisionTest(BaseContable):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="provision")
        self.perfil = Perfil.objects.create(usuario=self.usuario, empresa=self.empresa)
        self.client.force_login(self.usuario)
        self.url = reverse("compras:nueva_provision")
        self.datos = {
            "fecha": "2026-11-10",
            "proveedor": self.proveedor.pk,
            "importe": "28.00",
            "cuenta": Cuenta.objects.get(version="2026", codigo="6391").pk,
            "glosa": "Comisión devengada",
            "confirmado": "on",
            "operacion": str(uuid4()),
        }

    def test_crea_asiento_sin_pago_ni_credito_y_evitar_repeticion(self):
        antes = calcular(self.empresa, 2026, 11)
        respuesta = self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertEqual(provision.fecha_devengado, date(2026, 11, 10))
        self.assertEqual(provision.total, Decimal("28"))
        self.assertFalse(provision.con_credito)
        self.assertFalse(provision.deducible)
        asiento = Asiento.objects.get(empresa=self.empresa, origen_tipo="GASTO", origen_id=provision.pk)
        lineas = {linea.cuenta.codigo: (linea.debe, linea.haber) for linea in asiento.lineas.all()}
        self.assertEqual(lineas["6391"], (Decimal("28"), Decimal("0")))
        self.assertEqual(lineas["4211"], (Decimal("0"), Decimal("28")))
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="GASTO", origen_id=provision.pk).exists())
        self.assertTrue(
            HistorialDocumento.objects.filter(
                empresa=self.empresa, tipo="GASTO", documento_id=provision.pk, usuario=self.usuario, accion="PROVISION"
            ).exists()
        )
        detalle = self.client.get(reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertContains(detalle, "Gasto devengado registrado sin comprobante")
        self.assertNotContains(detalle, self.datos["operacion"])
        self.assertEqual(calcular(self.empresa, 2026, 11), antes)
        respuesta = self.client.post(self.url, self.datos)
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[provision.pk]))
        self.assertEqual(Gasto.objects.filter(empresa=self.empresa, provision=True).count(), 1)
        self.assertEqual(
            Asiento.objects.filter(empresa=self.empresa, origen_tipo="GASTO", origen_id=provision.pk).count(), 1
        )

    def test_periodo_cerrado_o_falta_de_confirmacion_no_registran(self):
        periodo, _ = Periodo.objects.get_or_create(empresa=self.empresa, anio=2026, mes=11)
        periodo.estado = Periodo.Estado.CERRADO
        periodo.save(update_fields=["estado"])
        respuesta = self.client.post(self.url, self.datos)
        self.assertContains(respuesta, "cerrado")
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())
        periodo.estado = Periodo.Estado.ABIERTO
        periodo.save(update_fields=["estado"])
        datos = self.datos.copy()
        datos.pop("confirmado")
        self.assertEqual(self.client.post(self.url, datos).status_code, 200)
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())

    def test_liquida_la_provision_con_comprobante_sin_duplicar_el_gasto(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {
            "fecha": "2026-11-11",
            "proveedor": self.proveedor.pk,
            "tipo_doc": "FACTURA",
            "serie": "F001",
            "numero": "19",
            "base": "28",
            "igv": "0",
            "cuenta": self.datos["cuenta"],
            "medio": self.bbva.pk,
            "canal": "TRANSFERENCIA",
            "glosa": "Comisión facturada",
            "provisiones": [provision.pk],
        }
        respuesta = self.client.post(reverse("compras:nuevo_gasto"), datos)
        self.assertEqual(respuesta.status_code, 302)
        factura = Gasto.objects.get(empresa=self.empresa, serie="F001", numero="19")
        provision.refresh_from_db()
        self.assertEqual(provision.gasto_origen_id, factura.pk)
        lineas = Asiento.objects.filter(empresa=self.empresa, estado="CONFIRMADO").values_list(
            "lineas__cuenta__codigo", "lineas__debe", "lineas__haber"
        )
        gasto = sum((debe - haber for codigo, debe, haber in lineas if codigo == "6391"), Decimal("0"))
        self.assertEqual(gasto, Decimal("28"))
        self.assertTrue(MovimientoTesoreria.objects.filter(origen_tipo="GASTO", origen_id=factura.pk).exists())

    def test_usuario_lector_no_puede_registrar(self):
        self.perfil.rol = Perfil.Rol.LECTOR
        self.perfil.save(update_fields=["rol"])
        self.assertRedirects(self.client.post(self.url, self.datos), reverse("core:panel"))
        self.assertFalse(Gasto.objects.filter(empresa=self.empresa, provision=True).exists())

    def test_comprobante_vinculado_puede_pagarse_despues_sin_duplicar_el_gasto(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {
            "fecha": "2026-11-11", "proveedor": self.proveedor.pk, "tipo_doc": "FACTURA",
            "serie": "F001", "numero": "20", "base": "28", "igv": "0", "cuenta": self.datos["cuenta"],
            "glosa": "Comisión facturada", "provisiones": [provision.pk],
        }
        respuesta = self.client.post(reverse("compras:nuevo_gasto_pendiente"), datos)
        factura = Gasto.objects.get(empresa=self.empresa, serie="F001", numero="20")
        self.assertRedirects(respuesta, reverse("compras:detalle_gasto", args=[factura.pk]))
        provision.refresh_from_db()
        self.assertEqual(provision.gasto_origen_id, factura.pk)
        self.assertFalse(MovimientoTesoreria.objects.exists())
        self.assertEqual(Asiento.objects.filter(empresa=self.empresa).count(), 2)
        reclasificacion = Asiento.objects.get(origen_tipo="GASTO_RECLAS_PROV", origen_id=factura.pk)
        self.assertEqual(reclasificacion.lineas.get(cuenta__codigo="4211").debe, Decimal("28"))
        self.assertEqual(reclasificacion.lineas.get(cuenta__codigo="4212").haber, Decimal("28"))
        detalle = self.client.get(reverse("compras:detalle_gasto", args=[factura.pk]))
        self.assertContains(detalle, "Saldo pendiente")
        self.assertContains(detalle, "Registrar pago")
        self.assertContains(detalle, "Ver cuentas de las provisiones vinculadas")
        listado = self.client.get(reverse("compras:lista"), {"estado_pago": "por_pagar"})
        self.assertContains(listado, "F001-20")
        for importe in ("10", "18"):
            respuesta = self.client.post(reverse("compras:pagar_gasto", args=[factura.pk]), {
                "fecha": "2026-11-12", "importe": importe, "cuenta": self.bbva.pk, "canal": "TRANSFERENCIA",
                "operacion": str(uuid4()),
            })
            self.assertEqual(respuesta.status_code, 302)
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Gasto.Estado.PAGADO)
        self.assertEqual(factura.pagos.count(), 2)
        self.assertEqual(MovimientoTesoreria.objects.filter(origen_tipo="PAGO_GASTO").count(), 2)
        lineas = Asiento.objects.filter(empresa=self.empresa, estado="CONFIRMADO").values_list(
            "lineas__cuenta__codigo", "lineas__debe", "lineas__haber"
        )
        gasto = sum((debe - haber for codigo, debe, haber in lineas if codigo == "6391"), Decimal("0"))
        deuda = sum((haber - debe for codigo, debe, haber in lineas if codigo == "4212"), Decimal("0"))
        deuda_no_emitida = sum((haber - debe for codigo, debe, haber in lineas if codigo == "4211"), Decimal("0"))
        self.assertEqual(gasto, Decimal("28"))
        self.assertEqual(deuda, Decimal("0"))
        self.assertEqual(deuda_no_emitida, Decimal("0"))

    def test_provision_con_igv_o_respaldo_invalido_no_vincula(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {"fecha": "2026-11-11", "proveedor": self.proveedor.pk, "tipo_doc": "FACTURA",
                 "serie": "F001", "numero": "21", "base": "28", "igv": "1",
                 "cuenta": self.datos["cuenta"], "glosa": "Servicio", "provisiones": [provision.pk]}
        respuesta = self.client.post(reverse("compras:nuevo_gasto_pendiente"), datos)
        self.assertContains(respuesta, "La liquidación solo admite")
        provision.refresh_from_db()
        self.assertIsNone(provision.gasto_origen_id)
        self.assertFalse(Gasto.objects.filter(serie="F001", numero="21").exists())
        datos["igv"] = "0"
        MovimientoTesoreria.objects.create(empresa=self.empresa, cuenta=self.bbva, fecha=date(2026, 11, 10),
                                           tipo="EGRESO", importe=28, concepto="Anterior",
                                           origen_tipo="GASTO", origen_id=provision.pk)
        respuesta = self.client.post(reverse("compras:nuevo_gasto_pendiente"), datos)
        self.assertContains(respuesta, "necesitan revisión")
        provision.refresh_from_db()
        self.assertIsNone(provision.gasto_origen_id)
        self.assertFalse(Gasto.objects.filter(serie="F001", numero="21").exists())

    def test_pago_bloqueado_si_asiento_de_provision_fue_anulado(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {"fecha": "2026-11-11", "proveedor": self.proveedor.pk, "tipo_doc": "FACTURA",
                 "serie": "F001", "numero": "22", "base": "28", "igv": "0",
                 "cuenta": self.datos["cuenta"], "glosa": "Servicio", "provisiones": [provision.pk]}
        self.assertEqual(self.client.post(reverse("compras:nuevo_gasto_pendiente"), datos).status_code, 302)
        factura = Gasto.objects.get(serie="F001", numero="22")
        Asiento.objects.filter(origen_tipo="GASTO", origen_id=provision.pk).update(estado="ANULADO")
        respuesta = self.client.post(reverse("compras:pagar_gasto", args=[factura.pk]), {
            "fecha": "2026-11-12", "importe": "10", "cuenta": self.bbva.pk, "canal": "TRANSFERENCIA",
            "operacion": str(uuid4()),
        })
        self.assertContains(respuesta, "necesita revisión")
        self.assertFalse(factura.pagos.exists())
        self.assertFalse(MovimientoTesoreria.objects.filter(origen_tipo="PAGO_GASTO").exists())

    def test_vincula_provisiones_antiguas_y_nuevas_sin_reescribir_asientos(self):
        datos = self.datos | {"importe": "10", "operacion": str(uuid4())}
        self.client.post(self.url, datos)
        antigua = Gasto.objects.get(empresa=self.empresa, provision=True)
        asiento_antiguo = Asiento.objects.get(origen_tipo="GASTO", origen_id=antigua.pk)
        linea = asiento_antiguo.lineas.get(cuenta__codigo="4211")
        linea.cuenta = Cuenta.objects.get(version="2026", codigo="4212")
        linea.save(update_fields=["cuenta"])
        self.client.post(self.url, self.datos | {"importe": "18", "operacion": str(uuid4())})
        nueva = Gasto.objects.filter(empresa=self.empresa, provision=True).exclude(pk=antigua.pk).get()
        factura_datos = {
            "fecha": "2026-11-11", "proveedor": self.proveedor.pk, "tipo_doc": "FACTURA",
            "serie": "F001", "numero": "23", "base": "28", "igv": "0", "cuenta": self.datos["cuenta"],
            "glosa": "Comisión facturada", "provisiones": [antigua.pk, nueva.pk],
        }
        self.assertEqual(self.client.post(reverse("compras:nuevo_gasto_pendiente"), factura_datos).status_code, 302)
        factura = Gasto.objects.get(serie="F001", numero="23")
        reclasificacion = Asiento.objects.get(origen_tipo="GASTO_RECLAS_PROV", origen_id=factura.pk)
        self.assertEqual(reclasificacion.lineas.get(cuenta__codigo="4211").debe, Decimal("18"))
        self.assertEqual(reclasificacion.lineas.get(cuenta__codigo="4212").haber, Decimal("18"))
        linea.refresh_from_db()
        self.assertEqual(linea.cuenta.codigo, "4212")
        respuesta = self.client.post(reverse("compras:pagar_gasto", args=[factura.pk]), {
            "fecha": "2026-11-12", "importe": "28", "cuenta": self.bbva.pk, "canal": "TRANSFERENCIA",
            "operacion": str(uuid4()),
        })
        self.assertEqual(respuesta.status_code, 302)
        factura.refresh_from_db()
        self.assertEqual(factura.estado, Gasto.Estado.PAGADO)

    def test_si_se_anula_la_reclasificacion_no_se_permite_pago(self):
        self.client.post(self.url, self.datos)
        provision = Gasto.objects.get(empresa=self.empresa, provision=True)
        datos = {"fecha": "2026-11-11", "proveedor": self.proveedor.pk, "tipo_doc": "FACTURA",
                 "serie": "F001", "numero": "24", "base": "28", "igv": "0",
                 "cuenta": self.datos["cuenta"], "glosa": "Servicio", "provisiones": [provision.pk]}
        self.assertEqual(self.client.post(reverse("compras:nuevo_gasto_pendiente"), datos).status_code, 302)
        factura = Gasto.objects.get(serie="F001", numero="24")
        Asiento.objects.filter(origen_tipo="GASTO_RECLAS_PROV", origen_id=factura.pk).update(estado="ANULADO")
        respuesta = self.client.post(reverse("compras:pagar_gasto", args=[factura.pk]), {
            "fecha": "2026-11-12", "importe": "10", "cuenta": self.bbva.pk, "canal": "TRANSFERENCIA",
            "operacion": str(uuid4()),
        })
        self.assertContains(respuesta, "reclasificación de las provisiones necesita revisión")
        self.assertFalse(factura.pagos.exists())

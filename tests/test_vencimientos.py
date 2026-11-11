import tempfile
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from contabilidad.impuestos import pagar_igv
from contabilidad.models import DeclaracionIGV621
from reportes.estados_sire import registrar_generacion, registrar_propuesta
from reportes.vencimientos import (
    OBLIGACIONES,
    PERIODO_VERIFICADO,
    panel_vencimientos,
    resumen_panel,
)
from tesoreria.servicios import registrar

from .test_invariantes import BaseContable

settings.MEDIA_ROOT = tempfile.mkdtemp(prefix="tilmux-vencimientos-")


class VencimientosOctubreTest(BaseContable):
    """Octubre 2026: SIRE 16/11, PDT 621 e IGV 17/11 (fechas verificadas)."""

    def crear_octubre(self):
        # Compra de dos unidades con crédito de 110: deja el IGV del período en 105,38.
        self.comprar("2", "305.555", fecha=date(2026, 10, 5))
        # Ventas del período: dos comprobantes de 706 con IGV = 1.196,62 / 215,38.
        self.vender("1", "706", fecha=date(2026, 10, 29))
        self.vender("1", "706", fecha=date(2026, 10, 30))

    def generar_sire(self):
        for registro in ("RCE", "RVIE"):
            registrar_propuesta(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro=registro,
                archivo=SimpleUploadedFile(f"{registro}.csv", b"propuesta"),
                filas=1,
                base=Decimal("0"),
                igv=Decimal("0"),
                total=Decimal("1"),
            )
            registrar_generacion(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro=registro,
                constancia_recepcion=f"CE-{registro}",
                numero_operacion=f"OP-{registro}",
                registros=1,
            )

    def test_octubre_en_cero_muestra_los_tres_pendientes(self):
        self.crear_octubre()

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 10))
        estados = {obligacion["clave"]: obligacion for obligacion in datos["obligaciones"]}

        self.assertTrue(datos["verificado"])
        self.assertEqual(estados["SIRE"]["estado"], "PENDIENTE")
        self.assertEqual(estados["PDT"]["estado"], "PENDIENTE")
        self.assertEqual(estados["IGV"]["estado"], "PENDIENTE")
        self.assertEqual(estados["IGV"]["tono"], "rojo")
        self.assertEqual(estados["SIRE"]["fecha"], date(2026, 11, 16))
        self.assertEqual(estados["PDT"]["fecha"], date(2026, 11, 17))
        self.assertEqual(estados["IGV"]["fecha"], date(2026, 11, 17))
        self.assertEqual(datos["igv"]["pendiente"], Decimal("105.38"))
        self.assertEqual(datos["pendientes"], 3)
        self.assertEqual(datos["vencidos"], 0)
        self.assertEqual(datos["proximo"]["clave"], "SIRE")

    def test_sire_generado_con_constancia_pone_la_obligacion_en_verde(self):
        self.crear_octubre()
        self.generar_sire()

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 10))
        sire = next(obligacion for obligacion in datos["obligaciones"] if obligacion["clave"] == "SIRE")

        self.assertTrue(datos["sire"]["cerrado"])
        self.assertEqual(sire["estado"], "GENERADO")
        self.assertEqual(sire["tono"], "ok")
        self.assertTrue(all(registro["cerrado"] for registro in sire["extra"]["registros"]))

    def test_declaracion_registrada_marca_el_pdt(self):
        DeclaracionIGV621.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            tipo=DeclaracionIGV621.Tipo.ORIGINAL,
            numero_orden="1211949769",
            fecha_presentacion=date(2026, 11, 17),
            casilla_140=Decimal("215"),
            casilla_145=Decimal("110"),
            casilla_184=Decimal("105"),
        )

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 10))
        pdt = next(obligacion for obligacion in datos["obligaciones"] if obligacion["clave"] == "PDT")

        self.assertEqual(pdt["estado"], "DECLARADO")
        self.assertEqual(pdt["tono"], "ok")
        self.assertEqual(datos["pdt"]["casilla_184"], Decimal("105"))
        self.assertTrue(pdt["extra"]["registro_manual"])

    def test_pago_del_igv_deja_la_obligacion_pagada(self):
        self.crear_octubre()

        pagar_igv(
            self.empresa,
            fecha=date(2026, 11, 15),
            importe=Decimal("105.38"),
            medio=self.bbva,
            anio=2026,
            mes=10,
        )

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 16))
        igv = next(obligacion for obligacion in datos["obligaciones"] if obligacion["clave"] == "IGV")

        self.assertEqual(datos["igv"]["pendiente"], Decimal("0"))
        self.assertEqual(datos["igv"]["pagado"], Decimal("105.38"))
        self.assertEqual(igv["estado"], "PAGADO")
        self.assertEqual(igv["tono"], "ok")

    def test_al_pasar_la_fecha_las_obligaciones_estan_vencidas(self):
        self.crear_octubre()

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 18))
        estados = {obligacion["clave"]: obligacion["estado"] for obligacion in datos["obligaciones"]}

        self.assertEqual(estados, {"SIRE": "VENCIDO", "PDT": "VENCIDO", "IGV": "VENCIDO"})
        self.assertEqual(datos["vencidos"], 3)
        self.assertTrue(all(obligacion["tono"] == "rojo" for obligacion in datos["obligaciones"]))

    def test_periodo_sin_fechas_verificadas_no_inventa_vencimientos(self):
        datos = panel_vencimientos(self.empresa, 2026, 11)

        self.assertFalse(datos["verificado"])
        self.assertEqual(datos["obligaciones"], [])
        self.assertIn("No hay fechas de vencimiento verificadas", datos["mensaje"])
        self.assertFalse(resumen_panel(self.empresa, 2026, 11)["verificado"])
        self.assertEqual(PERIODO_VERIFICADO, (2026, 10))
        self.assertEqual({obligacion["clave"] for obligacion in OBLIGACIONES}, {"SIRE", "PDT", "IGV"})

    def test_caja_muestra_las_deudas_del_socio_sin_darlas_por_pagadas(self):
        registrar(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=date(2026, 9, 18),
            tipo="INGRESO",
            importe=Decimal("500.00"),
            concepto="Préstamo del socio",
            tipo_regla="PRESTAMO_SOCIO",
        )
        registrar(
            empresa=self.empresa,
            cuenta=self.bbva,
            fecha=date(2026, 10, 3),
            tipo="INGRESO",
            importe=Decimal("39.00"),
            concepto="Token BCP del socio",
            tipo_regla="REEMBOLSO_SOCIO",
        )

        datos = panel_vencimientos(self.empresa, 2026, 10, hoy=date(2026, 11, 10))

        self.assertEqual(datos["caja"]["prestamo_socio"], Decimal("500.00"))
        self.assertEqual(datos["caja"]["reembolso_socio"], Decimal("39.00"))
        self.assertEqual(datos["caja"]["restituciones_registradas"], 0)
        self.assertIn("no dependen de que llegue el depósito", datos["caja"]["nota"])

    def test_pagina_y_tarjeta_del_panel_muestran_los_vencimientos(self):
        self.crear_octubre()
        usuario = get_user_model().objects.create_superuser(username="vencimientos", password="test")
        self.client.force_login(usuario)

        pagina = self.client.get(reverse("reportes:vencimientos"), {"anio": 2026, "mes": 10})
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "PDT 621")
        self.assertContains(pagina, "SIRE")
        self.assertContains(pagina, "105,38")
        self.assertContains(pagina, "16/11/2026")
        self.assertContains(pagina, "17/11/2026")

        panel = self.client.get(reverse("core:panel"))
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "Vencimientos tributarios")

        otro = self.client.get(reverse("reportes:vencimientos"), {"anio": 2026, "mes": 11})
        self.assertEqual(otro.status_code, 200)
        self.assertContains(otro, "No hay fechas de vencimiento verificadas")

import tempfile
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from compras.devoluciones import registrar_devolucion
from reportes.conciliacion_rce import comparar_rce
from reportes.estados_sire import (
    SireError,
    estado_de,
    registrar_ajuste,
    registrar_generacion,
    registrar_propuesta,
    resumen_periodo,
)
from reportes.models import EstadoSIRE, PropuestaSIRE

from .test_invariantes import BaseContable

DIRECTORIO_MEDIA = tempfile.mkdtemp(prefix="tilmux-sire-")
# Se fija antes de que el almacenamiento por defecto resuelva MEDIA_ROOT:
# con override_settings el archivo de prueba cae en media/ del repo.
settings.MEDIA_ROOT = DIRECTORIO_MEDIA

CABECERA_RCE = [
    "RUC",
    "ID",
    "Periodo",
    "CAR SUNAT",
    "Fecha de Emisión",
    "Fecha Vcto/Pago",
    "Tipo CP/Doc.",
    "Serie del CDP",
    "Nro CP o Doc. Nro Inicial (Rango)",
    "Nro Final (Rango)",
    "Tipo Doc Identidad",
    "Nro Doc Identidad",
    "Apellidos Nombres/ Razón Social",
    "BI Gravado DG",
    "IGV / IPM DG",
    "Total CP",
    "Moneda",
]


def csv_bytes(cabecera, filas, delimitador="|"):
    texto = delimitador.join(cabecera) + "\n"
    for fila in filas:
        texto += delimitador.join(str(celda) for celda in fila) + "\n"
    return texto.encode("utf-8")


def archivo(nombre, contenido):
    return SimpleUploadedFile(nombre, contenido, content_type="text/csv")


class EstadosSireTest(BaseContable):
    """Propuesta, complemento y constancia: sin constancia no hay cierre."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username="sire", password="test")
        self.client.force_login(self.usuario)

    def cargar_propuesta(self, registro="RCE", total="0.00", filas=1, base="0.00", igv="0.00"):
        return registrar_propuesta(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro=registro,
            archivo=archivo(f"{registro.lower()}.csv", b"contenido-propuesta"),
            filas=filas,
            base=Decimal(base),
            igv=Decimal(igv),
            total=Decimal(total),
            usuario=self.usuario,
        )

    def test_octubre_sin_propuesta_no_esta_cerrado(self):
        resumen = resumen_periodo(self.empresa, 2026, 10)

        self.assertFalse(resumen["cerrado"])
        self.assertEqual([fila["estado"] for fila in resumen["registros"]], ["SIN PROPUESTA"] * 2)
        # Consultar el período no debe inventar registros de estado.
        self.assertFalse(EstadoSIRE.objects.exists())
        self.assertFalse(estado_de(self.empresa, 2026, 10, "RCE").cerrado)

    def test_propuesta_rce_de_octubre_guarda_archivo_hash_y_totales(self):
        propuesta = self.cargar_propuesta(total="43.00", filas=3)

        self.assertEqual(propuesta.filas, 3)
        self.assertEqual(propuesta.total, Decimal("43.00"))
        self.assertEqual(len(propuesta.hash_sha256), 64)
        self.assertTrue(propuesta.archivo.name.endswith(".csv"))
        estado = estado_de(self.empresa, 2026, 10, "RCE")
        self.assertEqual(estado.estado, "PROPUESTA")
        self.assertFalse(estado.cerrado)

    def test_propuesta_rvie_de_octubre_con_las_cifras_del_periodo(self):
        self.cargar_propuesta(registro="RVIE", base="1196.62", igv="215.38", total="1412.00", filas=2)

        resumen = resumen_periodo(self.empresa, 2026, 10)
        rvie = next(fila for fila in resumen["registros"] if fila["registro"] == "RVIE")
        self.assertEqual(rvie["estado"], "PROPUESTA")
        self.assertEqual(rvie["propuesta"].base, Decimal("1196.62"))
        self.assertEqual(rvie["propuesta"].igv, Decimal("215.38"))
        self.assertEqual(rvie["propuesta"].total, Decimal("1412.00"))
        self.assertFalse(resumen["cerrado"])

    def test_complementar_la_boleta_deja_el_estado_complementada(self):
        propuesta = self.cargar_propuesta(total="43.00", filas=3)
        registrar_ajuste(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            tipo="AGREGADO",
            documento="B001-00393302",
            tipo_doc="BOLETA",
            fecha=date(2026, 10, 31),
            base=Decimal("198.04"),
            igv=Decimal("0.00"),
            total=Decimal("198.04"),
            motivo="Boleta tipo 03 de comisiones: entra por Complementar a casilla 120, sin crédito fiscal.",
            usuario=self.usuario,
        )

        estado = estado_de(self.empresa, 2026, 10, "RCE")
        self.assertEqual(estado.estado, "COMPLEMENTADA")
        self.assertFalse(estado.cerrado)
        ajuste = estado.ajustes.get()
        self.assertEqual(ajuste.tipo, "AGREGADO")
        self.assertEqual(ajuste.total, Decimal("198.04"))
        # La propuesta (43) más la boleta (198,04) es el total de libros del RCE.
        self.assertEqual(propuesta.total + ajuste.total, Decimal("241.04"))

    def test_ajuste_sin_propuesta_se_rechaza(self):
        with self.assertRaisesMessage(SireError, "No hay propuesta"):
            registrar_ajuste(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro="RCE",
                tipo="AGREGADO",
                documento="B001-1",
                base=Decimal("10"),
                motivo="Prueba de ajuste",
            )

    def test_generacion_exige_constancia_operacion_y_registros(self):
        self.cargar_propuesta(total="43.00", filas=3)
        with self.assertRaisesMessage(SireError, "constancia"):
            registrar_generacion(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro="RCE",
                constancia_recepcion="",
                numero_operacion="123",
                registros=3,
            )
        with self.assertRaisesMessage(SireError, "operación"):
            registrar_generacion(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro="RCE",
                constancia_recepcion="CE-1",
                numero_operacion="",
                registros=3,
            )
        with self.assertRaisesMessage(SireError, "registros"):
            registrar_generacion(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro="RCE",
                constancia_recepcion="CE-1",
                numero_operacion="123",
                registros=0,
            )

        estado = registrar_generacion(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            constancia_recepcion="CE-202610-1",
            numero_operacion="123456789",
            registros=3,
            generado_en=datetime(2026, 11, 5, 10, 30),
            usuario=self.usuario,
        )
        self.assertEqual(estado.estado, "GENERADO")
        self.assertTrue(estado.cerrado)
        self.assertEqual(estado.registros_generados, 3)
        self.assertIsNotNone(estado.generado_en)

    def test_rce_y_rvie_son_independientes_y_el_periodo_necesita_ambos(self):
        self.cargar_propuesta(registro="RCE", total="43.00", filas=3)
        self.cargar_propuesta(registro="RVIE", total="1412.00", filas=2)
        registrar_generacion(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            constancia_recepcion="CE-RCE",
            numero_operacion="111",
            registros=3,
        )

        resumen = resumen_periodo(self.empresa, 2026, 10)
        estados = {fila["registro"]: fila["estado"] for fila in resumen["registros"]}
        self.assertEqual(estados["RCE"], "GENERADO")
        self.assertEqual(estados["RVIE"], "PROPUESTA")
        self.assertFalse(resumen["cerrado"])

        registrar_generacion(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RVIE",
            constancia_recepcion="CE-RVIE",
            numero_operacion="222",
            registros=2,
        )
        self.assertTrue(resumen_periodo(self.empresa, 2026, 10)["cerrado"])

    def test_generado_no_admite_ajustes_posteriores(self):
        self.cargar_propuesta(total="43.00")
        registrar_generacion(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            constancia_recepcion="CE-1",
            numero_operacion="111",
            registros=1,
        )
        with self.assertRaisesMessage(SireError, "constancia de recepción"):
            registrar_ajuste(
                empresa=self.empresa,
                anio=2026,
                mes=10,
                registro="RCE",
                tipo="EXCLUIDO",
                documento="F001-9",
                base=Decimal("10"),
                motivo="Intento posterior a la generación",
            )

    def test_repropuesta_conserva_historial_y_no_duplica_el_mismo_archivo(self):
        primero = self.cargar_propuesta(total="43.00", filas=3)
        mismo = self.cargar_propuesta(total="43.00", filas=3)
        self.assertEqual(mismo.pk, primero.pk)
        self.assertEqual(PropuestaSIRE.objects.count(), 1)

        segunda = registrar_propuesta(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            archivo=archivo("rce-2.csv", b"otra-propuesta"),
            filas=4,
            base=Decimal("0"),
            igv=Decimal("0"),
            total=Decimal("53"),
            usuario=self.usuario,
        )
        self.assertNotEqual(segunda.pk, primero.pk)
        self.assertEqual(PropuestaSIRE.objects.count(), 2)
        self.assertEqual(estado_de(self.empresa, 2026, 10, "RCE").propuesta_actual.pk, segunda.pk)

    def test_pantalla_muestra_no_cerrado_y_permite_registrar_constancia(self):
        self.cargar_propuesta(total="43.00", filas=3)

        respuesta = self.client.get(reverse("reportes:estado_sire"), {"anio": 2026, "mes": 10})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "NO cerrado")
        self.assertContains(respuesta, "PROPUESTA")

        respuesta = self.client.post(
            reverse("reportes:estado_sire"),
            {
                "accion": "generar",
                "registro": "RCE",
                "anio": 2026,
                "mes": 10,
                "constancia_recepcion": "CE-202610-1",
                "numero_operacion": "123456789",
                "generado_en": "2026-11-05T10:30",
                "registros": "3",
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "GENERADO")
        self.assertContains(respuesta, "NO cerrado")  # RVIE sigue sin constancia

    def test_la_carga_de_la_propuesta_desde_la_pantalla_persiste_el_estado(self):
        filas = [
            [
                self.empresa.ruc,
                "TILMUX",
                "202610",
                "CAR1",
                "30/10/2026",
                "",
                "01",
                "FB29",
                "29938941",
                "",
                "6",
                "20100000001",
                "PROVEEDOR PRUEBA",
                "0.00",
                "0.00",
                "15.00",
                "PEN",
            ],
        ]
        contenido = csv_bytes(CABECERA_RCE, filas, delimitador="|")
        respuesta = self.client.post(
            reverse("reportes:conciliacion_archivo"),
            {"anio": "2026", "mes": "10", "registro": "compras", "archivo": archivo("rce-octubre.csv", contenido)},
        )
        self.assertEqual(respuesta.status_code, 200)
        estado = EstadoSIRE.objects.get(empresa=self.empresa, anio=2026, mes=10, registro="RCE")
        self.assertEqual(estado.estado, "PROPUESTA")
        self.assertEqual(estado.propuesta_actual.filas, 1)
        self.assertEqual(len(estado.propuesta_actual.hash_sha256), 64)


class ConciliacionRceNotaCreditoTest(BaseContable):
    """El tipo 07 de la propuesta se compara con las notas de crédito del ERP."""

    def setUp(self):
        self.compra = self.comprar("2", "100")
        self.linea = self.compra.lineas.get()
        self.nota = registrar_devolucion(
            compra=self.compra,
            fecha=date(2026, 11, 12),
            serie="FC01",
            numero="1",
            motivo_codigo="07",
            cantidades={self.linea.pk: Decimal("1")},
        )

    def filas(self, extra=None):
        filas = [CABECERA_RCE]
        filas.append(
            [
                "20100000001",
                "PROVEEDOR PRUEBA",
                "202611",
                "CAR1",
                "10/11/2026",
                "",
                "01",
                "F001",
                "1",
                "",
                "6",
                "20100000001",
                "PROVEEDOR PRUEBA",
                "200.00",
                "36.00",
                "236.00",
                "PEN",
            ]
        )
        filas.append(
            [
                "20100000001",
                "PROVEEDOR PRUEBA",
                "202611",
                "CAR2",
                "12/11/2026",
                "",
                "07",
                "FC01",
                "1",
                "",
                "6",
                "20100000001",
                "PROVEEDOR PRUEBA",
                "-100.00",
                "-18.00",
                "-118.00",
                "PEN",
            ]
        )
        if extra:
            filas.append(extra)
        return filas

    def test_la_nota_tipo_07_coincide_con_la_nota_del_erp(self):
        resultado = comparar_rce(filas=self.filas(), empresa=self.empresa, anio=2026, mes=11)

        self.assertEqual(resultado["coinciden"], 2)
        self.assertEqual(resultado["solo_archivo"], [])
        self.assertEqual(resultado["solo_sistema"], [])
        self.assertEqual(resultado["omitidos_archivo"], 0)

    def test_una_nota_07_sin_respaldo_queda_como_solo_archivo(self):
        extra = [
            "20100000001",
            "PROVEEDOR PRUEBA",
            "202611",
            "CAR3",
            "20/11/2026",
            "",
            "07",
            "FC99",
            "7",
            "",
            "6",
            "20100000001",
            "PROVEEDOR PRUEBA",
            "-50.00",
            "-9.00",
            "-59.00",
            "PEN",
        ]
        resultado = comparar_rce(filas=self.filas(extra), empresa=self.empresa, anio=2026, mes=11)

        self.assertEqual(resultado["coinciden"], 2)
        self.assertEqual(len(resultado["solo_archivo"]), 1)
        self.assertEqual(resultado["solo_archivo"][0]["tipo"], "Nota de crédito")
        self.assertEqual(resultado["solo_archivo"][0]["documento"], "FC99-7")


CABECERA_RVIE = [
    "Ruc",
    "Razon Social",
    "Periodo",
    "Tipo CP/Doc.",
    "Serie del CDP",
    "Nro CP o Doc. Nro Inicial (Rango)",
    "Nro Final (Rango)",
    "Tipo Doc Identidad",
    "Nro Doc Identidad",
    "Fecha de Emisión",
    "Valor Facturado Exportación",
    "BI Gravada",
    "Dscto BI",
    "IGV / IPM",
    "Dscto IGV / IPM",
    "Total CP",
    "Moneda",
]


class ConciliacionRvieSinRegistrosTest(BaseContable):
    """P0-7: el RVIE de 0 registros es válido y tiene su propio mensaje."""

    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username="rvie_sin_registros", password="test")
        self.client.force_login(self.usuario)

    def subir(self, contenido, mes="9"):
        return self.client.post(
            reverse("reportes:conciliacion_archivo"),
            {
                "anio": "2026",
                "mes": mes,
                "registro": "ventas",
                "archivo": archivo("rvie-setiembre.txt", contenido),
            },
        )

    def test_cero_registros_se_ve_como_sin_comprobantes_y_registra_la_propuesta(self):
        respuesta = self.subir(csv_bytes(CABECERA_RVIE, [], delimitador="|"))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Sin comprobantes")
        self.assertContains(respuesta, "no tiene comprobantes para el período")
        self.assertNotContains(respuesta, "Requiere revisión")
        estado = EstadoSIRE.objects.get(empresa=self.empresa, anio=2026, mes=9, registro="RVIE")
        self.assertEqual(estado.estado, "PROPUESTA")
        self.assertEqual(estado.propuesta_actual.filas, 0)

    def test_una_fila_de_otro_ruc_sigue_rechazada(self):
        fila = [
            "20100000001",
            "OTRO",
            "202609",
            "01",
            "E001",
            "1",
            "",
            "6",
            "20100000001",
            "30/09/2026",
            "0",
            "100",
            "0",
            "18",
            "0",
            "118",
            "PEN",
        ]
        respuesta = self.subir(csv_bytes(CABECERA_RVIE, [fila], delimitador="|"))

        self.assertContains(respuesta, "RUC del archivo no corresponde")
        self.assertFalse(EstadoSIRE.objects.filter(registro="RVIE").exists())

    def test_un_archivo_de_cero_bytes_sigue_siendo_ilegible(self):
        respuesta = self.subir(b"")

        self.assertContains(respuesta, "vacío")
        self.assertFalse(EstadoSIRE.objects.exists())

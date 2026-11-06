"""Lectura de la propuesta del SIRE en Excel y CSV."""

from __future__ import annotations

import io
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from openpyxl import Workbook

from reportes.sire import ArchivoInvalido, leer_filas, sumar, validar_contexto
from reportes.views import conciliacion_archivo


class Archivo:
    def __init__(self, nombre: str, contenido: bytes):
        self.name = nombre
        self._contenido = contenido

    def read(self):
        return self._contenido


class ConciliacionContextoTest(SimpleTestCase):
    def test_propuesta_de_otro_mes_no_se_compara(self):
        archivo = SimpleUploadedFile(
            "rce.csv",
            b"RUC,Periodo,BI Gravada,IGV,Importe Total\n20123456789,202610,100,18,118\n",
        )
        solicitud = RequestFactory().post(
            "/reportes/conciliacion/", {"anio": "2026", "mes": "9", "registro": "compras", "archivo": archivo}
        )
        solicitud.user = SimpleNamespace(is_authenticated=True)
        with (
            patch("reportes.views.empresa_actual", return_value=SimpleNamespace(ruc="20123456789")),
            patch("reportes.views.calcular") as calcular_reporte,
            patch("reportes.views.render", return_value=HttpResponse()) as renderizar,
        ):
            conciliacion_archivo(solicitud)
        self.assertIn("período", renderizar.call_args.args[2]["error"])
        calcular_reporte.assert_not_called()


CSV = """Reporte: PROPUESTA RCE
Periodo: 09/2026
Nro;Tipo CP;Serie;Numero;Fecha;BI Gravada;IGV;Importe Total
1;01;F001;123;01/09/2026;595,76;107,24;703,00
2;01;F001;124;05/09/2026;169,49;30,51;200,00
Total;;;;;;765,25;137,75;903,00
"""


class SireCsvTest(SimpleTestCase):
    def test_verifica_ruc_y_periodo_de_la_propuesta(self):
        contenido = (
            "RUC,Periodo,BI Gravado DG,IGV / IPM DG,Total CP\n"
            "20123456789,202610,100.00,18.00,118.00\n"
        )
        filas = leer_filas(Archivo("rce.csv", contenido.encode("utf-8")))
        self.assertEqual(
            validar_contexto(filas, ruc="20123456789", anio=2026, mes=10),
            {"ruc": True, "periodo": True},
        )
        with self.assertRaisesRegex(ArchivoInvalido, "período"):
            validar_contexto(filas, ruc="20123456789", anio=2026, mes=9)
        with self.assertRaisesRegex(ArchivoInvalido, "RUC"):
            validar_contexto(filas, ruc="20999999999", anio=2026, mes=10)

    def test_una_fila_sin_periodo_no_se_da_por_verificada(self):
        contenido = (
            "RUC,Periodo,BI Gravada,IGV,Importe Total\n"
            "20123456789,202610,100,18,118\n"
            "20123456789,,100,18,118\n"
        )
        filas = leer_filas(Archivo("rce.csv", contenido.encode("utf-8")))
        self.assertEqual(
            validar_contexto(filas, ruc="20123456789", anio=2026, mes=10),
            {"ruc": True, "periodo": False},
        )

    def test_sin_datos_de_empresa_o_periodo_no_los_da_por_verificados(self):
        filas = leer_filas(Archivo("rce.csv", CSV.encode("utf-8")))
        self.assertEqual(
            validar_contexto(filas, ruc="20123456789", anio=2026, mes=9),
            {"ruc": False, "periodo": False},
        )

    def test_razon_social_con_total_no_descarta_un_comprobante(self):
        contenido = (
            "RUC,Razón Social,Periodo,BI Gravada,IGV,Importe Total\n"
            "20123456789,Total Market SAC,202610,100.00,18.00,118.00\n"
        )
        filas = leer_filas(Archivo("rce.csv", contenido.encode("utf-8")))
        self.assertEqual(sumar(filas)["total"], Decimal("118"))
        self.assertTrue(validar_contexto(filas, ruc="20123456789", anio=2026, mes=10)["ruc"])

    def test_separador_no_depende_de_cantidad_de_comas_decimales(self):
        contenido = (
            "BI Gravada;IGV;Importe Total\n"
            "10,00;1,80;11,80\n"
            "20,00;3,60;23,60\n"
            "30,00;5,40;35,40\n"
        )
        resultado = sumar(leer_filas(Archivo("rce.csv", contenido.encode("utf-8"))))
        self.assertEqual(resultado["base"], Decimal("60.00"))
        self.assertEqual(resultado["igv"], Decimal("10.80"))

    def test_rechaza_importes_invalidos_en_lugar_de_silenciarlos(self):
        for valor in ("incorrecto", "NaN", "Infinity"):
            contenido = f"BI Gravada;IGV;Importe Total\n100,00;{valor};118,00\n"
            with self.subTest(valor=valor), self.assertRaises(ArchivoInvalido):
                sumar(leer_filas(Archivo("rce.csv", contenido.encode("utf-8"))))

    def test_no_confunde_credito_mixto_con_compra_gravada_ordinaria(self):
        cabecera = (
            "BI Gravado DG,IGV / IPM DG,BI Gravado DGNG,IGV / IPM DGNG,"
            "BI Gravado DNG,IGV / IPM DNG,Total CP\n"
        )
        for fila in ("0,0,100,18,0,0,118\n", "0,0,0,0,100,18,118\n"):
            with self.subTest(fila=fila), self.assertRaisesRegex(ArchivoInvalido, "mixtas"):
                sumar(leer_filas(Archivo("rce.csv", (cabecera + fila).encode("utf-8"))))

    def test_cabecera_propuesta_rce_con_adquisiciones_no_gravadas(self):
        contenido = (
            "Periodo,BI Gravado DG,IGV / IPM DG,BI Gravado DGNG,"
            "IGV / IPM DGNG,BI Gravado DNG,IGV / IPM DNG,Valor Adq. NG,Total CP\n"
            "202610,0.00,0.00,0.00,0.00,0.00,0.00,15.00,15.00\n"
        )
        totales = sumar(leer_filas(Archivo("rce.csv", contenido.encode("utf-8"))))
        self.assertEqual(totales["filas"], 1)
        self.assertEqual(totales["base"], Decimal("0.00"))
        self.assertEqual(totales["igv"], Decimal("0.00"))
        self.assertEqual(totales["total"], Decimal("15.00"))

    def test_importes_con_ambos_formatos_de_miles(self):
        contenido = (
            'Nro;BI Gravada;IGV;Importe Total\n'
            '1;1.234,56;222,22;1.456,78\n'
            '2;1,234.56;222.22;1,456.78\n'
        )
        totales = sumar(leer_filas(Archivo("rce.csv", contenido.encode("utf-8"))))
        self.assertEqual(totales["base"], Decimal("2469.12"))
        self.assertEqual(totales["igv"], Decimal("444.44"))
        self.assertEqual(totales["total"], Decimal("2913.56"))

    def test_detecta_columnas_y_suma(self):
        totales = sumar(leer_filas(Archivo("rce.csv", CSV.encode("utf-8-sig"))))
        self.assertEqual(totales["filas"], 2)
        self.assertEqual(totales["base"], Decimal("765.25"))
        self.assertEqual(totales["igv"], Decimal("137.75"))
        self.assertEqual(totales["total"], Decimal("903.00"))

    def test_omite_la_fila_de_totales(self):
        totales = sumar(leer_filas(Archivo("rce.csv", CSV.encode("utf-8-sig"))))
        self.assertEqual(totales["base"], Decimal("765.25"))

    def test_expone_los_titulos_originales(self):
        totales = sumar(leer_filas(Archivo("rce.csv", CSV.encode("utf-8-sig"))))
        self.assertEqual(
            totales["columnas"], ["BI Gravada", "IGV", "Importe Total"]
        )

    def test_sin_cabecera_lanza_error(self):
        with self.assertRaises(ArchivoInvalido):
            sumar(leer_filas(Archivo("malo.csv", b"hola;mundo\n1;2\n")))

    def test_formato_desconocido(self):
        with self.assertRaises(ArchivoInvalido):
            leer_filas(Archivo("propuesta.pdf", b"%PDF-1.4"))


class SireExcelTest(SimpleTestCase):
    def archivo(self):
        libro = Workbook()
        hoja = libro.active
        hoja.append(["PROPUESTA RVIE"])
        hoja.append(
            ["Nro", "Tipo CP", "Base Imponible", "IGV", "Importe Total"]
        )
        hoja.append([1, "01", 300.00, 54.00, 354.00])
        hoja.append([2, "07", -100.00, -18.00, -118.00])
        hoja.append(["Total", None, 200.00, 36.00, 236.00])
        buffer = io.BytesIO()
        libro.save(buffer)
        return buffer.getvalue()

    def test_suma_y_respeta_notas_negativas(self):
        totales = sumar(leer_filas(Archivo("rvie.xlsx", self.archivo())))
        self.assertEqual(totales["filas"], 2)
        self.assertEqual(totales["base"], Decimal("200"))
        self.assertEqual(totales["igv"], Decimal("36"))

    def test_excluye_columnas_no_gravadas(self):
        libro = Workbook()
        hoja = libro.active
        hoja.append(
            [
                "Base Imponible",
                "IGV",
                "Importe Total",
                "Base No Gravada",
            ]
        )
        hoja.append([100.00, 18.00, 118.00, 50.00])
        buffer = io.BytesIO()
        libro.save(buffer)

        totales = sumar(leer_filas(Archivo("rce.xlsx", buffer.getvalue())))
        self.assertEqual(totales["base"], Decimal("100"))
        self.assertEqual(totales["igv"], Decimal("18"))

    def test_suma_el_descuento_de_notas_de_credito_de_otro_periodo(self):
        contenido = (
            "Nro;Tipo CP;BI Gravada;IGV;Importe Total;Dscto BI;Dscto IGV\n"
            "1;01;100,00;18,00;118,00;0,00;0,00\n"
            "2;07;0,00;0,00;-59,00;-50,00;-9,00\n"
        )
        totales = sumar(leer_filas(Archivo("rvie.csv", contenido.encode("utf-8"))))

        self.assertEqual(totales["base"], Decimal("50.00"))
        self.assertEqual(totales["igv"], Decimal("9.00"))
        self.assertEqual(totales["total"], Decimal("59.00"))

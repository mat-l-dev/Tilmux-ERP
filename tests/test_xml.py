"""Lectura de comprobantes y guías de SUNAT."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase

from documentos.xml_cpe import Guia, XMLInvalido, leer

FIXTURES = Path(__file__).parent / "fixtures"


class LecturaDeComprobante(SimpleTestCase):
    def test_lee_la_boleta_de_mercado_libre(self):
        comprobante = leer((FIXTURES / "boleta_ml.xml").read_bytes())

        self.assertEqual(comprobante.tipo, "BOLETA")
        self.assertEqual(comprobante.serie, "B001")
        self.assertEqual(comprobante.numero, "00393302")
        self.assertEqual(comprobante.documento, "B001-00393302")
        self.assertEqual(comprobante.fecha, date(2026, 10, 31))
        self.assertEqual(comprobante.moneda, "PEN")
        self.assertEqual(comprobante.emisor_ruc, "20605980008")
        self.assertEqual(comprobante.receptor_ruc, "20615841961")

    def test_la_boleta_trae_base_e_igv_separados(self):
        comprobante = leer((FIXTURES / "boleta_ml.xml").read_bytes())

        self.assertEqual(comprobante.base, Decimal("167.83"))
        self.assertEqual(comprobante.igv, Decimal("30.21"))
        self.assertEqual(comprobante.total, Decimal("198.04"))
        self.assertEqual(comprobante.base + comprobante.igv, comprobante.total)

    def test_lee_las_lineas(self):
        comprobante = leer((FIXTURES / "boleta_ml.xml").read_bytes())

        self.assertEqual(len(comprobante.lineas), 2)
        self.assertEqual(
            sum((linea.base for linea in comprobante.lineas), Decimal("0.00")),
            comprobante.base,
        )


class LecturaDeGuia(SimpleTestCase):
    def test_lee_la_guia_de_remision(self):
        guia = leer((FIXTURES / "guia_remision.xml").read_bytes())

        self.assertIsInstance(guia, Guia)
        self.assertEqual(guia.tipo, "GRE_REMITENTE")
        self.assertEqual(guia.documento, "EG07-2")
        self.assertEqual(guia.fecha, date(2026, 10, 29))
        self.assertEqual(guia.remitente_ruc, "20615841961")
        self.assertEqual(guia.destinatario_ruc, "20614892405")
        self.assertEqual(guia.documento_referencia, "E001-2")
        self.assertEqual(guia.lineas, 1)

    def test_lee_el_peso(self):
        guia = leer((FIXTURES / "guia_remision.xml").read_bytes())

        self.assertEqual(guia.peso_bruto, Decimal("2.700"))


class ArchivosInvalidos(SimpleTestCase):
    def test_importe_no_finito_es_invalido(self):
        xml = (FIXTURES / "boleta_ml.xml").read_bytes().replace(b"198.04", b"NaN")
        with self.assertRaises(XMLInvalido):
            leer(xml)

    def test_un_archivo_que_no_es_xml_falla_claramente(self):
        with self.assertRaises(XMLInvalido):
            leer(b"esto no es un xml")

    def test_un_xml_desconocido_falla_claramente(self):
        with self.assertRaises(XMLInvalido):
            leer(b"<?xml version='1.0'?><Otro><Dato>1</Dato></Otro>")

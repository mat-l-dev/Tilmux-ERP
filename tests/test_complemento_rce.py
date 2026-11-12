import tempfile
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from contabilidad.models import Asiento
from reportes.casillas import calcular
from reportes.complementos import (
    car_sunat,
    compras_no_gravadas,
    registrar_complemento,
)
from reportes.estados_sire import SireError, estado_de, registrar_propuesta
from reportes.models import AjusteSIRE
from tesoreria.models import MovimientoTesoreria

from .test_invariantes import BaseContable

settings.MEDIA_ROOT = tempfile.mkdtemp(prefix="tilmux-complemento-")

RUC_MERCADOLIBRE = "20605980008"
BOBEDA = {
    "tipo_doc": "03",
    "serie": "B001",
    "numero": "00393302",
    "ruc_emisor": RUC_MERCADOLIBRE,
    "razon_social": "MERCADOLIBRE PERU S.R.L.",
    "fecha": date(2026, 10, 31),
    "total": Decimal("198.04"),
    "clasif_tabla23": "5",
    "motivo": "Comisiones y envío de Mercado Libre de octubre, no incluidos en la propuesta.",
}


class CarSunatTest(TestCase):
    def test_genera_el_car_de_27_caracteres_de_la_boleta_de_octubre(self):
        car = car_sunat(ruc=RUC_MERCADOLIBRE, tipo_doc="03", serie="B001", numero="00393302")

        self.assertEqual(car, "2060598000803B0010000393302")
        self.assertEqual(len(car), 27)

    def test_rechaza_ruc_serie_o_numero_invalidos(self):
        with self.assertRaisesMessage(SireError, "RUC"):
            car_sunat(ruc="2060598", tipo_doc="03", serie="B001", numero="1")
        with self.assertRaisesMessage(SireError, "serie"):
            car_sunat(ruc=RUC_MERCADOLIBRE, tipo_doc="03", serie="B01", numero="1")
        with self.assertRaisesMessage(SireError, "número"):
            car_sunat(ruc=RUC_MERCADOLIBRE, tipo_doc="03", serie="B001", numero="12345678901")


class ComplementoRCETest(BaseContable):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username="complemento", password="test")
        self.client.force_login(self.usuario)
        registrar_propuesta(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            registro="RCE",
            archivo=SimpleUploadedFile("rce-octubre.csv", b"propuesta"),
            filas=3,
            base=Decimal("0"),
            igv=Decimal("0"),
            total=Decimal("43.00"),
            usuario=self.usuario,
        )

    def registrar(self, **cambios):
        datos = {**BOBEDA, **cambios}
        return registrar_complemento(empresa=self.empresa, anio=2026, mes=10, usuario=self.usuario, **datos)

    def test_guarda_el_complemento_no_gravado_con_su_car(self):
        ajuste = self.registrar()

        self.assertEqual(ajuste.car, "2060598000803B0010000393302")
        self.assertEqual(ajuste.no_gravado, Decimal("198.04"))
        self.assertEqual(ajuste.base, Decimal("0"))
        self.assertEqual(ajuste.igv, Decimal("0"))
        self.assertEqual(ajuste.total, Decimal("198.04"))
        self.assertEqual(ajuste.documento, "B001-00393302")
        self.assertEqual(ajuste.tipo_doc, "03")
        self.assertEqual(ajuste.moneda, "PEN")
        self.assertEqual(ajuste.tipo_cambio, Decimal("0.000"))
        self.assertEqual(ajuste.fecha_vencimiento, date(2026, 10, 31))
        self.assertEqual(ajuste.clasif_tabla23, "5")
        self.assertEqual(ajuste.anio_documento, "")
        self.assertEqual(ajuste.numero_final, "")

    def test_rechaza_base_gravada_e_igv_de_una_boleta(self):
        with self.assertRaisesMessage(SireError, "no tiene base gravada"):
            self.registrar(base=Decimal("167.83"))
        with self.assertRaisesMessage(SireError, "no tiene base gravada"):
            self.registrar(igv=Decimal("30.21"))
        self.assertFalse(AjusteSIRE.objects.exists())

    def test_rechaza_comprobantes_que_no_son_boleta(self):
        with self.assertRaisesMessage(SireError, "boletas"):
            self.registrar(tipo_doc="01")
        self.assertFalse(AjusteSIRE.objects.exists())

    def test_rechaza_duplicado_por_car_y_fecha_de_otro_periodo(self):
        self.registrar()

        with self.assertRaisesMessage(SireError, "ya está complementado"):
            self.registrar()
        with self.assertRaisesMessage(SireError, "período"):
            self.registrar(numero="00393303", fecha=date(2026, 9, 30))
        self.assertEqual(AjusteSIRE.objects.count(), 1)

    def test_estado_complementada_y_casilla_120_con_241_04(self):
        antes = compras_no_gravadas(empresa=self.empresa, anio=2026, mes=10)
        self.assertEqual(antes["propuesta"], Decimal("43.00"))
        self.assertEqual(antes["complementos"], Decimal("0"))
        self.assertEqual(antes["total"], Decimal("43.00"))

        self.registrar()

        estado = estado_de(self.empresa, 2026, 10, "RCE")
        despues = compras_no_gravadas(empresa=self.empresa, anio=2026, mes=10)
        self.assertEqual(estado.estado, "COMPLEMENTADA")
        self.assertFalse(estado.cerrado)
        self.assertEqual(despues["propuesta"], Decimal("43.00"))
        self.assertEqual(despues["complementos"], Decimal("198.04"))
        self.assertEqual(despues["total"], Decimal("241.04"))

    def test_no_mueve_igv_renta_ni_registra_asientos_o_movimientos(self):
        claves = (
            "ventas_base",
            "ventas_igv",
            "compras_base",
            "compras_igv",
            "no_gravado",
            "base_renta",
            "renta",
            "resultado",
        )
        antes = {clave: calcular(self.empresa, 2026, 10)[clave] for clave in claves}
        asientos_antes = Asiento.objects.count()
        movimientos_antes = MovimientoTesoreria.objects.count()

        self.registrar()

        despues = {clave: calcular(self.empresa, 2026, 10)[clave] for clave in claves}
        self.assertEqual(despues, antes)
        self.assertEqual(Asiento.objects.count(), asientos_antes)
        self.assertEqual(MovimientoTesoreria.objects.count(), movimientos_antes)

    def test_la_pantalla_registra_el_complemento_y_muestra_el_car(self):
        url = reverse("reportes:complemento_rce")
        pagina = self.client.get(url, {"anio": 2026, "mes": 10})
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "casilla 120")

        respuesta = self.client.post(
            url,
            {
                "anio": "2026",
                "mes": "10",
                "tipo_doc": "03",
                "ruc_emisor": RUC_MERCADOLIBRE,
                "razon_social": "MERCADOLIBRE PERU S.R.L.",
                "serie": "B001",
                "numero": "00393302",
                "fecha": "2026-10-31",
                "total": "198.04",
                "clasif_tabla23": "5",
                "motivo": BOBEDA["motivo"],
            },
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(estado_de(self.empresa, 2026, 10, "RCE").estado, "COMPLEMENTADA")
        self.assertContains(respuesta, "2060598000803B0010000393302")
        self.assertContains(respuesta, "241,04")
        self.assertContains(respuesta, "198,04")

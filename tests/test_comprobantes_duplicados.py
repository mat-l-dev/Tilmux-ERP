"""Un comprobante del proveedor no debe contabilizarse dos veces."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo.models import CuentaTesoreria, Tercero
from compras.comprobantes import buscar_comprobante
from compras.models import Compra
from compras.models_gasto import Gasto
from compras.servicios import CompraError, confirmar, registrar_gasto
from contabilidad.models import Cuenta
from core.models import Empresa, Perfil


class ComprobantesDuplicadosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="Prueba", razon_social="Prueba SAC", ruc="20123456789")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cls.cuenta = Cuenta.objects.create(
            codigo="6391", nombre="Gastos", elemento=6, naturaleza="D", activa=True, admite_movimiento=True
        )
        cls.medio = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco", cuenta_contable=cls.cuenta)

    def test_no_confirmar_compra_ya_registrada_como_gasto(self):
        Gasto.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            cuenta=self.cuenta,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="000123",
        )
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="f001",
            numero="123",
        )
        with self.assertRaisesRegex(CompraError, "registrad"):
            confirmar(compra)

    def test_no_registrar_gasto_ya_confirmado_como_compra(self):
        Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="00123",
            estado=Compra.Estado.CONFIRMADA,
        )
        with self.assertRaisesRegex(CompraError, "registrad"):
            registrar_gasto(
                empresa=self.empresa,
                proveedor=self.proveedor,
                fecha=date(2026, 10, 1),
                tipo_doc="FACTURA",
                serie="F001",
                numero="123",
                base=Decimal("10"),
                igv=Decimal("0"),
                total=Decimal("10"),
                cuenta=self.cuenta,
                medio=self.medio,
            )

    def test_detecta_compra_previa_y_respeta_el_proveedor(self):
        Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="0007",
            estado=Compra.Estado.CONFIRMADA,
        )
        otra = Tercero.objects.create(nombre="Otro", tipo_doc="RUC", numero_doc="20100000002")
        datos = {"empresa": self.empresa, "tipo_doc": "FACTURA", "serie": "f001", "numero": "7"}
        self.assertEqual(buscar_comprobante(proveedor=self.proveedor, **datos), "compra")
        self.assertIsNone(buscar_comprobante(proveedor=otra, **datos))

    def test_provision_no_cuenta_como_factura_ya_recibida(self):
        Gasto.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            cuenta=self.cuenta,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="7",
            provision=True,
            estado=Gasto.Estado.PROVISION,
        )
        self.assertIsNone(
            buscar_comprobante(
                empresa=self.empresa, proveedor=self.proveedor, tipo_doc="FACTURA", serie="F001", numero="7"
            )
        )
        with patch("compras.servicios.postear"), patch("compras.servicios.anotar"):
            factura = registrar_gasto(
                empresa=self.empresa,
                proveedor=self.proveedor,
                fecha=date(2026, 10, 2),
                tipo_doc="FACTURA",
                serie="F001",
                numero="7",
                base=Decimal("10"),
                igv=Decimal("0"),
                total=Decimal("10"),
                cuenta=self.cuenta,
                medio=self.medio,
            )
        self.assertFalse(factura.provision)

    def test_corregir_compra_no_admite_comprobante_de_otro_gasto(self):
        Gasto.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            cuenta=self.cuenta,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="0007",
        )
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="",
            numero="",
            estado=Compra.Estado.CONFIRMADA,
        )
        usuario = get_user_model().objects.create_user(username="revisor")
        Perfil.objects.create(usuario=usuario, empresa=self.empresa)
        self.client.force_login(usuario)
        respuesta = self.client.post(
            reverse("compras:corregir", args=[compra.pk]),
            {"tipo_doc": "FACTURA", "serie": "F001", "numero": "7", "glosa": "Intento"},
        )
        self.assertEqual(respuesta.status_code, 302)
        compra.refresh_from_db()
        self.assertEqual(compra.serie, "")
        self.assertEqual(compra.numero, "")

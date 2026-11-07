from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from catalogo.models import CuentaTesoreria, Tercero
from compras.models_gasto import Gasto
from compras.servicios import CompraError, registrar_gasto
from contabilidad.models import Asiento, Cuenta
from core.models import Empresa
from tesoreria.models import MovimientoTesoreria


class ValidacionGastoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        cls.proveedor = Tercero.objects.create(nombre="Proveedor", tipo_doc="RUC", numero_doc="20100000001")
        cls.cuenta = Cuenta.objects.create(
            codigo="6391", nombre="Gasto", elemento=6, naturaleza="D", activa=True, admite_movimiento=True
        )
        cls.medio = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Banco", cuenta_contable=cls.cuenta)
        cls.ajeno = CuentaTesoreria.objects.create(empresa=cls.otra, nombre="Banco", cuenta_contable=cls.cuenta)

    def datos(self):
        return dict(
            empresa=self.empresa,
            proveedor=self.proveedor,
            fecha=date(2026, 10, 1),
            tipo_doc="FACTURA",
            serie="F001",
            numero="1",
            base=Decimal("100"),
            igv=Decimal("18"),
            total=Decimal("118"),
            cuenta=self.cuenta,
            medio=self.medio,
            con_credito=True,
        )

    def test_rechaza_importes_invalidos_sin_crear_movimientos(self):
        for valores in (
            {"base": "-1", "igv": "2", "total": "1"},
            {"base": "0", "igv": "18", "total": "18"},
            {"base": "1", "igv": "-1", "total": "0"},
            {"base": "NaN"},
            {"base": "Infinity"},
            {"total": "0"},
        ):
            with self.subTest(valores=valores), self.assertRaises(CompraError):
                registrar_gasto(**(self.datos() | valores))
        self.assertFalse(Gasto.objects.exists())
        self.assertFalse(Asiento.objects.exists())
        self.assertFalse(MovimientoTesoreria.objects.exists())

    def test_rechaza_cuenta_ajena_inactiva_distinta_moneda_o_sin_contabilidad(self):
        otros = [
            self.ajeno,
            CuentaTesoreria.objects.create(
                empresa=self.empresa, nombre="Inactiva", activa=False, cuenta_contable=self.cuenta
            ),
            CuentaTesoreria.objects.create(
                empresa=self.empresa, nombre="Dólares", moneda="USD", cuenta_contable=self.cuenta
            ),
            CuentaTesoreria.objects.create(empresa=self.empresa, nombre="Sin contabilidad"),
        ]
        for medio in otros:
            with self.subTest(medio=medio.nombre), self.assertRaisesMessage(CompraError, "tesorería activa"):
                registrar_gasto(**(self.datos() | {"medio": medio}))
        self.assertFalse(Gasto.objects.exists())

    def test_rechaza_cuentas_y_estados_incompatibles(self):
        self.cuenta.activa = False
        self.cuenta.save(update_fields=["activa"])
        with self.assertRaisesMessage(CompraError, "cuenta de gasto activa"):
            registrar_gasto(**self.datos())
        self.cuenta.activa = True
        self.cuenta.save(update_fields=["activa"])
        with self.assertRaisesMessage(CompraError, "estado del gasto"):
            registrar_gasto(**(self.datos() | {"estado": Gasto.Estado.ANULADO}))
        with self.assertRaisesMessage(CompraError, "provisión no debe indicar"):
            registrar_gasto(**(self.datos() | {"provision": True}))
        self.assertFalse(Gasto.objects.exists())

    def test_acepta_una_operacion_valida(self):
        with patch("compras.servicios.postear"), patch("compras.servicios.anotar"):
            gasto = registrar_gasto(**self.datos())
        self.assertEqual(gasto.estado, Gasto.Estado.PAGADO)
        self.assertEqual(gasto.total, Decimal("118"))

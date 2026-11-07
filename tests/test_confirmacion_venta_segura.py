from datetime import date
from decimal import Decimal

from django.test import TestCase

from catalogo.models import CuentaTesoreria, Producto, UnidadMedida
from contabilidad.models import Asiento, Cuenta
from core.models import Empresa
from inventario.models import MovimientoStock
from tesoreria.models import MovimientoTesoreria
from ventas.models import Venta, VentaLinea
from ventas.servicios import VentaError, confirmar


class ConfirmacionVentaSeguraTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(nombre="A", razon_social="A", ruc="20123456789")
        cls.otra = Empresa.objects.create(nombre="B", razon_social="B", ruc="20123456780")
        unidad = UnidadMedida.objects.create(codigo="NIU", nombre="Unidad")
        cls.producto = Producto.objects.create(sku="TEST", nombre="Producto", unidad=unidad)
        cuenta_contable = Cuenta.objects.create(codigo="1011", nombre="Caja", elemento=1, naturaleza="D")
        cls.cuenta = CuentaTesoreria.objects.create(
            empresa=cls.empresa, nombre="Banco", cuenta_contable=cuenta_contable
        )
        cls.ajena = CuentaTesoreria.objects.create(empresa=cls.otra, nombre="Ajena", cuenta_contable=cuenta_contable)
        cls.sin_contabilidad = CuentaTesoreria.objects.create(empresa=cls.empresa, nombre="Sin contabilidad")

    def setUp(self):
        self.venta = Venta.objects.create(
            empresa=self.empresa,
            fecha=date(2026, 11, 1),
            tipo_doc="BOLETA",
            serie="B001",
            numero="1",
            condicion="CONTADO",
            cuenta=self.cuenta,
            canal="TRANSFERENCIA",
        )
        self.linea = VentaLinea.objects.create(
            venta=self.venta,
            producto=self.producto,
            cantidad=1,
            precio_unitario=100,
            base=100,
            igv=18,
            total=118,
        )

    def assert_sin_operaciones(self):
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.estado, Venta.Estado.BORRADOR)
        self.assertFalse(MovimientoStock.objects.exists())
        self.assertFalse(MovimientoTesoreria.objects.exists())
        self.assertFalse(Asiento.objects.exists())

    def test_no_acepta_cuentas_de_otra_empresa_inactivas_o_sin_contabilidad(self):
        self.cuenta.activa = False
        self.cuenta.save(update_fields=["activa"])
        for cuenta in (self.cuenta, self.ajena, self.sin_contabilidad):
            self.venta.cuenta = cuenta
            self.venta.save(update_fields=["cuenta"])
            with self.subTest(cuenta=cuenta.nombre), self.assertRaisesMessage(VentaError, "tesorería activa"):
                confirmar(self.venta)
        self.assert_sin_operaciones()

    def test_rechaza_moneda_canal_y_condicion_invalidos(self):
        for campo, valor in (("moneda", "USD"), ("canal", "INVALIDO"), ("condicion", "OTRO")):
            anterior = getattr(self.venta, campo)
            setattr(self.venta, campo, valor)
            self.venta.save(update_fields=[campo])
            with self.subTest(campo=campo), self.assertRaises(VentaError):
                confirmar(self.venta)
            setattr(self.venta, campo, anterior)
            self.venta.save(update_fields=[campo])
        self.assert_sin_operaciones()

    def test_rechaza_lineas_inconsistentes(self):
        self.linea.total = Decimal("119")
        self.linea.save(update_fields=["total"])
        with self.assertRaisesMessage(VentaError, "Revisa las líneas"):
            confirmar(self.venta)
        self.assert_sin_operaciones()

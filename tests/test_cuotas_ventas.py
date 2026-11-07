from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from ventas.models import Venta, VentaLinea
from ventas.servicios import VentaError, confirmar
from ventas.servicios_cuotas import guardar_cuotas

from .test_invariantes import BaseContable


class CuotasVentaTest(BaseContable):
    def setUp(self):
        self.comprar("2", "50")
        self.venta = Venta.objects.create(
            empresa=self.empresa, cliente=self.cliente, fecha=date(2026, 11, 20),
            tipo_doc="FACTURA", serie="E001", numero="1", condicion="CREDITO",
        )
        VentaLinea.objects.create(
            venta=self.venta, producto=self.producto, cantidad=1, precio_unitario=118,
            base=100, igv=18, total=118,
        )

    def test_confirma_solo_con_cuotas_validas_y_cubre_total(self):
        with self.assertRaisesMessage(VentaError, "al menos una cuota"):
            confirmar(self.venta)
        cuotas = [
            {"vencimiento": date(2026, 12, 1), "importe": Decimal("50.00")},
            {"vencimiento": date(2027, 1, 1), "importe": Decimal("68.00")},
        ]
        guardar_cuotas(venta=self.venta, cuotas=cuotas)
        confirmar(self.venta)
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.estado, Venta.Estado.CONFIRMADA)
        self.assertEqual(list(self.venta.cuotas.values_list("importe", flat=True)), [Decimal("50"), Decimal("68")])
        with self.assertRaises(VentaError):
            guardar_cuotas(venta=self.venta, cuotas=cuotas)

    def test_rechaza_sumatoria_y_fecha_invalidas_sin_borrar_cuotas_existentes(self):
        correcta = [{"vencimiento": date(2026, 12, 1), "importe": Decimal("118")}]
        guardar_cuotas(venta=self.venta, cuotas=correcta)
        for invalida in (
            [{"vencimiento": date(2026, 12, 1), "importe": Decimal("100")}],
            [{"vencimiento": date(2026, 11, 19), "importe": Decimal("118")}],
            [{"vencimiento": date(2026, 11, 20), "importe": Decimal("118")}],
        ):
            with self.assertRaises(VentaError):
                guardar_cuotas(venta=self.venta, cuotas=invalida)
        self.assertEqual(self.venta.cuotas.get().importe, Decimal("118"))

    def test_formulario_guarda_varias_cuotas(self):
        user = get_user_model().objects.create_superuser(username="cuotas", password="test")
        self.client.force_login(user)
        url = reverse("ventas:cuotas", args=[self.venta.pk])
        response = self.client.post(url, {
            "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "0", "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "100", "form-0-vencimiento": "2026-12-01", "form-0-importe": "50.00",
            "form-1-vencimiento": "2027-01-01", "form-1-importe": "68.00",
        })
        self.assertRedirects(response, reverse("ventas:detalle", args=[self.venta.pk]))
        self.assertEqual(self.venta.cuotas.count(), 2)

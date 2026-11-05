"""Compras de mercadería con costos de internamiento."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Compra(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        ANULADA = "ANULADA", "Anulada"

    class TipoDoc(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        BOLETA = "BOLETA", "Boleta"
        OTRO = "OTRO", "Otro documento"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="compras"
    )
    proveedor = models.ForeignKey(
        "catalogo.Tercero",
        on_delete=models.PROTECT,
        related_name="compras",
        limit_choices_to={"rol__in": ["PROVEEDOR", "AMBOS"]},
    )
    fecha = models.DateField()
    tipo_doc = models.CharField(
        max_length=8, choices=TipoDoc.choices, default=TipoDoc.FACTURA
    )
    serie = models.CharField(max_length=4, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    moneda = models.CharField(max_length=3, default="PEN")
    tipo_cambio = models.DecimalField(max_digits=12, decimal_places=6, default=1)
    glosa = models.CharField(max_length=255, blank=True)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.BORRADOR
    )
    con_credito = models.BooleanField(
        default=True,
        help_text="Una boleta no otorga crédito: su IGV forma parte del costo.",
    )
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_moneda_origen = models.DecimalField(
        max_digits=18, decimal_places=2, default=0
    )
    revaluacion = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    pagada = models.BooleanField(default=False)
    fecha_pago = models.DateField(null=True, blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compras",
    )
    creado = models.DateTimeField(auto_now_add=True)
    confirmado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "compra"
        verbose_name_plural = "compras"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["empresa", "fecha"])]

    def __str__(self) -> str:
        return f"{self.fecha} · {self.proveedor.nombre} · {self.total}"


class CompraLinea(models.Model):
    compra = models.ForeignKey(
        Compra, on_delete=models.CASCADE, related_name="lineas"
    )
    orden = models.PositiveSmallIntegerField(default=1)
    producto = models.ForeignKey(
        "catalogo.Producto", on_delete=models.PROTECT, related_name="compras"
    )
    descripcion = models.CharField(max_length=200, blank=True)
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    costo_unitario_final = models.DecimalField(
        max_digits=24, decimal_places=10, default=0
    )

    class Meta:
        verbose_name = "línea de compra"
        verbose_name_plural = "líneas de compra"
        ordering = ["compra", "orden"]

    def __str__(self) -> str:
        return f"{self.producto.sku} × {self.cantidad}"


class CostoAdicional(models.Model):
    class Criterio(models.TextChoices):
        VALOR = "VALOR", "Por valor"
        CANTIDAD = "CANTIDAD", "Por cantidad"

    compra = models.ForeignKey(
        Compra, on_delete=models.CASCADE, related_name="costos"
    )
    concepto = models.CharField(max_length=120)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    criterio = models.CharField(
        max_length=8, choices=Criterio.choices, default=Criterio.VALOR
    )

    class Meta:
        verbose_name = "costo adicional"
        verbose_name_plural = "costos adicionales"
        ordering = ["compra", "id"]

    def __str__(self) -> str:
        return f"{self.concepto} · {self.base}"

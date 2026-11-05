"""Stock valorizado por capas PEPS.

El saldo no se guarda: se deriva de las capas y de los movimientos. Así el
inventario siempre se puede reconstruir y auditar.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models


class CapaFIFO(models.Model):
    """Entrada de mercadería con su costo unitario definitivo (landed cost)."""

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="capas"
    )
    producto = models.ForeignKey(
        "catalogo.Producto", on_delete=models.PROTECT, related_name="capas"
    )
    fecha = models.DateField()
    cantidad_inicial = models.DecimalField(max_digits=18, decimal_places=4)
    cantidad_restante = models.DecimalField(max_digits=18, decimal_places=4)
    costo_unitario = models.DecimalField(max_digits=24, decimal_places=10)
    origen_tipo = models.CharField(max_length=20, blank=True)
    origen_id = models.BigIntegerField(null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "capa PEPS"
        verbose_name_plural = "capas PEPS"
        ordering = ["fecha", "id"]
        indexes = [models.Index(fields=["empresa", "producto", "fecha"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad_restante__gte=0),
                name="capa_restante_no_negativa",
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad_inicial__gt=0),
                name="capa_inicial_positiva",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.producto.sku} · {self.cantidad_restante} @ {self.costo_unitario}"

    @property
    def valor(self) -> Decimal:
        return (self.cantidad_restante * self.costo_unitario).quantize(Decimal("0.01"))


class MovimientoStock(models.Model):
    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SALIDA = "SALIDA", "Salida"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="movimientos_stock"
    )
    producto = models.ForeignKey(
        "catalogo.Producto", on_delete=models.PROTECT, related_name="movimientos"
    )
    fecha = models.DateField()
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    costo_unitario = models.DecimalField(max_digits=24, decimal_places=10)
    costo_total = models.DecimalField(max_digits=18, decimal_places=2)
    origen_tipo = models.CharField(max_length=20, blank=True)
    origen_id = models.BigIntegerField(null=True, blank=True)
    glosa = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"
        ordering = ["fecha", "id"]
        indexes = [models.Index(fields=["empresa", "producto", "fecha"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad__gt=0), name="movimiento_cantidad_positiva"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.cantidad} {self.producto.sku}"


class ConsumoCapa(models.Model):
    """Qué capa pagó cada unidad de una salida. Es la trazabilidad del costo."""

    movimiento = models.ForeignKey(
        MovimientoStock, on_delete=models.CASCADE, related_name="consumos"
    )
    capa = models.ForeignKey(
        CapaFIFO, on_delete=models.PROTECT, related_name="consumos"
    )
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    costo_unitario = models.DecimalField(max_digits=24, decimal_places=10)
    costo_total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        verbose_name = "consumo de capa"
        verbose_name_plural = "consumos de capa"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cantidad__gt=0), name="consumo_cantidad_positiva"
            )
        ]

    def __str__(self) -> str:
        return f"{self.cantidad} de capa {self.capa_id}"

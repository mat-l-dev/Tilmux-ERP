"""Movimientos reales de dinero. El banco es la verdad; el libro la explica."""

from __future__ import annotations

from django.db import models


class MovimientoTesoreria(models.Model):
    class Tipo(models.TextChoices):
        INGRESO = "INGRESO", "Ingreso"
        EGRESO = "EGRESO", "Egreso"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="movimientos_tesoreria"
    )
    cuenta = models.ForeignKey(
        "catalogo.CuentaTesoreria",
        on_delete=models.PROTECT,
        related_name="movimientos",
    )
    fecha = models.DateField()
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    importe = models.DecimalField(max_digits=18, decimal_places=2)
    canal = models.CharField(
        max_length=15,
        choices=[
            ("TRANSFERENCIA", "Transferencia"),
            ("YAPE", "Yape"),
            ("PLIN", "Plin"),
            ("QR", "QR"),
            ("TARJETA", "Tarjeta"),
            ("EFECTIVO", "Efectivo"),
            ("OTRO", "Otro"),
        ],
        default="TRANSFERENCIA",
    )
    concepto = models.CharField(max_length=200)
    origen_tipo = models.CharField(max_length=20, blank=True)
    origen_id = models.BigIntegerField(null=True, blank=True)
    conciliado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de tesorería"
        verbose_name_plural = "movimientos de tesorería"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["empresa", "fecha"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(importe__gt=0), name="movimiento_importe_positivo"
            )
        ]

    def __str__(self) -> str:
        signo = "+" if self.tipo == self.Tipo.INGRESO else "-"
        return f"{signo}{self.importe} · {self.cuenta.nombre}"

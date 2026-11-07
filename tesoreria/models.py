"""Movimientos reales de dinero. El banco es la verdad; el libro la explica."""

from __future__ import annotations

from django.conf import settings
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


class ConciliacionBancaria(models.Model):
    """Vínculo explícito con una operación bancaria, conservado si se revierte."""

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT)
    cuenta = models.ForeignKey("catalogo.CuentaTesoreria", on_delete=models.PROTECT)
    movimiento = models.ForeignKey(MovimientoTesoreria, on_delete=models.PROTECT, related_name="conciliaciones")
    fecha_banco = models.DateField()
    tipo = models.CharField(max_length=7, choices=MovimientoTesoreria.Tipo.choices)
    importe = models.DecimalField(max_digits=18, decimal_places=2)
    referencia = models.CharField(max_length=100)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)
    activa = models.BooleanField(default=True)
    revertido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    revertido = models.DateTimeField(null=True, blank=True)
    motivo_reversion = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-creado", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["movimiento"], condition=models.Q(activa=True), name="conc_movimiento_activo",
            ),
            models.UniqueConstraint(
                fields=["empresa", "cuenta", "referencia"], condition=models.Q(activa=True),
                name="conc_referencia_activa",
            ),
            models.CheckConstraint(condition=models.Q(importe__gt=0), name="conc_importe_positivo"),
            models.CheckConstraint(condition=~models.Q(referencia=""), name="conc_referencia_no_vacia"),
        ]

    def __str__(self):
        return f"{self.cuenta.nombre} · {self.referencia}"

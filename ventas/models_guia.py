"""Guías de remisión vinculadas a su comprobante."""

from __future__ import annotations

from django.db import models


class GuiaRemision(models.Model):
    class Tipo(models.TextChoices):
        REMITENTE = "GRE_REMITENTE", "Guía de remisión remitente"
        TRANSPORTISTA = "GRE_TRANSPORTISTA", "Guía de remisión transportista"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="guias"
    )
    venta = models.ForeignKey(
        "ventas.Venta",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guias",
    )
    tipo = models.CharField(
        max_length=20, choices=Tipo.choices, default=Tipo.REMITENTE
    )
    serie = models.CharField(max_length=4)
    numero = models.CharField(max_length=20)
    fecha = models.DateField()
    remitente_ruc = models.CharField(max_length=11, blank=True)
    remitente_nombre = models.CharField(max_length=200, blank=True)
    destinatario_ruc = models.CharField(max_length=11, blank=True)
    destinatario_nombre = models.CharField(max_length=200, blank=True)
    peso_bruto = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True
    )
    bultos = models.PositiveIntegerField(null=True, blank=True)
    documento_referencia = models.CharField(max_length=30, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "guía de remisión"
        verbose_name_plural = "guías de remisión"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "serie", "numero"], name="guia_unica"
            )
        ]

    def __str__(self) -> str:
        return f"{self.serie}-{self.numero}"

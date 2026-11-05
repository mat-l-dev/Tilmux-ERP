"""Gastos con comprobante: completan el registro de compras."""

from __future__ import annotations

from django.db import models


class Gasto(models.Model):
    class TipoDoc(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        BOLETA = "BOLETA", "Boleta"
        OTRO = "OTRO", "Sin comprobante"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="gastos"
    )
    proveedor = models.ForeignKey(
        "catalogo.Tercero", on_delete=models.PROTECT, related_name="gastos"
    )
    fecha = models.DateField()
    tipo_doc = models.CharField(
        max_length=8, choices=TipoDoc.choices, default=TipoDoc.FACTURA
    )
    serie = models.CharField(max_length=4, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    cuenta = models.ForeignKey(
        "contabilidad.Cuenta", on_delete=models.PROTECT, related_name="gastos"
    )
    medio = models.ForeignKey(
        "catalogo.CuentaTesoreria",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="gastos",
    )
    glosa = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "gasto"
        verbose_name_plural = "gastos"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_doc", "serie", "numero"],
                condition=~models.Q(serie=""),
                name="gasto_comprobante_unico",
            )
        ]

    def __str__(self) -> str:
        documento = f"{self.serie}-{self.numero}".strip(" -") or "sin comprobante"
        return f"{self.fecha} · {self.proveedor.nombre} · {documento} · {self.total}"

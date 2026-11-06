"""Gastos con comprobante: completan el registro de compras."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Gasto(models.Model):
    class TipoDoc(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        BOLETA = "BOLETA", "Boleta"
        OTRO = "OTRO", "Sin comprobante"

    class Estado(models.TextChoices):
        PROVISION = "PROVISION", "Provisión"
        REGISTRADO = "REGISTRADO", "Registrado"
        PAGADO = "PAGADO", "Pagado"
        ANULADO = "ANULADO", "Anulado"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="gastos"
    )
    proveedor = models.ForeignKey(
        "catalogo.Tercero", on_delete=models.PROTECT, related_name="gastos"
    )
    fecha = models.DateField()
    fecha_anotacion = models.DateField(
        null=True, blank=True,
        help_text="Fecha de anotación en el registro de compras; si no se indica, se estima con la emisión.",
    )
    fecha_devengado = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Fecha económica del gasto, independiente de la fecha del comprobante."
        ),
    )
    tipo_doc = models.CharField(
        max_length=8, choices=TipoDoc.choices, default=TipoDoc.FACTURA
    )
    serie = models.CharField(max_length=4, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    provision = models.BooleanField(
        default=False,
        help_text=(
            "Marca una provisión: reconoce el gasto antes de recibir la factura "
            "final y no genera salida de tesorería."
        ),
    )
    gasto_origen = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="provisiones",
        help_text="Factura final que sustenta esta provisión.",
    )
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.REGISTRADO,
    )
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
    con_credito = models.BooleanField(
        default=True,
        help_text="Una boleta de venta no otorga crédito fiscal al comprador.",
    )
    deducible = models.BooleanField(
        default=True,
        help_text="Una boleta de venta tampoco sustenta gasto para efecto tributario.",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gastos",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "gasto"
        verbose_name_plural = "gastos"
        ordering = ["-fecha", "-id"]
        indexes = [
            models.Index(fields=["empresa", "fecha"]),
            models.Index(fields=["empresa", "fecha_devengado"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "proveedor", "tipo_doc", "serie", "numero"],
                condition=~models.Q(serie="") & models.Q(provision=False),
                name="gasto_comprobante_unico",
            ),
            models.CheckConstraint(
                condition=models.Q(provision=True)
                | models.Q(gasto_origen__isnull=True),
                name="gasto_origen_solo_en_provision",
            ),
        ]

    @property
    def fecha_periodo(self):
        """Fecha económica del gasto."""
        return self.fecha_devengado or self.fecha

    def __str__(self) -> str:
        documento = f"{self.serie}-{self.numero}".strip(" -") or "sin comprobante"
        return f"{self.fecha} · {self.proveedor.nombre} · {documento} · {self.total}"

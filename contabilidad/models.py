"""Catálogo de cuentas del PCGE."""

from __future__ import annotations

from django.db import models


class Cuenta(models.Model):
    """Cuenta del Plan Contable General Empresarial.

    El catálogo completo se carga desde el PCGE oficial. ``activa`` marca las
    cuentas que esta empresa realmente usa, para que el selector sea corto.
    """

    class Naturaleza(models.TextChoices):
        DEUDORA = "D", "Deudora"
        ACREEDORA = "A", "Acreedora"

    class Categoria(models.TextChoices):
        OPERACION = "OPERACION", "Operación"
        INVERSION = "INVERSION", "Inversión"
        FINANCIACION = "FINANCIACION", "Financiación"
        IMPUESTO = "IMPUESTO", "Impuesto a las ganancias"
        DISCONTINUADAS = "DISCONTINUADAS", "Operaciones discontinuadas"

    version = models.CharField(max_length=4, default="2026")
    codigo = models.CharField(max_length=6, db_index=True)
    nombre = models.CharField(max_length=255)
    padre = models.CharField(max_length=6, blank=True)
    elemento = models.PositiveSmallIntegerField()
    naturaleza = models.CharField(max_length=1, choices=Naturaleza.choices)
    admite_movimiento = models.BooleanField(default=False)
    categoria_financiera = models.CharField(
        max_length=15, choices=Categoria.choices, blank=True
    )
    activa = models.BooleanField(default=False)
    nota = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "cuenta"
        verbose_name_plural = "cuentas"
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "codigo"], name="cuenta_unica_por_version"
            )
        ]
        indexes = [models.Index(fields=["version", "activa"])]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

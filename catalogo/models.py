"""Maestros: unidades, terceros, productos, cuentas de tesorería y series."""

from __future__ import annotations

from django.db import models
from django.db.models import Q


class UnidadMedida(models.Model):
    codigo = models.CharField(max_length=3, unique=True)
    nombre = models.CharField(max_length=40)
    decimales = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "unidad de medida"
        verbose_name_plural = "unidades de medida"
        ordering = ["codigo"]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"


class Tercero(models.Model):
    class Rol(models.TextChoices):
        CLIENTE = "CLIENTE", "Cliente"
        PROVEEDOR = "PROVEEDOR", "Proveedor"
        AMBOS = "AMBOS", "Cliente y proveedor"

    class TipoDoc(models.TextChoices):
        RUC = "RUC", "RUC"
        DNI = "DNI", "DNI"
        CE = "CE", "Carné de extranjería"
        PAS = "PAS", "Pasaporte"
        SIN = "SIN", "Sin documento"

    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.CLIENTE)
    tipo_doc = models.CharField(max_length=4, choices=TipoDoc.choices, default=TipoDoc.RUC)
    numero_doc = models.CharField(max_length=11, blank=True)
    nombre = models.CharField(max_length=200)
    direccion = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tercero"
        verbose_name_plural = "terceros"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_doc", "numero_doc"],
                condition=~Q(numero_doc=""),
                name="tercero_documento_unico",
            )
        ]

    def __str__(self) -> str:
        return f"{self.nombre} · {self.numero_doc}" if self.numero_doc else self.nombre


class Producto(models.Model):
    class Tipo(models.TextChoices):
        BIEN = "BIEN", "Bien"
        SERVICIO = "SERVICIO", "Servicio"

    sku = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=200)
    unidad = models.ForeignKey(
        UnidadMedida, on_delete=models.PROTECT, related_name="productos"
    )
    tipo = models.CharField(max_length=8, choices=Tipo.choices, default=Tipo.BIEN)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["sku"]

    def __str__(self) -> str:
        return f"{self.sku} · {self.nombre}"


class CuentaTesoreria(models.Model):
    class Tipo(models.TextChoices):
        BANCO = "BANCO", "Cuenta bancaria"
        BILLETERA = "BILLETERA", "Billetera digital"
        CAJA = "CAJA", "Caja"

    class Canal(models.TextChoices):
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        YAPE = "YAPE", "Yape"
        PLIN = "PLIN", "Plin"
        QR = "QR", "QR"
        TARJETA = "TARJETA", "Tarjeta"
        EFECTIVO = "EFECTIVO", "Efectivo"
        OTRO = "OTRO", "Otro"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="cuentas_tesoreria"
    )
    nombre = models.CharField(max_length=60)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.BANCO)
    moneda = models.CharField(max_length=3, default="PEN")
    cuenta_contable = models.ForeignKey(
        "contabilidad.Cuenta",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cuentas_tesoreria",
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "cuenta de tesorería"
        verbose_name_plural = "cuentas de tesorería"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "nombre"], name="tesoreria_cuenta_unica"
            )
        ]

    def save(self, *args, **kwargs):
        # Cada banco recibe su subcuenta analítica bajo la 1061 al guardarse.
        if self.tipo == self.Tipo.BANCO:
            from tesoreria.subcuentas import SubcuentaError, subcuenta_de

            try:
                self.cuenta_contable = subcuenta_de(self)
            except SubcuentaError:
                pass
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.empresa.nombre} · {self.nombre}"


class Serie(models.Model):
    class Tipo(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        BOLETA = "BOLETA", "Boleta"
        NOTA_CREDITO = "NOTA_CREDITO", "Nota de crédito"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="series"
    )
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    serie = models.CharField(max_length=4)
    ultimo_numero = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "serie"
        verbose_name_plural = "series"
        ordering = ["empresa", "tipo", "serie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo", "serie"], name="serie_unica_por_tipo"
            )
        ]

    def __str__(self) -> str:
        return f"{self.serie} · {self.get_tipo_display()}"

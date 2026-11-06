"""Entidades base: empresa y periodo contable."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Empresa(models.Model):
    """Persona jurídica cuyos libros se llevan en el sistema."""

    class Regimen(models.TextChoices):
        RER = "RER", "Régimen Especial de Renta"
        RMT = "RMT", "Régimen MYPE Tributario"
        RG = "RG", "Régimen General"
        NRUS = "NRUS", "Nuevo RUS"

    nombre = models.CharField(max_length=120)
    razon_social = models.CharField(max_length=200)
    ruc = models.CharField(max_length=11, unique=True)
    regimen = models.CharField(
        max_length=8, choices=Regimen.choices, default=Regimen.RER
    )
    moneda = models.CharField(max_length=3, default="PEN")
    direccion = models.CharField(max_length=255, blank=True)
    activa = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} · {self.ruc}"


class Periodo(models.Model):
    """Mes contable de una empresa. Se cierra y no se reabre sin dejar rastro."""

    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Cerrado"

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="periodos"
    )
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.ABIERTO
    )
    version_pcge = models.CharField(max_length=4, default="2026")

    class Meta:
        verbose_name = "periodo"
        verbose_name_plural = "periodos"
        ordering = ["-anio", "-mes"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "anio", "mes"], name="periodo_unico_por_mes"
            ),
            models.CheckConstraint(
                condition=models.Q(mes__gte=1) & models.Q(mes__lte=12),
                name="periodo_mes_valido",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.empresa.nombre} · {self.anio}-{self.mes:02d}"

    @property
    def etiqueta(self) -> str:
        meses = (
            "enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "setiembre", "octubre", "noviembre", "diciembre",
        )
        return f"{meses[self.mes - 1].capitalize()} {self.anio}"


class TipoCambio(models.Model):
    """Tipo de cambio publicado por SUNAT. Un registro por fecha."""

    fecha = models.DateField(unique=True)
    compra = models.DecimalField(max_digits=10, decimal_places=3)
    venta = models.DecimalField(max_digits=10, decimal_places=3)
    fuente = models.CharField(max_length=40, default="SUNAT")
    obtenido = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tipo de cambio"
        verbose_name_plural = "tipos de cambio"
        ordering = ["-fecha"]

    def __str__(self) -> str:
        return f"{self.fecha} · compra {self.compra} · venta {self.venta}"

    @classmethod
    def del_dia(cls, fecha):
        registro = cls.objects.filter(fecha__lte=fecha).first()
        if registro is None:
            raise ValueError(f"No hay tipo de cambio para {fecha}.")
        return registro


class Perfil(models.Model):
    """Rol del usuario dentro de la empresa."""

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        REGISTRADOR = "REGISTRADOR", "Registrador"
        LECTOR = "LECTOR", "Solo lectura"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil",
    )
    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, null=True, blank=True, related_name="perfiles"
    )
    rol = models.CharField(max_length=12, choices=Rol.choices, default=Rol.REGISTRADOR)

    class Meta:
        verbose_name = "perfil"
        verbose_name_plural = "perfiles"

    def __str__(self) -> str:
        return f"{self.usuario.username} · {self.get_rol_display()}"

class HistorialDocumento(models.Model):
    """Rastro de cambios y acciones sobre compras y ventas."""

    class Tipo(models.TextChoices):
        COMPRA = "COMPRA", "Compra"
        VENTA = "VENTA", "Venta"
        GASTO = "GASTO", "Gasto"
        ASIENTO = "ASIENTO", "Asiento"
        IMPUESTO = "IMPUESTO", "Impuesto"

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="historial"
    )
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    documento_id = models.PositiveIntegerField()
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="historial_documentos",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=20, default="EDICION")
    detalle = models.TextField(blank=True)

    class Meta:
        verbose_name = "historial de documento"
        verbose_name_plural = "historial de documentos"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["empresa", "tipo", "documento_id"])]

    def __str__(self) -> str:
        return f"{self.tipo} {self.documento_id} · {self.accion}"

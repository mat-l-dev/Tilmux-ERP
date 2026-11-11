"""Estado documental del SIRE: propuesta, complemento y registro generado.

No guarda importes contables: eso vive en compras/ventas. Aquí queda la
trazabilidad de qué archivo se descargó, qué se ajustó y con qué constancia se
generó el registro. Sin constancia, el período no está cerrado.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class EstadoSIRE(models.Model):
    class Registro(models.TextChoices):
        RCE = "RCE", "RCE · compras"
        RVIE = "RVIE", "RVIE · ventas"

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="estados_sire")
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    registro = models.CharField(max_length=4, choices=Registro.choices)
    constancia_recepcion = models.CharField(max_length=80, blank=True)
    numero_operacion = models.CharField(max_length=60, blank=True)
    registros_generados = models.PositiveIntegerField(null=True, blank=True)
    generado_en = models.DateTimeField(null=True, blank=True)
    generado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_sire_generados",
    )
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "estado SIRE"
        verbose_name_plural = "estados SIRE"
        ordering = ["-anio", "-mes", "registro"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "anio", "mes", "registro"],
                name="estado_sire_unico_por_registro",
            ),
            models.CheckConstraint(condition=models.Q(mes__gte=1, mes__lte=12), name="estado_sire_mes_valido"),
        ]

    def __str__(self) -> str:
        return f"{self.anio}-{self.mes:02d} · {self.registro} · {self.estado}"

    @property
    def propuesta_actual(self):
        return self.propuestas.first()

    @property
    def estado(self) -> str:
        if self.constancia_recepcion and self.numero_operacion and self.generado_en:
            return "GENERADO"
        if not self.propuestas.exists():
            return "SIN PROPUESTA"
        if self.ajustes.exists():
            return "COMPLEMENTADA"
        return "PROPUESTA"

    @property
    def cerrado(self) -> bool:
        """Solo una constancia de recepción cierra el registro."""
        return self.estado == "GENERADO"


class PropuestaSIRE(models.Model):
    """Archivo original de la propuesta descargada del SIRE."""

    estado = models.ForeignKey(EstadoSIRE, on_delete=models.CASCADE, related_name="propuestas")
    archivo = models.FileField(upload_to="sire/%Y/%m/", max_length=255)
    nombre_original = models.CharField(max_length=255)
    hash_sha256 = models.CharField(max_length=64)
    tamano = models.PositiveIntegerField(default=0)
    filas = models.PositiveIntegerField(default=0)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    descargada_en = models.DateTimeField(auto_now_add=True)
    descargada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="propuestas_sire",
    )

    class Meta:
        verbose_name = "propuesta SIRE"
        verbose_name_plural = "propuestas SIRE"
        ordering = ["-descargada_en", "-pk"]

    def __str__(self) -> str:
        return f"{self.nombre_original} · {self.filas} filas"


class AjusteSIRE(models.Model):
    """Comprobante agregado o excluido al complementar la propuesta."""

    class Tipo(models.TextChoices):
        AGREGADO = "AGREGADO", "Agregado"
        EXCLUIDO = "EXCLUIDO", "Excluido"

    estado = models.ForeignKey(EstadoSIRE, on_delete=models.CASCADE, related_name="ajustes")
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    documento = models.CharField(max_length=60)
    tipo_doc = models.CharField(max_length=8, default="OTRO")
    fecha = models.DateField(null=True, blank=True)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    motivo = models.CharField(max_length=300)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ajustes_sire",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ajuste SIRE"
        verbose_name_plural = "ajustes SIRE"
        ordering = ["-creado", "-pk"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} · {self.documento}"

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


class RestitucionSocio(models.Model):
    """Pago de una deuda con el socio (4411/4419) con los datos del voucher.

    Solo existe cuando el voucher bancario está completo: número de operación,
    fecha y hora, cuenta de origen y destino, importe exacto y concepto. Sin eso
    la obligación queda PENDIENTE y no se postea ningún asiento.
    """

    class Tipo(models.TextChoices):
        PRESTAMO_SOCIO = "PRESTAMO_SOCIO", "Préstamo del socio (4411)"
        REEMBOLSO_SOCIO = "REEMBOLSO_SOCIO", "Reembolso al socio (4419)"
        REEMBOLSO_DIRECTOR = "REEMBOLSO_DIRECTOR", "Reembolso al director (4429)"
        REEMBOLSO_TERCERO = "REEMBOLSO_TERCERO", "Reembolso a tercero (4699)"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="restituciones_socio"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    fecha = models.DateField()
    fecha_hora = models.DateTimeField(help_text="Fecha y hora que figuran en el voucher.")
    cuenta = models.ForeignKey(
        "catalogo.CuentaTesoreria", on_delete=models.PROTECT, related_name="restituciones"
    )
    cuenta_contable = models.ForeignKey(
        "contabilidad.Cuenta", on_delete=models.PROTECT, related_name="restituciones"
    )
    beneficiario = models.CharField(max_length=200)
    numero_operacion = models.CharField(max_length=60)
    cuenta_destino = models.CharField(max_length=120)
    importe = models.DecimalField(max_digits=18, decimal_places=2)
    concepto = models.CharField(max_length=200)
    asiento = models.ForeignKey(
        "contabilidad.Asiento", on_delete=models.PROTECT, null=True, blank=True
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "restitución a socio"
        verbose_name_plural = "restitución a socios"
        ordering = ["-fecha_hora", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero_operacion"],
                name="restitucion_operacion_unica",
            ),
            models.CheckConstraint(
                condition=models.Q(importe__gt=0), name="restitucion_importe_positivo"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y} · {self.beneficiario} · {self.importe}"

    @property
    def cuenta_destino_visible(self) -> str:
        """Muestra solo los últimos dígitos de la cuenta del beneficiario."""
        limpio = (self.cuenta_destino or "").replace(" ", "")
        return f"•••• {limpio[-4:]}" if len(limpio) > 4 else "••••"


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

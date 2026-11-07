"""Cotizaciones, ventas y notas de crédito."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Cotizacion(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ENVIADA = "ENVIADA", "Enviada"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        CONVERTIDA = "CONVERTIDA", "Convertida en venta"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="cotizaciones"
    )
    numero = models.CharField(max_length=20)
    cliente = models.ForeignKey(
        "catalogo.Tercero",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cotizaciones",
        limit_choices_to={"rol__in": ["CLIENTE", "AMBOS"]},
    )
    cliente_nombre = models.CharField(max_length=200, blank=True)
    fecha = models.DateField()
    valida_hasta = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.BORRADOR
    )
    glosa = models.CharField(max_length=255, blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cotización"
        verbose_name_plural = "cotizaciones"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="cotizacion_numero_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.numero} · {self.cliente_nombre or (self.cliente and self.cliente.nombre) or 'Sin cliente'}"


class CotizacionLinea(models.Model):
    cotizacion = models.ForeignKey(
        Cotizacion, on_delete=models.CASCADE, related_name="lineas"
    )
    orden = models.PositiveSmallIntegerField(default=1)
    producto = models.ForeignKey(
        "catalogo.Producto", on_delete=models.PROTECT, related_name="cotizaciones"
    )
    descripcion = models.CharField(max_length=200, blank=True)
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        verbose_name = "línea de cotización"
        verbose_name_plural = "líneas de cotización"
        ordering = ["cotizacion", "orden"]


class Venta(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        ANULADA = "ANULADA", "Anulada"

    class TipoDoc(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        BOLETA = "BOLETA", "Boleta"

    class Condicion(models.TextChoices):
        CONTADO = "CONTADO", "Contado"
        CREDITO = "CREDITO", "Crédito"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="ventas"
    )
    cliente = models.ForeignKey(
        "catalogo.Tercero",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ventas",
        limit_choices_to={"rol__in": ["CLIENTE", "AMBOS"]},
    )
    cliente_nombre = models.CharField(max_length=200, blank=True)
    fecha = models.DateField()
    tipo_doc = models.CharField(
        max_length=8, choices=TipoDoc.choices, default=TipoDoc.BOLETA
    )
    serie = models.CharField(max_length=4)
    numero = models.CharField(max_length=20)
    condicion = models.CharField(
        max_length=8, choices=Condicion.choices, default=Condicion.CONTADO
    )
    cuenta = models.ForeignKey(
        "catalogo.CuentaTesoreria",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ventas",
    )
    canal = models.CharField(max_length=15, default="TRANSFERENCIA")
    moneda = models.CharField(max_length=3, default="PEN")
    tipo_cambio = models.DecimalField(max_digits=12, decimal_places=6, default=1)
    cotizacion = models.ForeignKey(
        Cotizacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas"
    )
    glosa = models.CharField(max_length=255, blank=True)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.BORRADOR
    )
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    costo_venta = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas",
    )
    creada = models.DateTimeField(auto_now_add=True)
    confirmada_en = models.DateTimeField(null=True, blank=True)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_modificadas",
    )
    modificado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["empresa", "fecha"])]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_doc", "serie", "numero"],
                name="venta_comprobante_unico",
            )
        ]

    def __str__(self) -> str:
        return f"{self.serie}-{self.numero} · {self.total}"


class CuotaVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="cuotas")
    numero = models.PositiveSmallIntegerField()
    vencimiento = models.DateField()
    importe = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["numero"]
        constraints = [
            models.UniqueConstraint(fields=["venta", "numero"], name="cuota_venta_numero_unico"),
            models.CheckConstraint(condition=models.Q(importe__gt=0), name="cuota_venta_importe_positivo"),
            models.CheckConstraint(condition=models.Q(numero__gt=0), name="cuota_venta_numero_positivo"),
        ]


class CobroVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="cobros")
    fecha = models.DateField()
    importe = models.DecimalField(max_digits=18, decimal_places=2)
    cuenta = models.ForeignKey("catalogo.CuentaTesoreria", on_delete=models.PROTECT)
    canal = models.CharField(max_length=15)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fecha", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(importe__gt=0), name="cobro_venta_importe_positivo")]


class VentaLinea(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="lineas")
    orden = models.PositiveSmallIntegerField(default=1)
    producto = models.ForeignKey(
        "catalogo.Producto", on_delete=models.PROTECT, related_name="ventas"
    )
    descripcion = models.CharField(max_length=200, blank=True)
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    costo_unitario = models.DecimalField(max_digits=24, decimal_places=10, default=0)
    costo_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        verbose_name = "línea de venta"
        verbose_name_plural = "líneas de venta"
        ordering = ["venta", "orden"]


class NotaCredito(models.Model):
    class Motivo(models.TextChoices):
        ANULACION = "01", "Anulación de la operación"
        ERROR_RUC = "02", "Anulación por error en el RUC"
        ERROR_DESCRIPCION = "03", "Corrección por error en la descripción"
        DESCUENTO_GLOBAL = "04", "Descuento global"
        DESCUENTO_ITEM = "05", "Descuento por ítem"
        DEVOLUCION_TOTAL = "06", "Devolución total"
        DEVOLUCION_ITEM = "07", "Devolución por ítem"
        BONIFICACION = "08", "Bonificación"
        DISMINUCION = "09", "Disminución en el valor"
        OTROS = "10", "Otros conceptos"
        AJUSTE_EXPORTACION = "11", "Ajustes de operaciones de exportación"
        AJUSTE_IVAP = "12", "Ajustes afectos al IVAP"

    venta = models.ForeignKey(
        Venta, on_delete=models.PROTECT, related_name="notas_credito"
    )
    fecha = models.DateField()
    serie = models.CharField(max_length=4)
    numero = models.CharField(max_length=20)
    motivo = models.CharField(max_length=200)
    motivo_codigo = models.CharField(
        max_length=2, choices=Motivo.choices, default=Motivo.DEVOLUCION_ITEM
    )
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    costo = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    reingresa_stock = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "nota de crédito"
        verbose_name_plural = "notas de crédito"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["venta", "serie", "numero"], name="nota_credito_unica"
            )
        ]

    def __str__(self) -> str:
        return f"{self.serie}-{self.numero} · {self.venta_id}"


class NotaCreditoLinea(models.Model):
    nota = models.ForeignKey(
        NotaCredito, on_delete=models.CASCADE, related_name="lineas"
    )
    venta_linea = models.ForeignKey(
        VentaLinea, on_delete=models.PROTECT, related_name="notas_credito"
    )
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    costo_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        verbose_name = "línea de nota de crédito"
        verbose_name_plural = "líneas de nota de crédito"
        ordering = ["nota", "id"]


class NotaDebito(models.Model):
    class Motivo(models.TextChoices):
        INTERESES = "01", "Intereses por mora"
        AUMENTO_VALOR = "02", "Aumento en el valor"
        PENALIDADES = "03", "Penalidades y otros conceptos"
        AJUSTE_EXPORTACION = "11", "Ajustes de operaciones de exportación"
        AJUSTE_IVAP = "12", "Ajustes afectos al IVAP"

    venta = models.ForeignKey(
        Venta, on_delete=models.PROTECT, related_name="notas_debito"
    )
    fecha = models.DateField()
    serie = models.CharField(max_length=4)
    numero = models.CharField(max_length=20)
    motivo_codigo = models.CharField(
        max_length=2, choices=Motivo.choices, default=Motivo.INTERESES
    )
    descripcion = models.CharField(max_length=200, blank=True)
    base = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "nota de débito"
        verbose_name_plural = "notas de débito"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["venta", "serie", "numero"], name="nota_debito_unica"
            )
        ]

    def __str__(self) -> str:
        return f"{self.serie}-{self.numero}"


from .models_guia import GuiaRemision  # noqa: E402,F401

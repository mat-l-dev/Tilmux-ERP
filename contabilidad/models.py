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


class Regla(models.Model):
    """Plantilla de asiento por tipo de operación."""

    class Tipo(models.TextChoices):
        COMPRA = "COMPRA", "Compra de mercadería"
        VENTA = "VENTA", "Venta de mercadería"
        PAGO_PROVEEDOR = "PAGO_PROVEEDOR", "Pago a proveedor"
        COBRO_CLIENTE = "COBRO_CLIENTE", "Cobro de cliente"
        GASTO_CON_IGV = "GASTO_CON_IGV", "Gasto con IGV"
        GASTO_SIN_IGV = "GASTO_SIN_IGV", "Gasto sin IGV"
        NOTA_CREDITO = "NOTA_CREDITO", "Nota de crédito de venta"
        APORTE_CAPITAL = "APORTE_CAPITAL", "Aporte de capital"
        PRESTAMO_SOCIO = "PRESTAMO_SOCIO", "Préstamo de socio"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia entre cuentas"
        IGV_MENSUAL = "IGV_MENSUAL", "Pago de IGV mensual"
        RENTA_MENSUAL = "RENTA_MENSUAL", "Renta RER del mes"
        CAPITAL_SUSCRITO = "CAPITAL_SUSCRITO", "Capital suscrito"
        REEMBOLSO_SOCIO = "REEMBOLSO_SOCIO", "Dinero de socio por reembolsar"
        COMISION_PASARELA = "COMISION_PASARELA", "Comisión de pasarela"

    tipo = models.CharField(max_length=20, choices=Tipo.choices, unique=True)
    nombre = models.CharField(max_length=120)

    class Meta:
        verbose_name = "regla contable"
        verbose_name_plural = "reglas contables"
        ordering = ["tipo"]

    def __str__(self) -> str:
        return self.nombre


class ReglaLinea(models.Model):
    class Lado(models.TextChoices):
        DEBE = "D", "Debe"
        HABER = "H", "Haber"

    class ImporteRef(models.TextChoices):
        BASE = "BASE", "Base imponible"
        IGV = "IGV", "IGV"
        TOTAL = "TOTAL", "Total"
        COSTO = "COSTO", "Costo de venta"
        NO_GRAVADO = "NO_GRAVADO", "No gravado"
        MEDIO = "MEDIO", "Cuenta del medio de pago"
        MEDIO_DESTINO = "MEDIO_DESTINO", "Cuenta del medio de destino"
        GASTO = "GASTO", "Cuenta del gasto"

    regla = models.ForeignKey(Regla, on_delete=models.CASCADE, related_name="lineas")
    orden = models.PositiveSmallIntegerField()
    cuenta = models.ForeignKey(
        Cuenta,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reglas",
        help_text="Vacío cuando la cuenta la decide el medio de pago.",
    )
    lado = models.CharField(max_length=1, choices=Lado.choices)
    importe_ref = models.CharField(max_length=14, choices=ImporteRef.choices)
    glosa = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "línea de regla"
        verbose_name_plural = "líneas de regla"
        ordering = ["regla", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["regla", "orden"], name="regla_linea_orden_unico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.regla.tipo} · {self.orden} · {self.lado} {self.importe_ref}"


class Asiento(models.Model):
    class Estado(models.TextChoices):
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        ANULADO = "ANULADO", "Anulado"

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="asientos"
    )
    periodo = models.ForeignKey(
        "core.Periodo", on_delete=models.PROTECT, related_name="asientos"
    )
    numero = models.PositiveIntegerField()
    fecha = models.DateField()
    tipo_operacion = models.CharField(max_length=20, choices=Regla.Tipo.choices)
    glosa = models.CharField(max_length=255)
    origen_tipo = models.CharField(max_length=20, blank=True)
    origen_id = models.BigIntegerField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.CONFIRMADO
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "asiento"
        verbose_name_plural = "asientos"
        ordering = ["-fecha", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="asiento_numero_unico"
            )
        ]
        indexes = [models.Index(fields=["empresa", "fecha"])]

    def __str__(self) -> str:
        return f"{self.numero:05d} · {self.glosa[:40]}"

    @property
    def debe(self):
        return sum((l.debe for l in self.lineas.all()), 0)

    @property
    def haber(self):
        return sum((l.haber for l in self.lineas.all()), 0)


class AsientoLinea(models.Model):
    class Diferencia(models.TextChoices):
        NINGUNA = "NINGUNA", "Ninguna"
        TEMPORARIA = "TEMPORARIA", "Temporaria"
        PERMANENTE = "PERMANENTE", "Permanente"

    asiento = models.ForeignKey(
        Asiento, on_delete=models.CASCADE, related_name="lineas"
    )
    orden = models.PositiveSmallIntegerField()
    cuenta = models.ForeignKey(
        Cuenta, on_delete=models.PROTECT, related_name="lineas_asiento"
    )
    debe = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    haber = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    monto_contable = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    monto_tributario = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tipo_diferencia = models.CharField(
        max_length=10, choices=Diferencia.choices, default=Diferencia.NINGUNA
    )
    glosa = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "línea de asiento"
        verbose_name_plural = "líneas de asiento"
        ordering = ["asiento", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["asiento", "orden"], name="asiento_linea_orden_unico"
            ),
            models.CheckConstraint(
                condition=~(models.Q(debe__gt=0) & models.Q(haber__gt=0)),
                name="asiento_linea_un_solo_lado",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cuenta.codigo} D{self.debe} H{self.haber}"

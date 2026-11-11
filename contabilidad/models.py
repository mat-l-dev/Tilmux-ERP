"""Catálogo de cuentas del PCGE."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class DeclaracionIGV621(models.Model):
    """Copia manual de casillas de una constancia presentada; no es la deuda total."""

    class Tipo(models.TextChoices):
        ORIGINAL = "ORIGINAL", "Original"
        SUSTITUTORIA = "SUSTITUTORIA", "Sustitutoria"
        RECTIFICATORIA = "RECTIFICATORIA", "Rectificatoria"

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT)
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    tipo = models.CharField(max_length=14, choices=Tipo.choices)
    numero_orden = models.CharField(max_length=40)
    fecha_presentacion = models.DateField()
    casilla_140 = models.DecimalField(max_digits=15, decimal_places=0)
    casilla_145 = models.DecimalField(max_digits=15, decimal_places=0)
    casilla_184 = models.DecimalField(max_digits=15, decimal_places=0)
    casilla_100 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="Ventas netas gravadas, como figura en la constancia.",
    )
    casilla_101 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="IGV de ventas, como figura en la constancia.",
    )
    casilla_107 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="Compras gravadas (base), como figura en la constancia.",
    )
    casilla_108 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="IGV de compras, como figura en la constancia.",
    )
    casilla_120 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="Compras no gravadas, como figura en la constancia.",
    )
    casilla_301 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="Renta: base imponible, como figura en la constancia.",
    )
    casilla_312 = models.DecimalField(
        max_digits=15, decimal_places=0, null=True, blank=True,
        help_text="Renta: impuesto resultante, como figura en la constancia.",
    )
    redondeo_deuda = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0,
        help_text=(
            "Casilla 184 menos el IGV estimado en libros. Es el redondeo a enteros "
            "(RS 025-2000), guardado para auditoría; no es un asiento."
        ),
    )
    vigente = models.BooleanField(
        default=False,
        help_text="Solo una constancia vigente por período; una rectificatoria reemplaza a la anterior.",
    )
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    registrado_en = models.DateTimeField(auto_now_add=True)
    anulada = models.BooleanField(default=False)
    motivo_anulacion = models.CharField(max_length=250, blank=True)
    anulada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="registros_621_anulados",
    )
    anulada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-registrado_en", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero_orden"], condition=models.Q(anulada=False),
                name="declaracion_621_orden_unica",
            ),
            models.UniqueConstraint(
                fields=["empresa", "anio", "mes"],
                condition=models.Q(vigente=True, anulada=False),
                name="declaracion_621_vigente_unica",
            ),
            models.CheckConstraint(condition=models.Q(mes__gte=1, mes__lte=12), name="declaracion_621_mes_valido"),
            models.CheckConstraint(condition=models.Q(casilla_145__gte=0), name="declaracion_621_saldo_no_negativo"),
        ]


class PagoIGV621(models.Model):
    """Pago del IGV ligado a la constancia vigente que lo justifica."""

    empresa = models.ForeignKey(
        "core.Empresa", on_delete=models.PROTECT, related_name="pagos_igv"
    )
    declaracion = models.ForeignKey(
        DeclaracionIGV621, on_delete=models.PROTECT, related_name="pagos"
    )
    fecha = models.DateField()
    importe = models.DecimalField(max_digits=18, decimal_places=2)
    cuenta = models.ForeignKey(
        "catalogo.CuentaTesoreria", on_delete=models.PROTECT, related_name="pagos_igv"
    )
    movimiento = models.ForeignKey(
        "tesoreria.MovimientoTesoreria",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pagos_igv",
    )
    asiento = models.ForeignKey(
        "Asiento", on_delete=models.PROTECT, null=True, blank=True, related_name="pagos_igv"
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_igv",
    )
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "pago de IGV"
        verbose_name_plural = "pagos de IGV"
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(importe__gt=0), name="pago_igv_importe_positivo"
            )
        ]

    def __str__(self) -> str:
        return f"{self.fecha} · S/ {self.importe}"


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
        PROVISION_GASTO = "PROVISION_GASTO", "Provisión de gasto"
        NOTA_CREDITO = "NOTA_CREDITO", "Nota de crédito de venta"
        DEVOLUCION_COMPRA = "DEVOLUCION_COMPRA", "Nota de crédito de compra"
        REEMBOLSO_PROVEEDOR = "REEMBOLSO_PROVEEDOR", "Reembolso de proveedor"
        APORTE_CAPITAL = "APORTE_CAPITAL", "Aporte de capital"
        PRESTAMO_SOCIO = "PRESTAMO_SOCIO", "Préstamo de socio"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia entre cuentas"
        IGV_MENSUAL = "IGV_MENSUAL", "Pago de IGV mensual"
        RENTA_MENSUAL = "RENTA_MENSUAL", "Renta RER del mes"
        PAGO_RENTA = "PAGO_RENTA", "Pago de renta RER"
        REVALUACION = "REVALUACION", "Revaluación de moneda extranjera"
        CAPITAL_SUSCRITO = "CAPITAL_SUSCRITO", "Capital suscrito"
        REEMBOLSO_SOCIO = "REEMBOLSO_SOCIO", "Dinero de socio por reembolsar"
        RESTITUCION_SOCIO = "RESTITUCION_SOCIO", "Restitución al socio"
        COMISION_PASARELA = "COMISION_PASARELA", "Comisión de pasarela"
        CIERRE = "CIERRE", "Cierre del ejercicio"

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
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asientos",
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
        return sum((linea.debe for linea in self.lineas.all()), 0)

    @property
    def haber(self):
        return sum((linea.haber for linea in self.lineas.all()), 0)


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

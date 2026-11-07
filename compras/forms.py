"""Formularios de compra: validan la cabecera antes de crear el borrador."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from catalogo.models import CuentaTesoreria, Tercero
from contabilidad.models import Cuenta

from .models import Compra
from .models_gasto import Gasto


class CabeceraCompraForm(forms.Form):
    fecha = forms.DateField()
    tipo_doc = forms.ChoiceField(choices=Compra.TipoDoc.choices)
    serie = forms.CharField(max_length=4, required=False)
    numero = forms.CharField(max_length=20, required=False)
    proveedor = forms.IntegerField(required=False)
    proveedor_ruc = forms.CharField(max_length=11, required=False)
    proveedor_nombre = forms.CharField(max_length=200, required=False)
    glosa = forms.CharField(max_length=255, required=False)

    def clean_proveedor_ruc(self):
        ruc = (self.cleaned_data.get("proveedor_ruc") or "").strip()
        if ruc and (not ruc.isdigit() or len(ruc) != 11):
            raise forms.ValidationError("El RUC debe tener 11 dígitos.")
        return ruc

    def clean(self):
        datos = super().clean()
        if not datos.get("proveedor"):
            if not datos.get("proveedor_ruc") or not datos.get("proveedor_nombre"):
                self.add_error(
                    "proveedor_nombre",
                    "Elige un proveedor o escribe su RUC y razón social.",
                )
        return datos


class GastoPagadoForm(forms.Form):
    fecha = forms.DateField(label="Fecha de pago y del gasto", widget=forms.DateInput(attrs={"type": "date"}))
    proveedor = forms.ModelChoiceField(queryset=Tercero.objects.none(), label="Proveedor")
    tipo_doc = forms.ChoiceField(choices=Gasto.TipoDoc.choices, label="Tipo de documento")
    serie = forms.CharField(max_length=4, required=False, label="Serie")
    numero = forms.CharField(max_length=20, required=False, label="Número")
    base = forms.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01"), label="Base o importe sin IGV"
    )
    igv = forms.DecimalField(max_digits=18, decimal_places=2, min_value=0, label="IGV", initial=0)
    cuenta = forms.ModelChoiceField(queryset=Cuenta.objects.none(), label="Cuenta de gasto")
    medio = forms.ModelChoiceField(queryset=CuentaTesoreria.objects.none(), label="Cuenta desde la que se pagó")
    canal = forms.ChoiceField(choices=[("", "Selecciona un canal"), *CuentaTesoreria.Canal.choices],
                              label="Cómo se pagó")
    glosa = forms.CharField(max_length=255, label="Concepto")
    con_credito = forms.BooleanField(
        required=False, label="Incluir en la estimación tributaria de compras", initial=False
    )
    deducible = forms.BooleanField(required=False, label="Sustenta costo o gasto tributario", initial=False)
    provisiones = forms.ModelMultipleChoiceField(
        queryset=Gasto.objects.none(), required=False, label="Provisiones que liquida (opcional)",
        help_text=("Mismo proveedor y total, sin IGV. Se usa la cuenta de gasto de cada provisión; "
                   "la cuenta elegida arriba no registra otro gasto."),
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].queryset = Tercero.objects.filter(activo=True, rol__in=["PROVEEDOR", "AMBOS"])
        self.fields["cuenta"].queryset = Cuenta.objects.filter(
            version="2026", activa=True, elemento=6, admite_movimiento=True
        )
        self.fields["medio"].queryset = CuentaTesoreria.objects.filter(
            empresa=empresa, activa=True, moneda="PEN", cuenta_contable__isnull=False
        )
        self.fields["provisiones"].queryset = Gasto.objects.filter(
            empresa=empresa, provision=True, estado=Gasto.Estado.PROVISION, gasto_origen__isnull=True,
        ).select_related("proveedor")

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo_doc")
        if tipo in {Gasto.TipoDoc.FACTURA, Gasto.TipoDoc.BOLETA}:
            if not datos.get("serie"):
                self.add_error("serie", "Indica la serie del comprobante.")
            if not datos.get("numero"):
                self.add_error("numero", "Indica el número del comprobante.")
        if datos.get("con_credito") and tipo != Gasto.TipoDoc.FACTURA:
            self.add_error("con_credito", "Solo se permite marcar crédito en una factura.")
        proveedor = datos.get("proveedor")
        if tipo == Gasto.TipoDoc.FACTURA and proveedor and (
            proveedor.tipo_doc != "RUC" or len(proveedor.numero_doc) != 11 or not proveedor.numero_doc.isdigit()
        ):
            self.add_error("proveedor", "La factura requiere un proveedor con RUC de 11 dígitos.")
        base, igv = datos.get("base"), datos.get("igv")
        if base is not None and igv is not None and base + igv <= 0:
            self.add_error("base", "El total del gasto debe ser mayor que cero.")
        return datos


class ProvisionGastoForm(forms.Form):
    fecha = forms.DateField(label="Fecha del gasto devengado", widget=forms.DateInput(attrs={"type": "date"}))
    proveedor = forms.ModelChoiceField(queryset=Tercero.objects.none(), label="Proveedor")
    importe = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"), label="Importe en soles")
    cuenta = forms.ModelChoiceField(queryset=Cuenta.objects.none(), label="Cuenta de gasto")
    glosa = forms.CharField(max_length=255, label="Concepto")
    confirmado = forms.BooleanField(label="Confirmo que el gasto corresponde a una obligación ya generada")
    operacion = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].queryset = Tercero.objects.filter(activo=True, rol__in=["PROVEEDOR", "AMBOS"])
        self.fields["cuenta"].queryset = Cuenta.objects.filter(
            version="2026", activa=True, elemento=6, admite_movimiento=True
        )


class GastoPendienteForm(GastoPagadoForm):
    confirma_base_provision = forms.BooleanField(
        required=False, label="Confirmo que la provisión corresponde a la base sin IGV de esta factura",
        help_text="Márcalo solo al vincular una provisión con una factura con IGV y crédito fiscal.",
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, empresa=empresa, **kwargs)
        self.fields.pop("medio")
        self.fields.pop("canal")
        self.fields["fecha"].label = "Fecha del comprobante y del gasto"
        self.fields["tipo_doc"].choices = [c for c in Gasto.TipoDoc.choices if c[0] != Gasto.TipoDoc.OTRO]
        self.fields["provisiones"].label = "Gastos devengados que respalda este comprobante (opcional)"
        self.fields["provisiones"].help_text = (
            "Sin IGV: deben sumar el total. Con IGV y crédito fiscal: una provisión por la base exacta. "
            "La cuenta de gasto indicada arriba no se usa si vinculas provisiones."
        )


class PagoGastoForm(forms.Form):
    fecha = forms.DateField(label="Fecha del pago", widget=forms.DateInput(attrs={"type": "date"}))
    importe = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"), label="Importe en soles")
    cuenta = forms.ModelChoiceField(queryset=CuentaTesoreria.objects.none(), label="Cuenta de pago")
    canal = forms.ChoiceField(choices=[("", "Selecciona un canal"), *CuentaTesoreria.Canal.choices],
                              label="Cómo se pagó")
    operacion = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = CuentaTesoreria.objects.filter(
            empresa=empresa, activa=True, moneda="PEN", cuenta_contable__isnull=False
        )


class ImportarGastoForm(forms.Form):
    cuenta = forms.ModelChoiceField(queryset=Cuenta.objects.none(), label="Cuenta del gasto")
    medio = forms.ModelChoiceField(queryset=CuentaTesoreria.objects.none(), label="Cuenta desde la que se pagó")
    canal = forms.ChoiceField(choices=[("", "Selecciona un canal"), *CuentaTesoreria.Canal.choices],
                              label="Cómo se pagó")
    con_credito = forms.BooleanField(required=False, label="Incluir en la estimación tributaria de compras")
    deducible = forms.BooleanField(required=False, label="Sustenta costo o gasto tributario")
    pago_confirmado = forms.BooleanField(
        label="Confirmo que se pagó el total en la fecha del comprobante desde la cuenta seleccionada"
    )

    def __init__(self, *args, empresa, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = tipo
        self.fields["cuenta"].queryset = Cuenta.objects.filter(
            version="2026", activa=True, elemento=6, admite_movimiento=True,
        ).order_by("codigo")
        self.fields["medio"].queryset = CuentaTesoreria.objects.filter(
            empresa=empresa, activa=True, moneda="PEN", cuenta_contable__isnull=False,
        )

    def clean_con_credito(self):
        valor = self.cleaned_data["con_credito"]
        if valor and self.tipo != Gasto.TipoDoc.FACTURA:
            raise forms.ValidationError("Solo se permite marcar crédito en una factura.")
        return valor

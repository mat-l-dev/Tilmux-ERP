"""Formularios de venta: validan la cabecera antes de crear el borrador."""

from __future__ import annotations

from decimal import Decimal

from django import forms

from catalogo.models import CuentaTesoreria

from .models import Venta

CANALES = [
    ("TRANSFERENCIA", "Transferencia"),
    ("YAPE", "Yape"),
    ("PLIN", "Plin"),
    ("QR", "QR"),
    ("TARJETA", "Tarjeta"),
    ("EFECTIVO", "Efectivo"),
]


class CabeceraVentaForm(forms.Form):
    fecha = forms.DateField()
    tipo_doc = forms.ChoiceField(choices=Venta.TipoDoc.choices)
    serie = forms.CharField(max_length=4)
    numero = forms.CharField(max_length=20)
    cliente_nombre = forms.CharField(max_length=200, required=False)
    cliente_doc = forms.CharField(max_length=11, required=False)
    condicion = forms.ChoiceField(choices=Venta.Condicion.choices)
    cuenta = forms.ModelChoiceField(
        queryset=CuentaTesoreria.objects.none(), required=False
    )
    canal = forms.ChoiceField(choices=CANALES, required=False)
    glosa = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is not None:
            self.fields["cuenta"].queryset = CuentaTesoreria.objects.filter(
                empresa=empresa, activa=True
            )

    def clean_cliente_doc(self):
        documento = (self.cleaned_data.get("cliente_doc") or "").strip()
        if documento and not documento.isdigit():
            raise forms.ValidationError("El documento solo admite números.")
        if documento and len(documento) not in (8, 11):
            raise forms.ValidationError("El documento debe tener 8 u 11 dígitos.")
        return documento

    def clean(self):
        datos = super().clean()
        if datos.get("tipo_doc") == Venta.TipoDoc.FACTURA and not datos.get("cliente_doc"):
            self.add_error("cliente_doc", "Una factura exige el RUC del cliente.")
        if datos.get("condicion") == Venta.Condicion.CONTADO and not datos.get("cuenta"):
            self.add_error("cuenta", "Una venta al contado necesita una cuenta.")
        return datos


class CobroVentaForm(forms.Form):
    operacion = forms.UUIDField(widget=forms.HiddenInput)
    fecha = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    importe = forms.DecimalField(max_digits=18, decimal_places=2, min_value=Decimal("0.01"))
    cuenta = forms.ModelChoiceField(queryset=CuentaTesoreria.objects.none())
    canal = forms.ChoiceField(choices=CuentaTesoreria.Canal.choices)

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = CuentaTesoreria.objects.filter(
            empresa=empresa, activa=True, moneda="PEN", cuenta_contable__isnull=False
        )


class CuotaVentaForm(forms.Form):
    vencimiento = forms.DateField(label="Vencimiento", widget=forms.DateInput(attrs={"type": "date"}))
    importe = forms.DecimalField(label="Importe", max_digits=18, decimal_places=2, min_value=Decimal("0.01"))


CuotasVentaFormSet = forms.formset_factory(CuotaVentaForm, extra=1, max_num=100, validate_max=True, can_delete=True)

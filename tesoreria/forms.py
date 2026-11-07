"""Datos mínimos para comparar una operación de un extracto bancario."""

from datetime import date
from decimal import Decimal

from django import forms

from catalogo.models import CuentaTesoreria

from .models import MovimientoTesoreria


class BuscarOperacionBancariaForm(forms.Form):
    cuenta = forms.ModelChoiceField(queryset=CuentaTesoreria.objects.none(), label="Cuenta del extracto")
    fecha = forms.DateField(
        label="Fecha que aparece en el banco",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    tipo = forms.ChoiceField(choices=MovimientoTesoreria.Tipo.choices, label="Tipo de operación")
    importe = forms.DecimalField(
        label="Importe en soles, sin signo", max_digits=18, decimal_places=2, min_value=Decimal("0.01"),
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = CuentaTesoreria.objects.filter(
            empresa=empresa, moneda="PEN",
        ).order_by("nombre", "pk")

    def clean_fecha(self):
        fecha = self.cleaned_data["fecha"]
        if not date(1900, 1, 4) <= fecha <= date(9999, 12, 28):
            raise forms.ValidationError("Indica una fecha dentro del rango admitido.")
        return fecha


class ConfirmarConciliacionForm(BuscarOperacionBancariaForm):
    movimiento_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    referencia = forms.CharField(max_length=100, label="Referencia única del banco")
    confirmo = forms.BooleanField(label="Confirmo que revisé la operación en el extracto")


class RevertirConciliacionForm(forms.Form):
    motivo = forms.CharField(max_length=1000, label="Motivo de la reversión")

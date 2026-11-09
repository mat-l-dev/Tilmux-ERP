"""Datos para comparar el libro con la declaración del período anterior."""

from decimal import Decimal

from django import forms

from contabilidad.models import DeclaracionIGV621


class CompararSaldoIGVForm(forms.Form):
    saldo_declarado = forms.DecimalField(
        label="Saldo a favor declarado del mes anterior (S/)",
        min_value=Decimal("0"), max_digits=18, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}),
        help_text="Ingresa un importe positivo: si la casilla 184 muestra -110, escribe 110.00.",
    )


class DeclaracionIGV621Form(forms.ModelForm):
    class Meta:
        model = DeclaracionIGV621
        fields = ["tipo", "numero_orden", "fecha_presentacion", "casilla_140", "casilla_145", "casilla_184"]
        labels = {
            "tipo": "Tipo de declaración", "numero_orden": "Número de orden de la constancia",
            "fecha_presentacion": "Fecha de presentación", "casilla_140": "Casilla 140 (S/)",
            "casilla_145": "Casilla 145 (S/)", "casilla_184": "Casilla 184 (S/)",
        }
        widgets = {"fecha_presentacion": forms.DateInput(attrs={"type": "date"})}

    def clean_casilla_145(self):
        valor = self.cleaned_data["casilla_145"]
        if valor < 0:
            raise forms.ValidationError("El saldo a favor anterior debe ser cero o positivo.")
        return valor

    def clean(self):
        datos = super().clean()
        c140, c145, c184 = (datos.get(c) for c in ("casilla_140", "casilla_145", "casilla_184"))
        if None not in (c140, c145, c184) and c140 - c145 != c184:
            raise forms.ValidationError("La casilla 184 debe ser igual a la 140 menos la 145; revisa la constancia.")
        return datos

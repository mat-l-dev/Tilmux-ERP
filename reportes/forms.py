"""Datos para comparar el libro con la declaración del período anterior."""

from decimal import Decimal

from django import forms


class CompararSaldoIGVForm(forms.Form):
    saldo_declarado = forms.DecimalField(
        label="Saldo a favor declarado del mes anterior (S/)",
        min_value=Decimal("0"), max_digits=18, decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.01", "inputmode": "decimal"}),
        help_text="Ingresa un importe positivo: si la casilla 184 muestra -110, escribe 110.00.",
    )

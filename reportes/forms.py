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
        fields = [
            "tipo",
            "numero_orden",
            "fecha_presentacion",
            "casilla_100",
            "casilla_101",
            "casilla_107",
            "casilla_108",
            "casilla_120",
            "casilla_140",
            "casilla_145",
            "casilla_184",
            "casilla_301",
            "casilla_312",
        ]
        labels = {
            "tipo": "Tipo de declaración",
            "numero_orden": "Número de orden de la constancia",
            "fecha_presentacion": "Fecha de presentación",
            "casilla_100": "Casilla 100 · ventas netas gravadas (S/)",
            "casilla_101": "Casilla 101 · IGV de ventas (S/)",
            "casilla_107": "Casilla 107 · compras gravadas, base (S/)",
            "casilla_108": "Casilla 108 · IGV de compras (S/)",
            "casilla_120": "Casilla 120 · compras no gravadas (S/)",
            "casilla_140": "Casilla 140 · IGV resultado (S/)",
            "casilla_145": "Casilla 145 · saldo a favor anterior (S/)",
            "casilla_184": "Casilla 184 · IGV a pagar (S/)",
            "casilla_301": "Casilla 301 · renta, base imponible (S/)",
            "casilla_312": "Casilla 312 · renta, impuesto resultante (S/)",
        }
        widgets = {"fecha_presentacion": forms.DateInput(attrs={"type": "date"})}
        help_texts = {
            "casilla_100": "Déjala vacía si la constancia no la muestra; no se inventa.",
            "casilla_301": "Opcional: solo si la constancia de renta la trae.",
        }

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


class ComplementoRCEForm(forms.Form):
    """Boleta tipo 03 que no va en la propuesta y se incorpora al RCE."""

    tipo_doc = forms.ChoiceField(
        label="Tipo de comprobante",
        choices=[("03", "Boleta de venta electrónica (tipo 03)")],
        initial="03",
    )
    ruc_emisor = forms.CharField(
        label="RUC del emisor",
        max_length=11,
        min_length=11,
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )
    razon_social = forms.CharField(label="Razón social del emisor", max_length=200)
    serie = forms.CharField(label="Serie", max_length=4, min_length=4)
    numero = forms.CharField(
        label="Número",
        max_length=20,
        help_text="Como figura en la boleta; el CAR lo lleva a 10 dígitos.",
    )
    fecha = forms.DateField(
        label="Fecha de emisión",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    total = forms.DecimalField(
        label="Total de la boleta (S/)",
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Todo el importe va a compras no gravadas (casilla 120).",
    )
    clasif_tabla23 = forms.CharField(
        label="Clasificación Tabla 23",
        max_length=2,
        initial="5",
        help_text="5 = otros gastos no incluidos en el numeral 4 (comisiones y envío).",
    )
    motivo = forms.CharField(
        label="Motivo del complemento",
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def clean_ruc_emisor(self):
        valor = "".join(c for c in self.cleaned_data["ruc_emisor"] if c.isdigit())
        if len(valor) != 11:
            raise forms.ValidationError("El RUC del emisor debe tener 11 dígitos.")
        return valor

    def clean_serie(self):
        valor = (self.cleaned_data["serie"] or "").strip().upper()
        if len(valor) != 4 or not valor.isalnum():
            raise forms.ValidationError("La serie debe tener 4 caracteres, por ejemplo B001.")
        return valor

    def clean_numero(self):
        valor = "".join(c for c in self.cleaned_data["numero"] if c.isdigit())
        if not 1 <= len(valor) <= 10:
            raise forms.ValidationError("El número debe tener entre 1 y 10 dígitos.")
        return valor

    def clean_clasif_tabla23(self):
        valor = (self.cleaned_data["clasif_tabla23"] or "5").strip()
        if not valor.isdigit():
            raise forms.ValidationError("La clasificación de la Tabla 23 debe ser numérica.")
        return valor[:2]

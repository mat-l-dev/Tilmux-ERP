"""Formularios de compra: validan la cabecera antes de crear el borrador."""

from __future__ import annotations

from django import forms

from .models import Compra


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

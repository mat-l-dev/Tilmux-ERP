from django.contrib import admin

from .models import Empresa, Periodo, TipoCambio


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "ruc", "regimen", "moneda", "activa")
    list_filter = ("regimen", "activa")
    search_fields = ("nombre", "razon_social", "ruc")


@admin.register(Periodo)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ("empresa", "anio", "mes", "estado", "version_pcge")
    list_filter = ("estado", "anio", "empresa")
    ordering = ("-anio", "-mes")


@admin.register(TipoCambio)
class TipoCambioAdmin(admin.ModelAdmin):
    list_display = ("fecha", "compra", "venta", "fuente")
    ordering = ("-fecha",)

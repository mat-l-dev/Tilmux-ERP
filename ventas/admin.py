from django.contrib import admin

from core.admin_seguro import SoloConsultaContable

from .models import Cotizacion, CotizacionLinea, NotaCredito, Venta, VentaLinea


class CotizacionLineaInline(admin.TabularInline):
    model = CotizacionLinea
    extra = 3
    autocomplete_fields = ("producto",)


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ("numero", "fecha", "cliente", "total", "estado")
    list_filter = ("empresa", "estado")
    search_fields = ("numero", "cliente_nombre", "cliente__nombre")
    date_hierarchy = "fecha"
    autocomplete_fields = ("cliente",)
    inlines = [CotizacionLineaInline]


class VentaLineaInline(admin.TabularInline):
    model = VentaLinea
    extra = 3
    fields = ("orden", "producto", "descripcion", "cantidad", "precio_unitario", "base", "igv")
    autocomplete_fields = ("producto",)


@admin.register(Venta)
class VentaAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha", "serie", "numero", "cliente_nombre", "total", "estado", "creado_por")
    list_filter = ("empresa", "estado", "tipo_doc", "condicion")
    search_fields = ("serie", "numero", "cliente_nombre", "cliente__nombre")
    date_hierarchy = "fecha"
    autocomplete_fields = ("cliente",)
    inlines = [VentaLineaInline]
@admin.register(NotaCredito)
class NotaCreditoAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha", "serie", "numero", "venta", "total", "reingresa_stock")
    list_filter = ("reingresa_stock",)
    search_fields = ("serie", "numero", "motivo")

from django.contrib import admin

from .models import CuentaTesoreria, Producto, Serie, Tercero, UnidadMedida


@admin.register(UnidadMedida)
class UnidadMedidaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "decimales")
    search_fields = ("codigo", "nombre")


@admin.register(Tercero)
class TerceroAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rol", "tipo_doc", "numero_doc", "activo")
    list_filter = ("rol", "tipo_doc", "activo")
    search_fields = ("nombre", "numero_doc")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("sku", "nombre", "unidad", "tipo", "activo")
    list_filter = ("tipo", "unidad", "activo")
    search_fields = ("sku", "nombre")


@admin.register(CuentaTesoreria)
class CuentaTesoreriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "tipo", "moneda", "activa")
    list_filter = ("empresa", "tipo", "activa")


@admin.register(Serie)
class SerieAdmin(admin.ModelAdmin):
    list_display = ("serie", "empresa", "tipo", "ultimo_numero", "activa")
    list_filter = ("empresa", "tipo", "activa")

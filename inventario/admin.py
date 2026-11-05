from django.contrib import admin

from .models import CapaFIFO, ConsumoCapa, MovimientoStock


@admin.register(CapaFIFO)
class CapaFIFOAdmin(admin.ModelAdmin):
    list_display = (
        "producto",
        "fecha",
        "cantidad_inicial",
        "cantidad_restante",
        "costo_unitario",
    )
    list_filter = ("empresa", "producto")
    search_fields = ("producto__sku", "producto__nombre")
    date_hierarchy = "fecha"


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ("fecha", "producto", "tipo", "cantidad", "costo_total")
    list_filter = ("empresa", "tipo")
    search_fields = ("producto__sku", "glosa")
    date_hierarchy = "fecha"


@admin.register(ConsumoCapa)
class ConsumoCapaAdmin(admin.ModelAdmin):
    list_display = ("movimiento", "capa", "cantidad", "costo_total")

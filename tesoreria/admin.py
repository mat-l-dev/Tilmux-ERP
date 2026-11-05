from django.contrib import admin

from .models import MovimientoTesoreria


@admin.register(MovimientoTesoreria)
class MovimientoTesoreriaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "cuenta", "tipo", "importe", "canal", "concepto", "conciliado")
    list_filter = ("empresa", "cuenta", "tipo", "canal", "conciliado")
    search_fields = ("concepto",)
    date_hierarchy = "fecha"

from django.contrib import admin

from core.admin_seguro import SoloConsultaContable

from .models import MovimientoTesoreria


@admin.register(MovimientoTesoreria)
class MovimientoTesoreriaAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha", "cuenta", "tipo", "importe", "canal", "concepto", "conciliado")
    list_filter = ("empresa", "cuenta", "tipo", "canal", "conciliado")
    search_fields = ("concepto",)
    date_hierarchy = "fecha"

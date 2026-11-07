from django.contrib import admin

from core.admin_seguro import SoloConsultaContable

from .models import ConciliacionBancaria, MovimientoTesoreria


@admin.register(MovimientoTesoreria)
class MovimientoTesoreriaAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha", "cuenta", "tipo", "importe", "canal", "concepto", "conciliado")
    list_filter = ("empresa", "cuenta", "tipo", "canal", "conciliado")
    search_fields = ("concepto",)
    date_hierarchy = "fecha"


@admin.register(ConciliacionBancaria)
class ConciliacionBancariaAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha_banco", "cuenta", "movimiento", "referencia", "activa", "creado_por")
    list_filter = ("empresa", "activa")

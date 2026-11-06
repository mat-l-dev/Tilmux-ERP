from django.contrib import admin

from core.admin_seguro import SoloConsultaContable

from .models import Compra, CompraLinea, CostoAdicional
from .models_gasto import Gasto


class CompraLineaInline(admin.TabularInline):
    model = CompraLinea
    extra = 3
    fields = ("orden", "producto", "descripcion", "cantidad", "precio_unitario", "base", "igv")
    autocomplete_fields = ("producto",)


class CostoAdicionalInline(admin.TabularInline):
    model = CostoAdicional
    extra = 1
    fields = ("concepto", "base", "igv", "criterio")


@admin.register(Gasto)
class GastoAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = (
        "fecha",
        "fecha_devengado",
        "proveedor",
        "tipo_doc",
        "serie",
        "numero",
        "total",
        "provision",
        "estado",
        "medio",
        "creado_por",
    )
    list_filter = ("empresa", "tipo_doc", "cuenta", "provision", "estado")
    search_fields = ("proveedor__nombre", "serie", "numero", "glosa")
    date_hierarchy = "fecha"
    autocomplete_fields = ("proveedor", "cuenta")


@admin.register(Compra)
class CompraAdmin(SoloConsultaContable, admin.ModelAdmin):
    list_display = ("fecha", "proveedor", "serie", "numero", "total", "estado", "creado_por")
    list_filter = ("empresa", "estado", "tipo_doc")
    search_fields = ("proveedor__nombre", "numero", "serie")
    date_hierarchy = "fecha"
    autocomplete_fields = ("proveedor",)
    inlines = [CompraLineaInline, CostoAdicionalInline]

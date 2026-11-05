from django.contrib import admin

from .models import Asiento, AsientoLinea, Cuenta, Regla, ReglaLinea


@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "elemento",
        "naturaleza",
        "admite_movimiento",
        "categoria_financiera",
        "activa",
    )
    list_filter = ("activa", "elemento", "naturaleza", "admite_movimiento")
    search_fields = ("codigo", "nombre")
    ordering = ("codigo",)
    list_per_page = 50


class ReglaLineaInline(admin.TabularInline):
    model = ReglaLinea
    extra = 0
    fields = ("orden", "cuenta", "lado", "importe_ref", "glosa")
    autocomplete_fields = ("cuenta",)


@admin.register(Regla)
class ReglaAdmin(admin.ModelAdmin):
    list_display = ("tipo", "nombre")
    inlines = [ReglaLineaInline]


class AsientoLineaInline(admin.TabularInline):
    model = AsientoLinea
    extra = 0
    can_delete = False
    readonly_fields = ("orden", "cuenta", "debe", "haber", "glosa")


@admin.register(Asiento)
class AsientoAdmin(admin.ModelAdmin):
    list_display = ("numero", "fecha", "tipo_operacion", "glosa", "estado")
    list_filter = ("empresa", "tipo_operacion", "estado")
    search_fields = ("glosa",)
    date_hierarchy = "fecha"
    inlines = [AsientoLineaInline]

    def has_add_permission(self, request):
        return False

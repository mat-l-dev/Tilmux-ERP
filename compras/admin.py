from django.contrib import admin

from .models import Compra, CompraLinea, CostoAdicional


class CompraLineaInline(admin.TabularInline):
    model = CompraLinea
    extra = 3
    fields = ("orden", "producto", "descripcion", "cantidad", "precio_unitario", "base", "igv")
    autocomplete_fields = ("producto",)


class CostoAdicionalInline(admin.TabularInline):
    model = CostoAdicional
    extra = 1
    fields = ("concepto", "base", "igv", "criterio")


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    list_display = ("fecha", "proveedor", "serie", "numero", "total", "estado")
    list_filter = ("empresa", "estado", "tipo_doc")
    search_fields = ("proveedor__nombre", "numero", "serie")
    date_hierarchy = "fecha"
    autocomplete_fields = ("proveedor",)
    inlines = [CompraLineaInline, CostoAdicionalInline]
    actions = ["confirmar_compras"]

    @admin.action(description="Confirmar compras seleccionadas")
    def confirmar_compras(self, request, queryset):
        from .servicios import CompraError, confirmar

        hechas, errores = 0, []
        for compra in queryset:
            try:
                confirmar(compra)
                hechas += 1
            except CompraError as exc:
                errores.append(f"{compra}: {exc}")
        if hechas:
            self.message_user(request, f"{hechas} compra(s) confirmada(s).")
        for error in errores:
            self.message_user(request, error, level="error")

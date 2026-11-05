from django.contrib import admin

from .models import Cuenta


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

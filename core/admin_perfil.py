from django.contrib import admin

from .models import Perfil


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "empresa", "rol")
    list_filter = ("rol", "empresa")
    search_fields = ("usuario__username",)

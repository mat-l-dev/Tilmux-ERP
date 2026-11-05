"""Punto de entrada de URLs."""

from django.contrib import admin
from django.urls import include, path

from core.salud import salud

urlpatterns = [
    path("admin/", admin.site.urls),
    path("salud/", salud),
    path("cuentas/", include("django.contrib.auth.urls")),
    path("ventas/", include("ventas.urls")),
    path("compras/", include("compras.urls")),
    path("reportes/", include("reportes.urls")),
    path("", include("core.urls")),
]

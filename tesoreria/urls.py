from django.urls import path

from . import views

app_name = "tesoreria"

urlpatterns = [
    path("", views.movimientos, name="movimientos"),
    path("comparar-banco/", views.comparar_banco, name="comparar_banco"),
]

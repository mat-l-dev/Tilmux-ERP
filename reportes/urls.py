from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("balance/", views.balance, name="balance"),
    path("mayor/", views.mayor, name="mayor"),
    path("ventas/", views.registro_ventas, name="registro_ventas"),
    path("compras/", views.registro_compras, name="registro_compras"),
    path("impuestos/", views.impuestos, name="impuestos"),
]

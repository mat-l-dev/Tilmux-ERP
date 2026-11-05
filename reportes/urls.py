from django.urls import path

from . import eeff, exportar, views

app_name = "reportes"

urlpatterns = [
    path("balance/", views.balance, name="balance"),
    path("mayor/", views.mayor, name="mayor"),
    path("ventas/", views.registro_ventas, name="registro_ventas"),
    path("compras/", views.registro_compras, name="registro_compras"),
    path("ventas/exportar/", exportar.ventas, name="exportar_ventas"),
    path("compras/exportar/", exportar.compras, name="exportar_compras"),
    path("eeff/", eeff.estados, name="eeff"),
    path("impuestos/", views.impuestos, name="impuestos"),
]

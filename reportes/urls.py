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
    path("eeff/exportar/", exportar.eeff_excel, name="exportar_eeff"),
    path("eeff/pdf/", exportar.eeff_pdf, name="exportar_eeff_pdf"),
    path("conciliacion/", views.conciliacion, name="conciliacion"),
    path("inventario/", views.inventario, name="inventario"),
    path("kardex/<int:pk>/", views.kardex, name="kardex"),
    path("impuestos/", views.impuestos, name="impuestos"),
]

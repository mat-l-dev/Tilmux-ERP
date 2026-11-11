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
    path("conciliacion/archivo/", views.conciliacion_archivo, name="conciliacion_archivo"),
    path("sire/", views.estado_sire, name="estado_sire"),
    path("inventario/", views.inventario, name="inventario"),
    path("kardex/<int:pk>/", views.kardex, name="kardex"),
    path("impuestos/", views.impuestos, name="impuestos"),
    path("impuestos/igv/declaracion/", views.registrar_declaracion_igv, name="registrar_declaracion_igv"),
    path("impuestos/igv/declaracion/<int:pk>/anular/", views.anular_registro_621, name="anular_registro_621"),
    path("impuestos/renta/", views.asentar_renta_mes, name="asentar_renta"),
    path("impuestos/renta/pagar/", views.pagar_renta_mes, name="pagar_renta"),
    path("impuestos/igv/pagar/", views.pagar_igv_mes, name="pagar_igv"),
]

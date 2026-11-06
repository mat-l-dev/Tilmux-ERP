from django.urls import path

from . import views

app_name = "compras"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("gastos/nuevo/", views.nuevo_gasto, name="nuevo_gasto"),
    path("importar/", views.importar, name="importar"),
    path("importar/preview/", views.importar_preview, name="importar_preview"),
    path("importar/compra/", views.importar_compra, name="importar_compra"),
    path("importar/guia/", views.vincular_guia, name="vincular_guia"),
    path("gastos/<int:pk>/", views.detalle_gasto, name="detalle_gasto"),
    path("<int:pk>/pagar/", views.pagar_compra, name="pagar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/confirmar/", views.confirmar_compra, name="confirmar"),
    path("<int:pk>/corregir/", views.corregir, name="corregir"),
    path("<int:pk>/anular/", views.anular, name="anular"),
]

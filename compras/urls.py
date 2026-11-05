from django.urls import path

from . import views

app_name = "compras"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("importar/", views.importar, name="importar"),
    path("importar/preview/", views.importar_preview, name="importar_preview"),
    path("importar/compra/", views.importar_compra, name="importar_compra"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/confirmar/", views.confirmar_compra, name="confirmar"),
]

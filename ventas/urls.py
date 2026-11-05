from django.urls import path

from . import views

app_name = "ventas"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/confirmar/", views.confirmar_venta, name="confirmar"),
    path("<int:pk>/nota-credito/", views.nota_credito, name="nota_credito"),
    path("<int:pk>/nota-debito/", views.nota_debito, name="nota_debito"),
]

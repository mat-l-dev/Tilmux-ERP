from django.urls import path

from . import views

app_name = "tesoreria"

urlpatterns = [
    path("", views.movimientos, name="movimientos"),
    path("comparar-banco/", views.comparar_banco, name="comparar_banco"),
    path("conciliaciones/", views.historial_conciliaciones, name="historial_conciliaciones"),
    path("conciliaciones/confirmar/", views.confirmar_conciliacion, name="confirmar_conciliacion"),
    path("conciliaciones/<int:pk>/revertir/", views.revertir_conciliacion, name="revertir_conciliacion"),
]

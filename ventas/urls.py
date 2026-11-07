from django.urls import path

from . import views

app_name = "ventas"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("cuentas-por-cobrar/", views.cuentas_cobrar, name="cuentas_cobrar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/confirmar/", views.confirmar_venta, name="confirmar"),
    path("<int:pk>/cobrar/", views.cobrar, name="cobrar"),
    path("<int:pk>/cobros/<int:cobro_id>/asignar/", views.asignar_cuota, name="asignar_cuota"),
    path("<int:pk>/cuotas/", views.cuotas, name="cuotas"),
    path("<int:pk>/nota-credito/", views.nota_credito, name="nota_credito"),
    path("<int:pk>/nota-debito/", views.nota_debito, name="nota_debito"),
]

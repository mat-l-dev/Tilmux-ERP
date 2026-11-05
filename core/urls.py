from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("empresa/cambiar/", views.cambiar_empresa, name="cambiar_empresa"),
    path("periodos/", views.periodos, name="periodos"),
    path("periodos/<int:pk>/cerrar/", views.cerrar_periodo, name="cerrar_periodo"),
    path("periodos/<int:pk>/reabrir/", views.reabrir_periodo, name="reabrir_periodo"),
    path("proximamente/", views.proximamente, name="proximamente"),
]

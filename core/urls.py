from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("guia/", views.guia, name="guia"),
    path("empresa/cambiar/", views.cambiar_empresa, name="cambiar_empresa"),
    path("periodos/", views.periodos, name="periodos"),
    path("pendientes/", views.pendientes, name="pendientes"),
    path("periodos/<int:pk>/cerrar/", views.cerrar_periodo, name="cerrar_periodo"),
    path("periodos/<int:pk>/revaluar/", views.revaluar_periodo, name="revaluar_periodo"),
    path("periodos/<int:pk>/reabrir/", views.reabrir_periodo, name="reabrir_periodo"),
    path("periodos/cierre/<int:anio>/", views.cerrar_ejercicio, name="cerrar_ejercicio"),
    path(
        "periodos/cierre/<int:anio>/revertir/",
        views.revertir_ejercicio,
        name="revertir_ejercicio",
    ),
    path("proximamente/", views.proximamente, name="proximamente"),
]

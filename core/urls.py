from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("empresa/cambiar/", views.cambiar_empresa, name="cambiar_empresa"),
    path("proximamente/", views.proximamente, name="proximamente"),
]

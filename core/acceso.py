"""Deniega acceso operativo si no hay empresa asignada y protege el admin."""

from django.http import HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin

from .context import empresas_disponibles


class AccesoEmpresaMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        usuario = request.user
        if not usuario.is_authenticated or usuario.is_superuser:
            return None
        ruta = request.resolver_match
        if ruta and ruta.namespace == "admin":
            return HttpResponseForbidden("La administración está reservada a administradores globales.")
        if ruta and (ruta.view_name == "core:panel" or ruta.url_name == "logout"):
            return None
        if not empresas_disponibles(usuario).exists():
            return HttpResponseForbidden("Tu usuario no tiene una empresa activa asignada. Contacta al administrador.")
        return None

"""Usuario de la petición actual, para la auditoría de autoría.

Los servicios reciben el usuario por parámetro cuando se llaman desde un comando.
En una petición web, el middleware lo deja disponible sin cambiar cada firma.
"""

from __future__ import annotations

from contextvars import ContextVar

usuario_actual: ContextVar = ContextVar("usuario_actual", default=None)


class UsuarioActualMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = request.user if request.user.is_authenticated else None
        token = usuario_actual.set(usuario)
        try:
            return self.get_response(request)
        finally:
            usuario_actual.reset(token)

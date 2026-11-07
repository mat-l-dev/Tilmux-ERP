"""Control de escritura según el rol del usuario."""

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import Perfil


def requiere_escritura(view):
    """Bloquea a los usuarios de solo lectura en las pantallas que registran."""

    @wraps(view)
    def _envoltura(request, *args, **kwargs):
        perfil = getattr(request.user, "perfil", None)
        if not request.user.is_superuser and (perfil is None or perfil.empresa_id is None or not perfil.empresa.activa):
            messages.error(request, "Tu usuario no tiene una empresa activa asignada.")
            return redirect("core:panel")
        if perfil is not None and perfil.rol == Perfil.Rol.LECTOR:
            messages.error(request, "Tu usuario es de solo lectura.")
            return redirect("core:panel")
        return view(request, *args, **kwargs)

    return _envoltura

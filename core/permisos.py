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
        if perfil is not None and perfil.rol == Perfil.Rol.LECTOR:
            messages.error(request, "Tu usuario es de solo lectura.")
            return redirect("core:panel")
        return view(request, *args, **kwargs)

    return _envoltura

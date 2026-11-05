"""Contexto compartido por todas las plantillas."""

from __future__ import annotations

from django.http import HttpRequest

from .models import Empresa


def empresa_actual(request: HttpRequest) -> Empresa | None:
    """Devuelve la empresa de la sesión, fijando la primera si no hay elección."""
    if not request.user.is_authenticated:
        return None
    empresas = list(Empresa.objects.filter(activa=True))
    if not empresas:
        return None
    elegida = request.session.get("empresa_id")
    activa = next((e for e in empresas if e.pk == elegida), empresas[0])
    if elegida != activa.pk:
        request.session["empresa_id"] = activa.pk
    return activa


def empresas_context(request: HttpRequest) -> dict:
    activa = empresa_actual(request)
    return {
        "empresas": list(Empresa.objects.filter(activa=True)) if activa else [],
        "empresa_activa": activa,
    }

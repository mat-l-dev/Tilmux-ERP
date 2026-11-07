"""Contexto compartido por todas las plantillas."""

from __future__ import annotations

from datetime import date

from django.http import HttpRequest

from .models import Empresa


def empresas_disponibles(usuario):
    """Restringe los perfiles asignados; conserva acceso heredado sin asignación."""
    empresas = Empresa.objects.filter(activa=True)
    if not usuario.is_authenticated:
        return empresas.none()
    perfil = getattr(usuario, "perfil", None)
    if not usuario.is_superuser and perfil is not None and perfil.empresa_id is not None:
        return empresas.filter(pk=perfil.empresa_id)
    return empresas


def empresa_actual(request: HttpRequest) -> Empresa | None:
    """Devuelve la empresa de la sesión, fijando la primera si no hay elección."""
    if not request.user.is_authenticated:
        return None
    empresas = list(empresas_disponibles(request.user))
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
        "empresas": list(empresas_disponibles(request.user)) if activa else [],
        "empresa_activa": activa,
    }


MESES = (
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Setiembre", "Octubre", "Noviembre", "Diciembre",
)


def periodos_context(request: HttpRequest) -> dict:
    """Opciones de mes para los selectores de la interfaz."""
    hoy = date.today()
    opciones = []
    for pasos in range(24):
        total = hoy.year * 12 + (hoy.month - 1) - pasos
        anio, mes = total // 12, total % 12 + 1
        opciones.append(
            {"valor": f"{anio}-{mes:02d}", "etiqueta": f"{MESES[mes - 1]} {anio}"}
        )
    return {
        "periodos_disponibles": opciones,
        "periodo_seleccionado": request.GET.get("periodo", ""),
    }

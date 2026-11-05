"""Comprobación de salud para el balanceador."""

from django.db import connection
from django.http import JsonResponse


def salud(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover
        return JsonResponse({"estado": "error", "detalle": str(exc)}, status=503)
    return JsonResponse({"estado": "ok"})

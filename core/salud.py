"""Comprobación de salud para el balanceador."""

import logging

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def salud(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # pragma: no cover
        logger.exception("Fallo en la comprobación de salud de la base de datos.")
        return JsonResponse({"estado": "error"}, status=503)
    return JsonResponse({"estado": "ok"})

"""Validación compartida de filtros de consulta."""

import re
from datetime import date


def periodo_mes(texto):
    if not texto:
        return None
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", texto):
        raise ValueError("El período debe tener el formato AAAA-MM.")
    try:
        return date.fromisoformat(f"{texto}-01")
    except ValueError:
        raise ValueError("Indica un período válido.") from None

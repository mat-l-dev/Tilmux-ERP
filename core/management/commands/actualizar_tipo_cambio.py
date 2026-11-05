"""Descarga el tipo de cambio diario publicado por SUNAT."""

from __future__ import annotations

import urllib.request
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import TipoCambio

URL = "https://www.sunat.gob.pe/a/txt/tipoCambio.txt"


class Command(BaseCommand):
    help = "Obtiene el tipo de cambio de SUNAT y lo guarda por fecha."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url", default=URL, help="Origen del archivo de SUNAT."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        solicitud = urllib.request.Request(
            options["url"],
            headers={"User-Agent": "TilmuxERP/1.0 (+https://tilmux.pe)"},
        )
        try:
            with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
                crudo = respuesta.read()
        except Exception as exc:  # pragma: no cover - depende de la red
            raise CommandError(f"No se pudo descargar el tipo de cambio: {exc}") from exc

        texto = crudo.decode("utf-8", errors="replace").strip()
        partes = [p.strip() for p in texto.split("|")]
        if len(partes) < 3:
            raise CommandError(f"Formato inesperado: {texto!r}")

        try:
            fecha = datetime.strptime(partes[0], "%d/%m/%Y").date()
            compra = Decimal(partes[1])
            venta = Decimal(partes[2])
        except (ValueError, ArithmeticError) as exc:
            raise CommandError(f"No se pudo interpretar: {texto!r}") from exc

        registro, creado = TipoCambio.objects.update_or_create(
            fecha=fecha,
            defaults={"compra": compra, "venta": venta, "fuente": "SUNAT"},
        )
        estado = "creado" if creado else "actualizado"
        self.stdout.write(
            self.style.SUCCESS(
                f"Tipo de cambio {estado}: {registro.fecha} "
                f"compra {registro.compra} venta {registro.venta}"
            )
        )

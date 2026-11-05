"""Compara los registros del sistema con las casillas de la vista preliminar."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum

from compras.models import Compra
from compras.models_gasto import Gasto
from core.models import Empresa
from ventas.models import NotaCredito, NotaDebito, Venta

import calendar


class Command(BaseCommand):
    help = "Muestra los totales del periodo con el número de casilla del formulario."

    def add_arguments(self, parser):
        parser.add_argument("--anio", type=int, required=True)
        parser.add_argument("--mes", type=int, required=True)
        parser.add_argument("--ruc", default="20615841961")

    def handle(self, *args, **options):
        empresa = Empresa.objects.filter(ruc=options["ruc"]).first()
        if empresa is None:
            raise CommandError("No existe la empresa indicada.")

        desde = date(options["anio"], options["mes"], 1)
        hasta = date(
            options["anio"],
            options["mes"],
            calendar.monthrange(options["anio"], options["mes"])[1],
        )

        ventas = Venta.objects.filter(
            empresa=empresa, estado=Venta.Estado.CONFIRMADA, fecha__range=(desde, hasta)
        )
        base_ventas = ventas.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")
        igv_ventas = ventas.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        creditos = NotaCredito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).aggregate(b=Sum("base"), i=Sum("igv"))
        base_ventas -= creditos["b"] or Decimal("0")
        igv_ventas -= creditos["i"] or Decimal("0")

        debitos = NotaDebito.objects.filter(
            venta__empresa=empresa, fecha__range=(desde, hasta)
        ).aggregate(b=Sum("base"), i=Sum("igv"))
        base_ventas += debitos["b"] or Decimal("0")
        igv_ventas += debitos["i"] or Decimal("0")

        compras = Compra.objects.filter(
            empresa=empresa, estado=Compra.Estado.CONFIRMADA, fecha__range=(desde, hasta)
        )
        base_compras = compras.aggregate(s=Sum("subtotal"))["s"] or Decimal("0")
        igv_compras = compras.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        gastos = Gasto.objects.filter(
            empresa=empresa, fecha__range=(desde, hasta), igv__gt=0
        )
        base_compras += gastos.aggregate(s=Sum("base"))["s"] or Decimal("0")
        igv_compras += gastos.aggregate(s=Sum("igv"))["s"] or Decimal("0")

        otros_gastos = Gasto.objects.filter(
            empresa=empresa, fecha__range=(desde, hasta), igv=0
        )
        no_gravado = otros_gastos.aggregate(s=Sum("base"))["s"] or Decimal("0")

        resultado = igv_ventas - igv_compras

        self.stdout.write(f"Periodo {options['anio']}-{options['mes']:02d}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Ventas"))
        self.stdout.write(f"  100  Ventas netas gravadas (base)   {base_ventas:>12.2f}")
        self.stdout.write(f"  101  IGV de ventas                  {igv_ventas:>12.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Compras"))
        self.stdout.write(f"  107  Compras gravadas (base)        {base_compras:>12.2f}")
        self.stdout.write(f"  108  IGV de compras                 {igv_compras:>12.2f}")
        self.stdout.write(f"  120  Compras no gravadas            {no_gravado:>12.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resultado"))
        self.stdout.write(f"  140  Saldo a favor / por pagar      {resultado:>12.2f}")

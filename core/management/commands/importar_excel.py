"""Importa las operaciones del Excel contable de TILMUX al libro nuevo."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from openpyxl import load_workbook

from catalogo.models import CuentaTesoreria, Producto, Serie, Tercero
from compras.models import Compra, CompraLinea
from compras.servicios import confirmar as confirmar_compra
from contabilidad.models import Asiento
from contabilidad.servicios import Montos, postear
from core.models import Empresa
from tesoreria.models import MovimientoTesoreria
from tesoreria.servicios import registrar, transferir
from ventas.models import Venta, VentaLinea
from ventas.servicios import confirmar as confirmar_venta

MEDIOS = {"BBVA": "BBVA", "BCP": "BCP", "Caja": "Caja", "Pasarela": "Mercado Pago"}
COMPRAS = {"FACTURA": "Factura", "BOLETA": "Boleta"}


def dec(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"))


def fecha_de(valor) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


class Command(BaseCommand):
    help = "Importa las 23 operaciones del Excel de TILMUX."

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            default=str(Path(settings.BASE_DIR) / "Archivos" / "TILMUX – Contabilidad 2026.xlsx"),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if Asiento.objects.exists():
            raise CommandError(
                "Ya existen asientos. La importación solo corre sobre un libro vacío."
            )

        ruta = Path(options["archivo"])
        if not ruta.exists():
            candidatos = list(Path(settings.BASE_DIR, "Archivos").glob("*.xlsx"))
            if not candidatos:
                raise CommandError("No encuentro el Excel en Archivos/.")
            ruta = candidatos[0]

        empresa = Empresa.objects.get(ruc="20615841961")
        hojas = load_workbook(ruta, data_only=True)
        hoja = hojas["Operaciones"]
        cabeceras = {
            celda.value: celda.column
            for celda in hoja[1]
            if celda.value
        }

        def campo(fila, nombre):
            columna = cabeceras.get(nombre)
            return fila[columna - 1] if columna else None

        self.mercado_libre = self._proveedor(
            "20605980008", "MERCADOLIBRE PERU S.R.L."
        )
        self.cliente = self._cliente("20614892405", "MAQUINARIAS Y DIVERSOS S.A.C.")
        self.empresa = empresa
        self.procesadas = 0

        for fila in hoja.iter_rows(min_row=2, values_only=True):
            if not fila[0]:
                continue
            tipo = campo(fila, "Tipo de operación")
            if not tipo:
                continue
            fecha = fecha_de(campo(fila, "Fecha"))
            importe = dec(campo(fila, "Importe total (S/)"))
            base = dec(campo(fila, "Base"))
            igv = dec(campo(fila, "IGV"))
            medio = campo(fila, "Medio de pago")
            destino = campo(fila, "Medio destino")
            comprobante = campo(fila, "Serie y número") or ""
            detalle = campo(fila, "Detalle") or ""
            numero_fila = int(fila[0])

            if tipo == "Capital suscrito en la constitución":
                postear(
                    empresa=empresa,
                    fecha=fecha,
                    tipo="CAPITAL_SUSCRITO",
                    glosa=detalle,
                    montos=Montos(total=importe),
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Aporte de capital recibido":
                registrar(
                    empresa=empresa,
                    cuenta=self._cuenta(medio),
                    fecha=fecha,
                    tipo="INGRESO",
                    importe=importe,
                    concepto=detalle,
                    tipo_regla="APORTE_CAPITAL",
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Préstamo de socio recibido":
                registrar(
                    empresa=empresa,
                    cuenta=self._cuenta(medio),
                    fecha=fecha,
                    tipo="INGRESO",
                    importe=importe,
                    concepto=detalle,
                    tipo_regla="PRESTAMO_SOCIO",
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Dinero de socio por reembolsar":
                registrar(
                    empresa=empresa,
                    cuenta=self._cuenta(medio),
                    fecha=fecha,
                    tipo="INGRESO",
                    importe=importe,
                    concepto=detalle,
                    tipo_regla="REEMBOLSO_SOCIO",
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Comisión o gasto bancario":
                registrar(
                    empresa=empresa,
                    cuenta=self._cuenta(medio),
                    fecha=fecha,
                    tipo="EGRESO",
                    importe=importe,
                    concepto=detalle or "Comisión bancaria",
                    tipo_regla="GASTO_SIN_IGV",
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Comisión de pasarela de pagos":
                registrar(
                    empresa=empresa,
                    cuenta=self._cuenta(medio),
                    fecha=fecha,
                    tipo="EGRESO",
                    importe=importe,
                    concepto=detalle,
                    tipo_regla="COMISION_PASARELA",
                    base=base,
                    igv=igv,
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            elif tipo == "Transferencia entre cuentas propias":
                transferir(
                    empresa=empresa,
                    origen=self._cuenta(medio),
                    destino=self._cuenta(destino),
                    fecha=fecha,
                    importe=importe,
                    concepto=detalle,
                )
            elif tipo == "Compra de mercadería":
                self._compra(
                    fecha=fecha,
                    base=base,
                    igv=igv,
                    total=importe,
                    comprobante=comprobante,
                    detalle=detalle,
                    medio=medio,
                )
            elif tipo == "Venta de mercadería":
                self._venta(
                    fecha=fecha,
                    base=base,
                    igv=igv,
                    total=importe,
                    comprobante=comprobante,
                    detalle=detalle,
                )
            elif tipo == "Renta RER del mes":
                postear(
                    empresa=empresa,
                    fecha=fecha,
                    tipo="RENTA_MENSUAL",
                    glosa=detalle,
                    montos=Montos(total=importe),
                    origen_tipo="IMPORTACION",
                    origen_id=numero_fila,
                )
            else:
                self.stdout.write(f"  omitida ({numero_fila}): {tipo}")
                continue
            self.procesadas += 1

        self._actualizar_series()
        self.stdout.write(
            self.style.SUCCESS(f"{self.procesadas} operaciones importadas.")
        )
        self._resumen(empresa)

    # --- ayudas -------------------------------------------------------

    def _cuenta(self, medio: str) -> CuentaTesoreria:
        nombre = MEDIOS.get(medio, medio)
        return CuentaTesoreria.objects.get(empresa=self.empresa, nombre=nombre)

    def _proveedor(self, ruc: str, nombre: str) -> Tercero:
        tercero, _ = Tercero.objects.get_or_create(
            tipo_doc="RUC",
            numero_doc=ruc,
            defaults={"nombre": nombre, "rol": "PROVEEDOR"},
        )
        return tercero

    def _cliente(self, ruc: str, nombre: str) -> Tercero:
        tercero, _ = Tercero.objects.get_or_create(
            tipo_doc="RUC",
            numero_doc=ruc,
            defaults={"nombre": nombre, "rol": "CLIENTE"},
        )
        return tercero

    def _producto(self, detalle: str) -> Producto:
        sku = "TIL-000002" if "Standard" in detalle else "TIL-000001"
        return Producto.objects.get(sku=sku)

    def _compra(self, *, fecha, base, igv, total, comprobante, detalle, medio):
        serie, numero = ("", "")
        tipo_doc = "OTRO"
        if "-" in comprobante and not comprobante.lower().startswith("pendiente"):
            serie, numero = comprobante.split("-", 1)
            tipo_doc = "FACTURA" if serie.upper().startswith(("F", "E")) else "BOLETA"

        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=self.mercado_libre,
            fecha=fecha,
            tipo_doc=tipo_doc,
            serie=serie,
            numero=numero,
            glosa=detalle[:255],
        )
        CompraLinea.objects.create(
            compra=compra,
            orden=1,
            producto=self._producto(detalle),
            cantidad=Decimal("1"),
            precio_unitario=base,
            base=base,
            igv=igv,
            total=total,
        )
        confirmar_compra(compra)
        registrar(
            empresa=self.empresa,
            cuenta=self._cuenta(medio),
            fecha=fecha,
            tipo="EGRESO",
            importe=total,
            concepto=f"Pago compra {comprobante}".strip(),
            origen_tipo="COMPRA",
            origen_id=compra.pk,
        )

    def _venta(self, *, fecha, base, igv, total, comprobante, detalle):
        serie, numero = comprobante.split("-", 1)
        venta = Venta.objects.create(
            empresa=self.empresa,
            cliente=self.cliente,
            cliente_nombre=self.cliente.nombre,
            fecha=fecha,
            tipo_doc="FACTURA",
            serie=serie,
            numero=numero,
            condicion="CONTADO",
            cuenta=self._cuenta("Pasarela"),
            canal="TARJETA",
            glosa=detalle[:255],
        )
        VentaLinea.objects.create(
            venta=venta,
            orden=1,
            producto=self._producto(detalle),
            cantidad=Decimal("1"),
            precio_unitario=total,
            base=base,
            igv=igv,
            total=total,
        )
        confirmar_venta(venta)

    def _actualizar_series(self):
        for serie in Serie.objects.filter(empresa=self.empresa):
            ultimo = 0
            if serie.tipo == Serie.Tipo.FACTURA:
                numeros = (
                    Venta.objects.filter(empresa=self.empresa, serie=serie.serie)
                    .values_list("numero", flat=True)
                )
                ultimo = max((int(n) for n in numeros if n.isdigit()), default=0)
            serie.ultimo_numero = ultimo
            serie.save(update_fields=["ultimo_numero"])

    def _resumen(self, empresa):
        from contabilidad.models import AsientoLinea
        from django.db.models import Sum

        def saldo(codigos):
            filas = AsientoLinea.objects.filter(
                asiento__empresa=empresa,
                asiento__estado="CONFIRMADO",
                cuenta__codigo__in=codigos,
            ).aggregate(d=Sum("debe"), h=Sum("haber"))
            return dec((filas["d"] or 0) - (filas["h"] or 0))

        efectivo = saldo(["101", "1031", "1061"])
        inventario = saldo(["20111"])
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Saldos resultantes"))
        self.stdout.write(f"  Efectivo     {efectivo:>10}")
        self.stdout.write(f"  Inventario   {inventario:>10}")
        self.stdout.write(f"  Asientos     {Asiento.objects.count():>10}")
        self.stdout.write(
            f"  Movimientos  {MovimientoTesoreria.objects.count():>10}"
        )

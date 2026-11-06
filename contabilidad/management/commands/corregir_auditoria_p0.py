"""Corrige los hallazgos P0 de la auditoría de TILMUX.

La corrección es idempotente y deja historial en cada paso. No borra asientos
ni líneas: anula el asiento duplicado y reclasifica la línea mal contabilizada.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from compras.models_gasto import Gasto
from contabilidad.impuestos import saldo_cuenta
from contabilidad.models import Asiento, AsientoLinea, Cuenta
from contabilidad.servicios import (
    anular_asiento,
    corregir_glosa_asiento,
    reclasificar_linea_asiento,
)
from core.models import Empresa, HistorialDocumento, Periodo
from reportes.casillas import calcular

CERO = Decimal("0.00")
FECHA_CORTE = date(2026, 11, 30)
DOC_FV20 = "FV20-01490476"
DOC_FV15 = "FV15-01525308"


class Command(BaseCommand):
    help = "Corrige los asientos 37/38, las provisiones y el número de FV20."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida y muestra el resultado, pero revierte todos los cambios.",
        )
        parser.add_argument(
            "--usuario",
            default="",
            help="Usuario que firma el historial (por defecto, el primer superusuario).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        empresa = Empresa.objects.get(ruc="20615841961")
        usuario = self._usuario(options["usuario"])
        dry_run = options["dry_run"]

        gastos = {
            g.pk: g
            for g in Gasto.objects.select_for_update()
            .filter(empresa=empresa)
            .select_related("proveedor")
        }
        asientos = {
            a.numero: a
            for a in Asiento.objects.select_for_update()
            .filter(empresa=empresa, numero__in=[32, 33, 36, 37, 38, 39, 41])
            .prefetch_related("lineas__cuenta")
        }
        self._validar_estado(gastos, asientos)
        periodo_octubre = Periodo.objects.get(empresa=empresa, anio=2026, mes=10)

        cambios: list[str] = []

        # 1. Número real de la factura FV20 según el XML del proveedor.
        g9 = gastos[9]
        if (g9.serie, g9.numero) != ("FV20", "01490476"):
            anterior = f"{g9.serie}-{g9.numero}"
            if (
                Gasto.objects.filter(
                    empresa=empresa,
                    tipo_doc=g9.tipo_doc,
                    serie="FV20",
                    numero="01490476",
                )
                .exclude(pk=g9.pk)
                .exists()
            ):
                raise CommandError(
                    "Ya existe otro gasto con el número FV20-01490476."
                )
            g9.serie = "FV20"
            g9.numero = "01490476"
            g9.glosa = "Mantenimiento de cuenta BCP – FV20-01490476"
            g9.save(update_fields=["serie", "numero", "glosa"])
            self._hist_gasto(
                g9,
                "CORRECCION",
                f"Documento {anterior} → FV20-01490476 según XML del proveedor.",
                usuario,
            )
            cambios.append(f"Gasto 9: {anterior} -> FV20-01490476")

        # 2. Provisiones, facturas finales y periodo económico.
        provisiones = {3: 9, 12: 11, 13: 11}
        for gasto_id, origen_id in provisiones.items():
            gasto = gastos[gasto_id]
            origen = gastos[origen_id]
            campos = []
            if not gasto.provision:
                gasto.provision = True
                campos.append("provision")
            if gasto.gasto_origen_id != origen.pk:
                gasto.gasto_origen = origen
                campos.append("gasto_origen")
            if gasto.estado != Gasto.Estado.PROVISION:
                gasto.estado = Gasto.Estado.PROVISION
                campos.append("estado")
            if gasto.fecha_devengado is None:
                gasto.fecha_devengado = gasto.fecha
                campos.append("fecha_devengado")
            if campos:
                gasto.save(update_fields=campos)
                self._hist_gasto(
                    gasto,
                    "CORRECCION",
                    f"Marcada como provisión de {origen.serie}-{origen.numero}. "
                    f"Campos: {', '.join(campos)}.",
                    usuario,
                )
                cambios.append(
                    f"Gasto {gasto_id}: provisión de "
                    f"{origen.serie}-{origen.numero}"
                )

        for gasto_id, fecha_devengado in ((9, date(2026, 9, 30)), (11, date(2026, 10, 31))):
            gasto = gastos[gasto_id]
            campos = []
            if gasto.provision:
                gasto.provision = False
                campos.append("provision")
            if gasto.gasto_origen_id is not None:
                gasto.gasto_origen = None
                campos.append("gasto_origen")
            if gasto.estado != Gasto.Estado.PAGADO:
                gasto.estado = Gasto.Estado.PAGADO
                campos.append("estado")
            if gasto.fecha_devengado != fecha_devengado:
                gasto.fecha_devengado = fecha_devengado
                campos.append("fecha_devengado")
            if campos:
                gasto.save(update_fields=campos)
                self._hist_gasto(
                    gasto,
                    "CORRECCION",
                    f"Factura final; periodo económico {fecha_devengado}. "
                    f"Campos: {', '.join(campos)}.",
                    usuario,
                )
                cambios.append(
                    f"Gasto {gasto_id}: periodo económico {fecha_devengado}"
                )

        # El resto de gastos ya pagados no son provisiones.
        for gasto in gastos.values():
            if gasto.pk in provisiones or gasto.pk in (9, 11):
                continue
            campos = []
            if gasto.provision:
                gasto.provision = False
                campos.append("provision")
            if gasto.gasto_origen_id is not None:
                gasto.gasto_origen = None
                campos.append("gasto_origen")
            if gasto.estado != Gasto.Estado.PAGADO:
                gasto.estado = Gasto.Estado.PAGADO
                campos.append("estado")
            if campos:
                gasto.save(update_fields=campos)
                self._hist_gasto(
                    gasto,
                    "CORRECCION",
                    f"Gasto pagado. Campos: {', '.join(campos)}.",
                    usuario,
                )

        # 3. Asiento 37: pago duplicado de FV20. El pago real es el asiento 12.
        a37 = asientos[37]
        if a37.estado != Asiento.Estado.ANULADO:
            anular_asiento(
                a37,
                "Duplicado: el pago real de FV20 está en el asiento 12 del "
                "30/09 y su aplicación en el asiento 41. No hubo un segundo "
                "débito bancario de S/ 18 el 31/10.",
                usuario=usuario,
            )
            cambios.append("Asiento 37: ANULADO (pago duplicado de FV20)")

        # 4. Asiento 38: la provisión de 10 se debitó contra banco; debe ir
        #    contra la cuenta por pagar 4212. El pago real está en el asiento 32.
        a38 = asientos[38]
        linea_banco = a38.lineas.filter(cuenta__codigo="1061", haber=Decimal("10.00")).first()
        if linea_banco is not None:
            cuenta_4212 = Cuenta.objects.get(version="2026", codigo="4212")
            reclasificar_linea_asiento(
                linea_banco,
                cuenta_4212,
                "La provisión de S/ 10 del 03/10 se registró contra banco; "
                "debe quedar contra la cuenta por pagar 4212. El pago real "
                "está en el asiento 32.",
                glosa="Provisión envío estado de cuenta BCP – FV15-01525308",
                usuario=usuario,
            )
            cambios.append("Asiento 38: línea 1061 -> 4212 (provisión, no pago)")

        # 5. Asiento 33: el débito bancario real es del 31/10, no del 04/11.
        a33 = asientos[33]
        if a33.fecha != date(2026, 10, 31) or a33.periodo_id != periodo_octubre.pk:
            anterior = f"{a33.fecha} / periodo {a33.periodo.etiqueta}"
            a33.fecha = date(2026, 10, 31)
            a33.periodo = periodo_octubre
            a33.save(update_fields=["fecha", "periodo"])
            HistorialDocumento.objects.create(
                empresa=empresa,
                tipo=HistorialDocumento.Tipo.ASIENTO,
                documento_id=a33.pk,
                usuario=usuario,
                accion="CORRECCION",
                detalle=(
                    f"Fecha y periodo: {anterior} → 2026-10-31 / 2026-10. "
                    "El débito bancario de S/ 18 es del 31/10."
                ),
            )
            cambios.append("Asiento 33: fecha 31/10 y periodo 2026-10")

        # 6. Glosas con el número correcto de FV20 y la naturaleza de la provisión.
        glosas = (
            (
                36,
                f"{DOC_FV20} · BCP – provisión",
                "Corregir el número del comprobante según el XML del proveedor.",
            ),
            (
                41,
                f"Aplicación del pago 30/09 a {DOC_FV20}",
                "Corregir el número del comprobante según el XML del proveedor.",
            ),
            (
                39,
                f"Aplicación de provisión 03/10 a {DOC_FV15}",
                "La línea aplicada es una provisión, no un pago directo.",
            ),
        )
        for numero, glosa, motivo in glosas:
            asiento = asientos[numero]
            if asiento.glosa != glosa:
                corregir_glosa_asiento(asiento, glosa, motivo, usuario=usuario)
                cambios.append(f"Asiento {numero}: glosa corregida")

        self._validar_resultado(empresa)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: cambios revertidos."))
            transaction.set_rollback(True)
            return

        self.stdout.write(self.style.SUCCESS("Corrección P0 aplicada."))
        for cambio in cambios:
            self.stdout.write(f"  · {cambio}")
        if not cambios:
            self.stdout.write("  · Sin cambios: la base ya estaba corregida.")

    def _usuario(self, username: str):
        usuarios = get_user_model().objects
        if username:
            usuario = usuarios.filter(username=username).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {username}.")
            return usuario
        return usuarios.filter(is_superuser=True).order_by("pk").first()

    def _hist_gasto(self, gasto, accion: str, detalle: str, usuario) -> None:
        HistorialDocumento.objects.create(
            empresa=gasto.empresa,
            tipo=HistorialDocumento.Tipo.GASTO,
            documento_id=gasto.pk,
            usuario=usuario,
            accion=accion,
            detalle=detalle,
        )

    def _validar_estado(self, gastos, asientos) -> None:
        faltantes = [pk for pk in (3, 9, 11, 12, 13) if pk not in gastos]
        if faltantes:
            raise CommandError(f"Faltan gastos esperados: {faltantes}.")
        faltantes = [n for n in (32, 33, 36, 37, 38, 39, 41) if n not in asientos]
        if faltantes:
            raise CommandError(f"Faltan asientos esperados: {faltantes}.")
        esperados = {3: "18.00", 9: "18.00", 11: "28.00", 12: "10.00", 13: "18.00"}
        for pk, total in esperados.items():
            if gastos[pk].total != Decimal(total):
                raise CommandError(
                    f"El gasto {pk} tiene total {gastos[pk].total}, se esperaba {total}."
                )
        a37 = asientos[37]
        if a37.estado == Asiento.Estado.CONFIRMADO:
            debe = sum((linea.debe for linea in a37.lineas.all()), CERO)
            haber = sum((linea.haber for linea in a37.lineas.all()), CERO)
            if debe != Decimal("18.00") or haber != Decimal("18.00"):
                raise CommandError("El asiento 37 no cuadra con S/ 18.00.")
        a38 = asientos[38]
        if a38.estado == Asiento.Estado.CONFIRMADO:
            tiene_10 = any(
                linea.cuenta.codigo in ("1061", "4212")
                and linea.haber == Decimal("10.00")
                for linea in a38.lineas.all()
            )
            if not tiene_10:
                raise CommandError("El asiento 38 no tiene el crédito de S/ 10.00.")

    def _validar_resultado(self, empresa) -> None:
        esperado = {
            "4212": CERO,
            "1061": Decimal("-901.60"),
            "40111": Decimal("22.05"),
            "40171": Decimal("17.95"),
        }
        for codigo, valor in esperado.items():
            saldo = saldo_cuenta(empresa, codigo, FECHA_CORTE)
            if saldo != valor:
                raise CommandError(
                    f"Saldo {codigo}: S/ {saldo}, se esperaba S/ {valor}."
                )
        casillas = {
            9: Decimal("60.00"),
            10: Decimal("43.00"),
            11: Decimal("28.00"),
        }
        for mes, valor in casillas.items():
            datos = calcular(empresa, 2026, mes)
            if datos["no_gravado"] != valor:
                raise CommandError(
                    f"Casilla 120 de {mes:02d}/2026: S/ {datos['no_gravado']}, "
                    f"se esperaba S/ {valor}."
                )
        totales = AsientoLinea.objects.filter(
            asiento__empresa=empresa,
            asiento__estado=Asiento.Estado.CONFIRMADO,
        ).aggregate(debe=Sum("debe"), haber=Sum("haber"))
        if (totales["debe"] or CERO) != (totales["haber"] or CERO):
            raise CommandError(
                f"La balanza no cuadra: D {totales['debe']} / H {totales['haber']}."
            )

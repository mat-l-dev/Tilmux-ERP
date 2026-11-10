"""Consulta de movimientos registrados, sin asumir el saldo del banco."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalogo.models import CuentaTesoreria
from contabilidad.servicios import ContabilidadError
from core.context import empresa_actual
from core.models import Perfil
from core.permisos import requiere_escritura

from .conciliacion import ConciliacionError, buscar_candidatos, confirmar, revertir
from .filtros import filtrar_movimientos
from .forms import (
    BuscarOperacionBancariaForm,
    ConfirmarConciliacionForm,
    RestitucionSocioForm,
    RevertirConciliacionForm,
)
from .models import ConciliacionBancaria, MovimientoTesoreria, RestitucionSocio
from .origenes import enlazar_documentos
from .restituciones import RestitucionError, obligaciones, reembolsos_registrados, registrar_restitucion


@login_required
def movimientos(request):
    empresa = empresa_actual(request)
    cuentas = CuentaTesoreria.objects.filter(empresa=empresa).order_by("nombre", "pk")
    movimientos = MovimientoTesoreria.objects.filter(
        empresa=empresa, cuenta__empresa=empresa,
    ).select_related("cuenta").annotate(
        conciliacion_activa=Exists(ConciliacionBancaria.objects.filter(
            empresa=empresa, movimiento_id=OuterRef("pk"), activa=True,
        )),
    ).order_by("-fecha", "-pk")
    resumenes = {
        item["cuenta_id"]: item
        for item in movimientos.order_by().values("cuenta_id").annotate(
            ingresos=Sum("importe", filter=Q(tipo=MovimientoTesoreria.Tipo.INGRESO)),
            egresos=Sum("importe", filter=Q(tipo=MovimientoTesoreria.Tipo.EGRESO)),
        )
    }
    filas = []
    for cuenta in cuentas:
        resumen = resumenes.get(cuenta.pk, {})
        ingresos, egresos = resumen.get("ingresos") or Decimal("0"), resumen.get("egresos") or Decimal("0")
        filas.append({"cuenta": cuenta, "ingresos": ingresos, "egresos": egresos, "neto": ingresos - egresos})

    cuenta_id = request.GET.get("cuenta", "")
    if cuenta_id:
        if cuenta_id.isascii() and cuenta_id.isdecimal() and len(cuenta_id) <= 18:
            movimientos = movimientos.filter(cuenta_id=int(cuenta_id))
        else:
            movimientos = movimientos.none()
    movimientos, errores_filtro = filtrar_movimientos(movimientos, request.GET)
    pagina = Paginator(movimientos, 30).get_page(request.GET.get("pagina"))
    pagina.object_list = list(pagina.object_list)
    enlazar_documentos(empresa=empresa, movimientos=pagina.object_list)
    return render(request, "tesoreria/movimientos.html", {
        "filas": filas, "pagina": pagina, "cuenta_id": cuenta_id, "errores_filtro": errores_filtro,
    })


@login_required
def comparar_banco(request):
    empresa = empresa_actual(request)
    formulario = BuscarOperacionBancariaForm(
        request.POST if request.method == "POST" else None,
        empresa=empresa, initial={"cuenta": request.GET.get("cuenta")},
    )
    candidatos = None
    cantidad = 0
    datos_bancarios = None
    if request.method == "POST" and formulario.is_valid():
        consulta = buscar_candidatos(empresa=empresa, **formulario.cleaned_data).annotate(
            conciliacion_activa=Exists(ConciliacionBancaria.objects.filter(
                empresa=empresa, movimiento_id=OuterRef("pk"), activa=True,
            )),
        )
        cantidad = consulta.count()
        candidatos = list(consulta[:100])
        enlazar_documentos(empresa=empresa, movimientos=candidatos)
        datos_bancarios = formulario.cleaned_data
    perfil = getattr(request.user, "perfil", None)
    return render(request, "tesoreria/comparar_banco.html", {
        "formulario": formulario, "candidatos": candidatos, "cantidad": cantidad,
        "datos_bancarios": datos_bancarios, "puede_escribir": perfil is None or perfil.rol != Perfil.Rol.LECTOR,
    })


@login_required
@requiere_escritura
@require_POST
def confirmar_conciliacion(request):
    empresa = empresa_actual(request)
    formulario = ConfirmarConciliacionForm(request.POST, empresa=empresa)
    if formulario.is_valid():
        datos = formulario.cleaned_data.copy()
        datos.pop("confirmo")
        try:
            confirmar(empresa=empresa, usuario=request.user, **datos)
        except ConciliacionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Conciliación guardada con su referencia bancaria.")
            return redirect("tesoreria:historial_conciliaciones")
    else:
        messages.error(request, "Revisa los datos, la referencia y la confirmación antes de conciliar.")
    return redirect("tesoreria:comparar_banco")


@login_required
def obligaciones_socios(request):
    """Deudas con el socio pendientes de restitución y pagos ya registrados."""
    empresa = empresa_actual(request)
    return render(
        request,
        "tesoreria/obligaciones.html",
        {
            "pendientes": obligaciones(empresa),
            "pagos": reembolsos_registrados(empresa)[:50],
            "puede_escribir": _puede_escribir(request),
        },
    )


@login_required
@requiere_escritura
def restitucion_socio(request):
    """Registra el pago de 4411/4419 con el voucher bancario obligatorio."""
    empresa = empresa_actual(request)
    inicial = {"tipo": request.GET.get("tipo") or RestitucionSocio.Tipo.PRESTAMO_SOCIO}
    formulario = RestitucionSocioForm(
        request.POST if request.method == "POST" else None, empresa=empresa, initial=inicial
    )
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            restitucion = registrar_restitucion(
                empresa=empresa,
                tipo=datos["tipo"],
                cuenta=datos["cuenta"],
                fecha_hora=datos["fecha_hora"],
                numero_operacion=datos["numero_operacion"],
                cuenta_destino=datos["cuenta_destino"],
                beneficiario=datos["beneficiario"],
                importe=datos["importe"],
                concepto=datos["concepto"],
                usuario=request.user,
            )
        except (RestitucionError, ContabilidadError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Restitución registrada por S/ {restitucion.importe}. "
                f"Asiento N.º {restitucion.asiento.numero}. La obligación quedó cancelada.",
            )
            return redirect("tesoreria:obligaciones_socios")
    elif request.method == "POST":
        messages.error(request, "Completa todos los datos del voucher; sin ellos no se registra el pago.")

    return render(
        request,
        "tesoreria/restitucion_socio.html",
        {
            "formulario": formulario,
            "pendientes": obligaciones(empresa),
        },
    )


def _puede_escribir(request) -> bool:
    perfil = getattr(request.user, "perfil", None)
    return perfil is None or perfil.rol != Perfil.Rol.LECTOR


@login_required
def historial_conciliaciones(request):
    empresa = empresa_actual(request)
    registros = ConciliacionBancaria.objects.filter(empresa=empresa).select_related(
        "cuenta", "movimiento", "creado_por", "revertido_por",
    ).order_by("-creado", "-pk")
    pagina = Paginator(registros, 30).get_page(request.GET.get("pagina"))
    perfil = getattr(request.user, "perfil", None)
    return render(request, "tesoreria/conciliaciones.html", {
        "pagina": pagina, "puede_escribir": perfil is None or perfil.rol != Perfil.Rol.LECTOR,
    })


@login_required
@requiere_escritura
@require_POST
def revertir_conciliacion(request, pk):
    empresa = empresa_actual(request)
    get_object_or_404(ConciliacionBancaria, pk=pk, empresa=empresa)
    formulario = RevertirConciliacionForm(request.POST)
    if formulario.is_valid():
        try:
            revertir(
                empresa=empresa, conciliacion_id=pk, motivo=formulario.cleaned_data["motivo"], usuario=request.user,
            )
        except ConciliacionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Conciliación revertida; el historial se conserva.")
    else:
        messages.error(request, "Indica un motivo de reversión válido.")
    return redirect("tesoreria:historial_conciliaciones")

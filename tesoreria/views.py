"""Consulta de movimientos registrados, sin asumir el saldo del banco."""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render

from catalogo.models import CuentaTesoreria
from core.context import empresa_actual

from .conciliacion import buscar_candidatos
from .forms import BuscarOperacionBancariaForm
from .models import MovimientoTesoreria


@login_required
def movimientos(request):
    empresa = empresa_actual(request)
    cuentas = CuentaTesoreria.objects.filter(empresa=empresa).order_by("nombre", "pk")
    movimientos = MovimientoTesoreria.objects.filter(
        empresa=empresa, cuenta__empresa=empresa,
    ).select_related("cuenta").order_by("-fecha", "-pk")
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
    pagina = Paginator(movimientos, 30).get_page(request.GET.get("pagina"))
    return render(request, "tesoreria/movimientos.html", {
        "filas": filas, "pagina": pagina, "cuenta_id": cuenta_id,
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
    if request.method == "POST" and formulario.is_valid():
        consulta = buscar_candidatos(empresa=empresa, **formulario.cleaned_data)
        cantidad = consulta.count()
        candidatos = list(consulta[:100])
    return render(request, "tesoreria/comparar_banco.html", {
        "formulario": formulario, "candidatos": candidatos, "cantidad": cantidad,
    })

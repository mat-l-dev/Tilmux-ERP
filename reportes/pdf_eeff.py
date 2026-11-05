"""Genera los estados financieros en PDF con ReportLab."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _importe(valor) -> str:
    texto = f"{float(valor):,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _tabla(filas, estilos, subtotales=(), totales=()):
    datos = [["Concepto", "Importe"]]
    for concepto, importe in filas:
        datos.append([concepto, _importe(importe)])

    tabla = Table(datos, colWidths=[120 * mm, 40 * mm], hAlign="LEFT")
    estilo = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#555555")),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]
    for indice, (concepto, _) in enumerate(filas, start=1):
        if concepto in subtotales:
            estilo.append(("FONT", (0, indice), (-1, indice), "Helvetica-Bold", 8.5))
            estilo.append(("LINEABOVE", (0, indice), (-1, indice), 0.4, colors.grey))
        if concepto in totales:
            estilo.append(("FONT", (0, indice), (-1, indice), "Helvetica-Bold", 10))
            estilo.append(("LINEABOVE", (0, indice), (-1, indice), 0.8, colors.black))
    tabla.setStyle(TableStyle(estilo))
    return tabla


def generar(datos, empresa) -> bytes:
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Estados financieros {empresa.razon_social}",
    )
    estilos = getSampleStyleSheet()
    historia = [
        Paragraph(empresa.razon_social, estilos["Title"]),
        Paragraph(f"RUC {empresa.ruc} · {empresa.get_regimen_display()}", estilos["Normal"]),
        Paragraph(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} · en soles",
            estilos["Normal"],
        ),
        Spacer(1, 14),
    ]

    situacion = [(f"{a['codigo']} {a['nombre']}", a["importe"]) for a in datos["activo_corriente"]]
    situacion.append(("Total activo corriente", datos["total_activo_corriente"]))
    situacion += [(f"{a['codigo']} {a['nombre']}", a["importe"]) for a in datos["activo_no_corriente"]]
    situacion.append(("Total activo no corriente", datos["total_activo_no_corriente"]))
    situacion.append(("Total activo", datos["total_activo"]))
    situacion += [(f"{p['codigo']} {p['nombre']}", p["importe"]) for p in datos["pasivo"]]
    situacion.append(("Total pasivo", datos["total_pasivo"]))
    situacion += [(f"{p['codigo']} {p['nombre']}", p["importe"]) for p in datos["patrimonio"]]
    situacion.append(("Resultado acumulado", datos["resultado_acumulado"]))
    situacion.append(("Total pasivo y patrimonio", datos["total_pasivo_patrimonio"]))

    historia.append(Paragraph("Estado de situación financiera", estilos["Heading2"]))
    historia.append(
        _tabla(
            situacion,
            estilos,
            subtotales={"Total activo corriente", "Total activo no corriente", "Total pasivo"},
            totales={"Total activo", "Total pasivo y patrimonio"},
        )
    )
    historia.append(Spacer(1, 12))

    resultados = [
        ("Ingresos por ventas", datos["ingresos_ventas"]),
        ("Costo de ventas", -datos["costo_ventas"]),
        ("Gastos de operación", -datos["gastos_operativos"]),
        ("Otros ingresos operativos", datos["otros_ingresos"]),
        ("Resultado de operación", datos["resultado_operacion"]),
        ("Ingresos financieros", datos["ingresos_financieros"]),
        ("Gastos financieros", -datos["gastos_financieros"]),
        ("Resultado antes de impuesto", datos["resultado_antes_impuesto"]),
        ("Impuesto a las ganancias", -datos["gasto_impuesto"]),
        ("Resultado del periodo", datos["resultado_neto"]),
    ]
    historia.append(Paragraph("Estado de resultados", estilos["Heading2"]))
    historia.append(
        _tabla(
            resultados,
            estilos,
            subtotales={"Resultado de operación"},
            totales={"Resultado del periodo"},
        )
    )

    historia.append(PageBreak())

    historia.append(Paragraph("Estado de cambios en el patrimonio", estilos["Heading2"]))
    historia.append(
        _tabla(
            [(c["concepto"], c["importe"]) for c in datos["cambios"]],
            estilos,
            totales={"Saldo al cierre"},
        )
    )
    historia.append(Spacer(1, 12))

    historia.append(Paragraph("Estado de flujo de efectivo", estilos["Heading2"]))
    historia.append(
        _tabla(
            [(f["concepto"], f["importe"]) for f in datos["flujo"]],
            estilos,
            subtotales={"Flujo de operación", "Flujo de financiación"},
            totales={"Efectivo al cierre"},
        )
    )

    notas = [
        "<b>1. Base de preparación.</b> Estados financieros preparados conforme a la "
        "Norma de Información Financiera para microempresas, con el PCGE 2026 aplicado "
        "anticipadamente. Se presentan en soles.",
        f"<b>2. Efectivo.</b> El saldo de S/ {_importe(datos['efectivo'])} incluye caja, "
        "efectivo en tránsito y depósitos bancarios.",
        "<b>3. Inventarios.</b> Valorizados al costo de adquisición con costos de "
        "internamiento, método PEPS. Al cierre se compara con el valor neto realizable.",
        "<b>4. Impuestos.</b> El IGV se determina por diferencias entre el impuesto de "
        "ventas y el crédito de compras con factura. Las boletas no otorgan crédito fiscal. "
        "La renta del régimen especial equivale al 1,5 % de los ingresos netos.",
        "<b>5. Moneda extranjera.</b> Las operaciones en dólares se convierten al tipo de "
        "cambio de SUNAT y los saldos pendientes se revalúan al cierre.",
    ]
    historia.append(Spacer(1, 12))
    historia.append(Paragraph("Notas a los estados financieros", estilos["Heading2"]))
    for nota in notas:
        historia.append(Paragraph(nota, estilos["BodyText"]))
        historia.append(Spacer(1, 4))

    documento.build(historia)
    return buffer.getvalue()

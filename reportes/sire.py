"""Lectura de la propuesta del SIRE descargada como Excel o CSV.

SUNAT entrega la propuesta del RVIE (ventas) y del RCE (compras) en Excel.
El formato exacto cambia con las actualizaciones del SIRE, así que en vez de
depender de posiciones fijas se detectan las columnas por su cabecera.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

# Columnas que no forman parte de la base gravada ni del crédito fiscal.
EXCLUIR = (
    "no gravad",
    "exonerad",
    "inafect",
    "gratuit",
    "descuento",
    "retenci",
    "percepci",
    "detracci",
)


class ArchivoInvalido(Exception):
    pass


def _normalizar(texto) -> str:
    return " ".join(str(texto or "").strip().lower().split())


def _limpio(texto) -> str:
    return " ".join(str(texto or "").strip().split())


def _es_fila_total(fila: list) -> bool:
    primer_valor = next((_normalizar(celda) for celda in fila[:2] if _normalizar(celda)), "")
    return primer_valor in {"total", "totales", "total general", "total del periodo", "total del período"}


def leer_filas(archivo) -> list[list]:
    nombre = (archivo.name or "").lower()
    contenido = archivo.read()
    if not contenido:
        raise ArchivoInvalido("El archivo está vacío.")

    if nombre.endswith((".xlsx", ".xlsm")):
        try:
            libro = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
        except Exception as exc:  # archivo corrupto o que no es Excel
            raise ArchivoInvalido("No pude abrir el Excel. Vuelve a descargarlo.") from exc
        hoja = libro.worksheets[0]
        return [list(fila) for fila in hoja.iter_rows(values_only=True)]

    if nombre.endswith((".csv", ".txt")):
        texto = contenido.decode("utf-8-sig", errors="replace")
        muestra = texto[:5000]
        delimitador = None
        for linea in texto.splitlines()[:60]:
            for candidato in (";", ","):
                columnas = _columnas([_normalizar(celda) for celda in next(csv.reader([linea], delimiter=candidato))])
                if any(base != igv for base in columnas[0] for igv in columnas[1]):
                    delimitador = candidato
                    break
            if delimitador:
                break
        if delimitador is None:
            delimitador = ";" if muestra.count(";") > muestra.count(",") else ","
        return [fila for fila in csv.reader(io.StringIO(texto), delimiter=delimitador)]

    raise ArchivoInvalido("Sube la propuesta en formato .xlsx o .csv.")


def _numero(valor) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    texto = str(valor).strip().replace(" ", "").replace("S/", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        # El último separador indica los decimales: 1.234,56 o 1,234.56.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    else:
        texto = texto.replace(",", ".")
    if texto in {"-", "—", ""}:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _columnas(
    textos: list[str],
) -> tuple[list[int], list[int], list[int], list[int], list[int]]:
    base, igv, total, dscto_base, dscto_igv = [], [], [], [], []
    for indice, texto in enumerate(textos):
        if not texto:
            continue
        if "dscto" in texto or "descuento" in texto:
            if "igv" in texto:
                dscto_igv.append(indice)
            elif "bi" in texto or "base" in texto:
                dscto_base.append(indice)
            continue
        if any(palabra in texto for palabra in EXCLUIR):
            continue
        if "base" in texto or texto.startswith("bi "):
            base.append(indice)
        if "igv" in texto:
            igv.append(indice)
        if "total" in texto and "base" not in texto and "igv" not in texto:
            total.append(indice)
    return base, igv, total, dscto_base, dscto_igv


def _cabecera(
    filas: list[list],
) -> tuple[int, list[int], list[int], list[int], list[int], list[int]]:
    for indice, fila in enumerate(filas[:60]):
        textos = [_normalizar(celda) for celda in fila]
        columnas = _columnas(textos)
        if any(base != igv for base in columnas[0] for igv in columnas[1]):
            return indice, *columnas
    raise ArchivoInvalido(
        "No encontré las columnas de base imponible e IGV. "
        "Descarga la propuesta del SIRE en Excel o CSV y vuelve a intentarlo."
    )


def validar_contexto(filas: list[list], *, ruc: str, anio: int, mes: int) -> dict:
    """Comprueba datos de empresa y periodo cuando figuran en cada fila."""
    cabecera, *_ = _cabecera(filas)
    titulos = [_normalizar(celda) for celda in filas[cabecera]]
    indices = {
        "ruc": next((i for i, titulo in enumerate(titulos) if titulo == "ruc"), None),
        "periodo": next((i for i, titulo in enumerate(titulos) if titulo in {"periodo", "período"}), None),
    }
    verificado = {"ruc": indices["ruc"] is not None, "periodo": indices["periodo"] is not None}
    filas_datos = 0
    esperado = f"{anio:04d}{mes:02d}"
    for fila in filas[cabecera + 1 :]:
        if not any(celda not in (None, "") for celda in fila):
            continue
        if _es_fila_total(fila):
            continue
        filas_datos += 1
        for campo, indice in indices.items():
            if indice is None:
                continue
            valor = fila[indice] if indice < len(fila) else None
            if valor is None or not str(valor).strip():
                verificado[campo] = False
                continue
            if isinstance(valor, float) and valor.is_integer():
                valor = int(valor)
            texto = str(valor).strip()
            if campo == "ruc" and texto != ruc:
                raise ArchivoInvalido("El RUC del archivo no corresponde a la empresa seleccionada.")
            if campo == "periodo" and texto not in {esperado, esperado + "00"}:
                raise ArchivoInvalido("El período del archivo no corresponde al período seleccionado.")
    if not filas_datos:
        return {"ruc": False, "periodo": False}
    return verificado


def verificar_registro(filas: list[list], *, registro: str) -> bool:
    """Reconoce solo cabeceras distintivas; no infiere el registro por el nombre del archivo."""
    cabecera, *_ = _cabecera(filas)
    titulos = {_normalizar(celda) for celda in filas[cabecera]}
    rce = {"bi gravado dg", "igv / ipm dg"} <= titulos
    rvie = ("valor facturado exportación" in titulos or "valor facturado exportacion" in titulos) and (
        "dscto bi" in titulos and "dscto igv / ipm" in titulos
    )
    if rce and rvie:
        raise ArchivoInvalido("El archivo mezcla columnas distintivas de RCE y RVIE. Revisa el archivo.")
    detectado = "compras" if rce else "ventas" if rvie else None
    if detectado and detectado != registro:
        raise ArchivoInvalido("El tipo de registro del archivo no coincide con el seleccionado (RCE o RVIE).")
    return detectado is not None


def moneda_verificada_soles(filas: list[list]) -> bool:
    """Solo confirma soles si todas las filas identifican explícitamente PEN."""
    cabecera, *_ = _cabecera(filas)
    titulos = [_normalizar(celda) for celda in filas[cabecera]]
    nombres = {"moneda", "tipo de moneda", "tipo moneda", "código moneda", "codigo moneda"}
    indices = [indice for indice, titulo in enumerate(titulos) if titulo in nombres]
    if len(indices) != 1:
        return False
    indice = indices[0]
    datos = [
        fila
        for fila in filas[cabecera + 1 :]
        if any(celda not in (None, "") for celda in fila) and not _es_fila_total(fila)
    ]
    return bool(datos) and all(indice < len(fila) and str(fila[indice]).strip().upper() == "PEN" for fila in datos)


def _numero_validado(valor) -> Decimal | None:
    numero = _numero(valor)
    if numero is None:
        if valor is None or (not isinstance(valor, bool) and str(valor).strip() in {"", "-", "—"}):
            return None
        raise ArchivoInvalido("El archivo contiene un importe inválido. Revisa sus columnas numéricas.")
    if not numero.is_finite():
        raise ArchivoInvalido("El archivo contiene un importe inválido. Revisa sus columnas numéricas.")
    return numero


def _suma(fila: list, columnas: list[int]) -> Decimal:
    valores = [_numero_validado(fila[i]) for i in columnas if i < len(fila)]
    return sum((v for v in valores if v is not None), Decimal("0"))


def sumar(filas: list[list]) -> dict:
    """Suma las columnas de base, IGV y total de la propuesta."""
    cabecera, cols_base, cols_igv, cols_total, cols_dscto_base, cols_dscto_igv = _cabecera(filas)
    titulos = [_limpio(celda) for celda in filas[cabecera]]
    columnas_mixtas = [
        indice
        for indice, titulo in enumerate(titulos)
        if _normalizar(titulo).split() and _normalizar(titulo).split()[-1] in {"dgng", "dng"}
    ]
    usadas = sorted(set(cols_base + cols_igv + cols_total + cols_dscto_base + cols_dscto_igv))
    nombres = [titulos[i] for i in usadas if i < len(titulos)]

    totales = {"base": Decimal("0"), "igv": Decimal("0"), "total": Decimal("0")}
    filas_contadas = 0

    for numero_fila, fila in enumerate(filas[cabecera + 1 :], start=cabecera + 2):
        if not any(celda not in (None, "") for celda in fila):
            continue
        if _es_fila_total(fila):
            continue

        requeridas = usadas + columnas_mixtas
        if requeridas and len(fila) <= max(requeridas):
            raise ArchivoInvalido(
                f"La fila {numero_fila} está incompleta: faltan columnas de importes. Descarga de nuevo el archivo."
            )

        if any(_numero_validado(fila[i]) not in (None, Decimal("0")) for i in columnas_mixtas if i < len(fila)):
            raise ArchivoInvalido(
                "El archivo contiene compras destinadas a operaciones mixtas o no gravadas. "
                "Esta conciliación aún no calcula esas casillas; revísalas en el RCE y el 621."
            )

        base = _suma(fila, cols_base) + _suma(fila, cols_dscto_base)
        igv = _suma(fila, cols_igv) + _suma(fila, cols_dscto_igv)
        total = _suma(fila, cols_total)
        if cols_total and (base != 0 or igv != 0) and all(_numero_validado(fila[i]) is None for i in cols_total):
            raise ArchivoInvalido(f"La fila {numero_fila} tiene base o IGV, pero no tiene importe total.")
        if not cols_total:
            total = base + igv
        if base == 0 and igv == 0 and total == 0:
            continue

        totales["base"] += base
        totales["igv"] += igv
        totales["total"] += total
        filas_contadas += 1

    return {"filas": filas_contadas, "columnas": nombres, "tiene_total": bool(cols_total), **totales}

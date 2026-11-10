"""Exige formato de ruff solo a los archivos que toca un cambio.

El repositorio arrastra deuda de formato en código anterior (ver `AGENTS.md` §9):
un `ruff format --check` sobre todo el árbol fallaría siempre y bloquearía
cambios legítimos. Este verificador funciona como trinquete: revisa únicamente
los `.py` modificados respecto de una base, de modo que el código nuevo y el que
se edite queden formateados sin reformatear de golpe lo demás.

Uso:
    uv run python scripts/verificar_formato.py            # base origin/main
    uv run python scripts/verificar_formato.py --base SHA # base explícita
    uv run python scripts/verificar_formato.py --todo     # todo el árbol

La CI pasa la base del PR o del push en la variable `BASE_COMPARACION`.
Las migraciones quedan fuera: son código generado y no deben editarse.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_POR_DEFECTO = "origin/main"


def _git(*argumentos: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *argumentos],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _base_valida(base: str) -> bool:
    if not base:
        return False
    return _git("rev-parse", "--verify", f"{base}^{{commit}}").returncode == 0


def resolver_base(preferida: str) -> str | None:
    """Devuelve la primera base comparable: la pedida o, si no existe, origin/main."""
    for candidata in (preferida, BASE_POR_DEFECTO):
        if _base_valida(candidata):
            return candidata
    return None


def _limpiar(archivos: list[str]) -> list[str]:
    limpios = []
    for archivo in archivos:
        archivo = archivo.strip()
        if not archivo or "/migrations/" in archivo.replace("\\", "/"):
            continue
        if Path(archivo).is_file():
            limpios.append(archivo)
    return sorted(set(limpios))


def archivos_modificados(base: str) -> list[str]:
    """Devuelve los `.py` agregados o modificados respecto de la base."""
    resultado = _git("diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD", "--", "*.py")
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip() or "No se pudo comparar con la base.")
    return _limpiar(resultado.stdout.splitlines())


def archivos_en_curso() -> list[str]:
    """Devuelve los `.py` tocados en el árbol de trabajo (aún sin confirmar)."""
    resultado = _git("status", "--porcelain", "--untracked-files=all", "--", "*.py")
    if resultado.returncode != 0:
        raise RuntimeError(resultado.stderr.strip() or "No se pudo leer el estado de git.")
    archivos = []
    for linea in resultado.stdout.splitlines():
        if len(linea) > 3:
            archivos.append(linea[3:])
    return _limpiar(archivos)


def ejecutable_ruff() -> str | None:
    encontrado = shutil.which("ruff")
    if encontrado:
        return encontrado
    # Sin el entorno activado (por ejemplo `python scripts/...`), buscar al lado
    # del intérprete actual: .venv\Scripts\ruff.exe o .venv/bin/ruff.
    candidatos = [Path(sys.executable).with_name("ruff.exe"), Path(sys.executable).with_name("ruff")]
    for candidato in candidatos:
        if candidato.is_file():
            return str(candidato)
    return None


def revisar(archivos: list[str], ruff: str) -> int:
    resultado = subprocess.run([ruff, "format", "--check", *archivos], check=False)
    return resultado.returncode


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--base",
        default=os.environ.get("BASE_COMPARACION") or BASE_POR_DEFECTO,
    )
    analizador.add_argument(
        "--todo",
        action="store_true",
        help="Revisa el árbol completo (falla mientras exista deuda de formato).",
    )
    opciones = analizador.parse_args()

    ruff = ejecutable_ruff()
    if ruff is None:
        print("No se encontró ruff. Ejecuta `uv sync` o usa `uv run python ...`.", file=sys.stderr)
        return 2

    if opciones.todo:
        archivos = [str(ruta) for ruta in Path(".").rglob("*.py") if ".venv" not in ruta.parts]
        archivos = [archivo for archivo in archivos if "/migrations/" not in archivo.replace("\\", "/")]
        print(f"Revisando el árbol completo: {len(archivos)} archivos.")
        return revisar(archivos, ruff)

    base = resolver_base(opciones.base)
    if base is None:
        print(
            f"No se pudo resolver la base '{opciones.base}' ni '{BASE_POR_DEFECTO}'. "
            "Indica --base SHA o define BASE_COMPARACION.",
            file=sys.stderr,
        )
        return 2
    if base != opciones.base:
        print(f"Aviso: '{opciones.base}' no existe; se compara con '{base}'.")

    archivos = sorted(set(archivos_modificados(base)) | set(archivos_en_curso()))
    if not archivos:
        print(f"Sin archivos .py modificados respecto de {base}; nada que revisar.")
        return 0

    print(f"Revisando {len(archivos)} archivos modificados respecto de {base}:")
    for archivo in archivos:
        print(f"  {archivo}")
    return revisar(archivos, ruff)


if __name__ == "__main__":
    raise SystemExit(main())

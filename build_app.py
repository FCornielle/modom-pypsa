"""Build de la app de escritorio: PyInstaller + copia de datos junto al .exe.

Uso:
    .venv/Scripts/python.exe build_app.py [--no-build]

Produce  dist/PlataformaMODOM/  con:
    PlataformaMODOM.exe · _internal/ (código+libs) · data/ · results/
La app resuelve data/ y results/ por `paths.APP_ROOT` = carpeta del .exe, así que las
corridas se guardan ahí y los datos del MODOM se pueden actualizar reemplazando archivos.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "dist" / "PlataformaMODOM"
PINNED_EXPORT = "salida_PDD_30_09_2025_20260613_022117"


def _force_rmtree(path: Path) -> None:
    """Borra un árbol aunque tenga archivos de solo-lectura (el export DIgSILENT los trae)."""
    import os
    import stat

    def _on_error(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


def _copy(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  aviso: falta {src}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    print(f"  copiado {src.relative_to(REPO)} -> {dst.relative_to(DIST.parent)}")


def bundle_data() -> None:
    """Copia los datos necesarios (livianos) junto al ejecutable."""
    print("Copiando datos junto al .exe...")
    _copy(REPO / "data" / "processed", DIST / "data" / "processed")
    _copy(REPO / "data" / "raw", DIST / "data" / "raw")
    # de external solo lo que usa la app: coords + el export DIgSILENT fijado
    ext = REPO / "data" / "external"
    for name in ("buses_with_coords.csv", "coordinate_overrides.csv"):
        _copy(ext / name, DIST / "data" / "external" / name)
    _copy(ext / PINNED_EXPORT, DIST / "data" / "external" / PINNED_EXPORT)
    # resultado base (para que la plataforma abra con el dashboard poblado)
    _copy(REPO / "results" / "pypsa_milp", DIST / "results" / "pypsa_milp")
    (DIST / "results" / "runs").mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-build", action="store_true", help="solo copiar datos")
    args = ap.parse_args()
    if not args.no_build:
        print("Limpiando dist previo (con manejo de solo-lectura)...")
        _force_rmtree(DIST)  # evita el choque de PyInstaller con los datos copiados
        print("Compilando con PyInstaller (esto tarda varios minutos)...")
        pyi = REPO / ".venv" / "Scripts" / "pyinstaller.exe"
        subprocess.run([str(pyi), "PlataformaMODOM.spec", "--noconfirm",
                        "--distpath", "dist", "--workpath", "build_pyi"],
                       cwd=str(REPO), check=True)
    bundle_data()
    exe = DIST / "PlataformaMODOM.exe"
    print(f"\nListo: {exe}" if exe.exists() else f"\nNo se encontró {exe}")


if __name__ == "__main__":
    main()

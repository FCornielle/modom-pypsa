"""Raíz de la aplicación, robusta al empaquetado (PyInstaller / frozen).

En desarrollo, `APP_ROOT` es la raíz del repo (como antes). En el ejecutable empaquetado,
es la **carpeta que contiene el .exe**, para que los datos y las corridas (`data/`, `results/`)
sean escribibles junto a la aplicación y no dentro del bundle de solo lectura. El código y las
plantillas sí van dentro del bundle (se resuelven por `__file__`).
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):  # ejecutable PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]  # src/modom_pypsa/paths.py -> raíz del repo


APP_ROOT = app_root()
DATA_DIR = APP_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
EXTERNAL_DIR = DATA_DIR / "external"
RAW_DIR = DATA_DIR / "raw"
RESULTS_DIR = APP_ROOT / "results"

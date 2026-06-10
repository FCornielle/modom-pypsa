"""Extrae el CVP declarado y el combustible oficial por unidad (VEROPE del OC).

El archivo `VERIFICACION CVP_*.xlsx` (carpeta VEROPE de Programación del SENI) trae,
por central, el **costo variable de producción declarado** y el **combustible oficial**.
Son datos vigentes y autoritativos que mejoran la fidelidad de costos/precios/mezcla
frente al `effective_cvp` de la plantilla MODOM y a la clasificación de combustible
por heurística del unifilar.

Salida: `data/external/programacion_seni/verope/declared_cvp.csv`
(`generator_id, cvp_declarado, combustible, combustible_raw`). El builder PyPSA y
el dashboard pueden usarla como override. Cruza ~54/140 unidades (las térmicas que
declaran; hidro/solar/eólica no declaran CVP).
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import pandas as pd

from .xlsm import XlsmReader

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "external" / "programacion_seni" / "verope" / "declared_cvp.csv"
SHEET = "COSTO VARIABLE DE PRODUCCIÓN"


def find_verope_xlsx(search_root: Path) -> Path:
    cands = glob.glob(str(search_root / "**" / "VERIFICACION CVP*.xlsx"), recursive=True)
    if not cands:
        raise FileNotFoundError(f"No encontré 'VERIFICACION CVP*.xlsx' bajo {search_root}")
    return Path(sorted(cands)[-1])  # el más reciente por nombre


def map_fuel(raw: str) -> str:
    """Combustible declarado del OC -> categoría del dashboard."""
    t = str(raw).upper()
    if "CARB" in t or "ITABO" in t:          # Itabo 1 y 2 = carbón
        return "Carbón"
    if "GAS NATURAL" in t or re.search(r"\bGN\b", t):
        return "Gas Natural"
    if "FUEL OIL" in t or "DIESEL" in t or "GASOIL" in t or "FO" == t:
        return "Fuel Oil / Diesel"
    if "BIO" in t or "BAGAZO" in t:
        return "Biomasa"
    if "SOLAR" in t or "FOTOV" in t:
        return "Solar"
    if "EOLIC" in t or "VIENTO" in t:
        return "Eólica"
    if "HIDRO" in t or "AGUA" in t:
        return "Hidro"
    return "Otra"


def extract_declared_cvp(xlsx: Path) -> pd.DataFrame:
    m = XlsmReader(xlsx).read_sheet_matrix(SHEET)
    h = [str(c).strip().upper() for c in m[2]]

    def col(*names: str) -> int:
        for nm in names:
            for i, c in enumerate(h):
                if nm in c:
                    return i
        return -1

    cgen, cfuel, ccvp = col("CENTRAL", "CÓDIGO"), col("COMBUSTIBLE"), col("COSTO VARIABLE")
    rows: dict[str, dict] = {}
    for r in m[3:]:
        gid = str(r[cgen]).strip() if 0 <= cgen < len(r) else ""
        if not gid.startswith("G"):
            continue
        try:
            cvp = float(str(r[ccvp]).strip())
        except (ValueError, IndexError):
            continue
        fuel_raw = str(r[cfuel]).strip() if 0 <= cfuel < len(r) else ""
        rows[gid] = {"generator_id": gid, "cvp_declarado": round(cvp, 2),
                     "combustible": map_fuel(fuel_raw), "combustible_raw": fuel_raw}
    return pd.DataFrame(list(rows.values()))


def export_declared_cvp(search_root: Path, out: Path = DEFAULT_OUT) -> dict[str, object]:
    xlsx = find_verope_xlsx(search_root)
    df = extract_declared_cvp(xlsx)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return {
        "source": xlsx.name,
        "units": len(df),
        "by_fuel": df["combustible"].value_counts().to_dict(),
        "out": str(out),
    }

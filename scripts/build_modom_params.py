"""Ingesta de los parámetros del MILP del MODOM (commitment, opciones, embalses).

Uso:
    .venv/Scripts/python.exe scripts/build_modom_params.py [--xlsm data/raw/<workbook>.xlsm]

Escribe:
    data/processed/commitment/gen_params.csv     (e_datgen: rampas, tiempos, NAMX, ...)
    data/processed/commitment/model_options.csv  (e_opcn: CENS, PORS, CVRRF, ...)
    data/processed/hydro/{reservoirs,inflow,extract,final_level,gen_reservoir}.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from modom_pypsa import modom_params as mp

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    default_xlsm = REPO / "data" / "raw" / "MODOM_DIARIO_dd-mm-yyyy_V449.xlsm"
    ap.add_argument("--xlsm", type=Path, default=default_xlsm)
    ap.add_argument("--outdir", type=Path, default=REPO / "data" / "processed")
    args = ap.parse_args()

    summary = mp.export_params(args.xlsm, args.outdir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(REPO / "src"))
    main()

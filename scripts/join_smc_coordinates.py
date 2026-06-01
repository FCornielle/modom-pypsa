#!/usr/bin/env python3
"""Cruza los puntos SMC del OC (lat/lon) con las barras del modelo de red."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.smc_coordinates import (
    DEFAULT_DATA_DIR,
    DEFAULT_EXTERNAL_DIR,
    DEFAULT_OC_CSV,
    export_coordinates,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--oc-csv", type=Path, default=DEFAULT_OC_CSV)
    ap.add_argument("--outdir", type=Path, default=DEFAULT_EXTERNAL_DIR)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.oc_csv.exists():
        print(
            f"No existe {args.oc_csv}. Corre primero scripts/scrape_oc_smc.py "
            "para extraer las coordenadas del OC."
        )
        return 1
    summary = export_coordinates(args.data_dir, args.oc_csv, args.outdir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

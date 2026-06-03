#!/usr/bin/env python3
"""Genera el dashboard del SENI como un único HTML autocontenido y compartible."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.dashboard import (
    DEFAULT_CASE_LABEL,
    DEFAULT_DATA_DIR,
    DEFAULT_EXTERNAL_DIR,
    DEFAULT_OUT,
    DEFAULT_RESULTS_DIR,
    build_dashboard,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--external-dir", type=Path, default=DEFAULT_EXTERNAL_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--case-label",
        default=DEFAULT_CASE_LABEL,
        help="Etiqueta del caso (p.ej. 'MODOM_DIARIO 15-04-2026 V449').",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    out = build_dashboard(
        args.results_dir, args.data_dir, args.external_dir, args.out, args.case_label
    )
    print(f"OK -> {out}")
    print("Abre ese archivo en el navegador (es autocontenido: se puede compartir).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

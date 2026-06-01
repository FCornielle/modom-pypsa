#!/usr/bin/env python3
"""Exporta un inventario reproducible de un workbook MODOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.workbook_inventory import export_workbook_inventory


DEFAULT_XLSM = Path("/tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm")
DEFAULT_OUTDIR = REPO_ROOT / "data" / "processed" / "workbook_inventory"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, default=DEFAULT_XLSM)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--preview-rows", type=int, default=5)
    parser.add_argument("--header-scan-rows", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        raise FileNotFoundError(f"No existe el workbook XLSM: {args.xlsm}")

    payload = export_workbook_inventory(
        xlsm_path=args.xlsm,
        outdir=args.outdir,
        preview_rows=args.preview_rows,
        header_scan_rows=args.header_scan_rows,
    )
    summary = {
        "source_xlsm": str(args.xlsm),
        "outdir": str(args.outdir),
        "sheet_count": payload["sheet_count"],
        "focus_sheet_names": payload["focus_sheet_names"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

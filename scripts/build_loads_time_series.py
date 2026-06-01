#!/usr/bin/env python3
"""Construye la primera versión canónica de `loads_time_series` desde MODOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.loads import export_loads_time_series


DEFAULT_XLSM = Path("/tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm")
DEFAULT_OUTDIR = REPO_ROOT / "data" / "processed" / "loads_time_series"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, default=DEFAULT_XLSM)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        raise FileNotFoundError(f"No existe el workbook XLSM: {args.xlsm}")

    payload = export_loads_time_series(args.xlsm, args.outdir)
    summary = {
        "source_xlsm": str(args.xlsm),
        "outdir": str(args.outdir),
        "raw_long_row_count": len(payload["raw_long_rows"]),
        "loads_time_series_row_count": len(payload["loads_time_series"]),
        "loads_time_series_load_count": payload["reconciliation_summary"]["counts"][
            "loads_time_series_load_count"
        ],
        "time_block_count": payload["reconciliation_summary"]["counts"]["time_block_count"],
        "requires_snapshot_translation": payload["reconciliation_summary"][
            "consistency_flags"
        ]["requires_snapshot_translation"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

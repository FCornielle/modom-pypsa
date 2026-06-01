#!/usr/bin/env python3
"""Construye series temporales canónicas de generación desde MODOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.generator_time_series import export_generator_time_series


DEFAULT_XLSM = Path("/tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm")
DEFAULT_OUTROOT = REPO_ROOT / "data" / "processed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, default=DEFAULT_XLSM)
    parser.add_argument("--outroot", type=Path, default=DEFAULT_OUTROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        raise FileNotFoundError(f"No existe el workbook XLSM: {args.xlsm}")

    payload = export_generator_time_series(args.xlsm, args.outroot)
    availability_counts = payload["generator_availability"]["summary"]["counts"]
    renewable_counts = payload["renewable_profiles"]["summary"]["counts"]
    summary = {
        "source_xlsm": str(args.xlsm),
        "outroot": str(args.outroot),
        "generator_availability_row_count": availability_counts[
            "generator_availability_row_count"
        ],
        "availability_matched_generator_count": availability_counts[
            "matched_generator_count"
        ],
        "availability_sheet_only_generator_count": availability_counts[
            "sheet_only_generator_count"
        ],
        "renewable_profiles_row_count": renewable_counts["renewable_profiles_row_count"],
        "renewable_matched_generator_count": renewable_counts[
            "matched_generator_count"
        ],
        "total_renovable_only_generator_count": renewable_counts[
            "total_renovable_only_generator_count"
        ],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

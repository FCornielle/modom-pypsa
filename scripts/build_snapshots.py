#!/usr/bin/env python3
"""Construye la tabla canónica inicial de snapshots desde el workbook MODOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.snapshots import export_snapshots


DEFAULT_XLSM = Path("/tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm")
DEFAULT_OUTDIR = REPO_ROOT / "data" / "processed" / "snapshots"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, default=DEFAULT_XLSM)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        raise FileNotFoundError(f"No existe el workbook XLSM: {args.xlsm}")

    payload = export_snapshots(args.xlsm, args.outdir)
    summary = {
        "source_xlsm": str(args.xlsm),
        "outdir": str(args.outdir),
        "snapshot_count": len(payload["snapshots"]),
        "dispatch_range": payload["horizon_summary"]["dispatch_horizon"]["range_spec"],
        "load_block_count": payload["horizon_summary"]["load_profile_horizon"]["block_count"],
        "canonical_v1_uses_24h_load_blocks": payload["horizon_summary"][
            "consistency_flags"
        ]["canonical_v1_uses_24h_load_blocks"],
        "requires_operational_48_to_24_translation": payload["horizon_summary"][
            "consistency_flags"
        ]["requires_operational_48_to_24_translation"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

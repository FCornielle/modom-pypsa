#!/usr/bin/env python3
"""Extrae los parámetros reactivos de red (líneas R/X/charging, shunts, OLTC) del export de DIgSILENT."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.digsilent_data import DEFAULT_OUTDIR, DEFAULT_XLSX, export_digsilent_data


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX,
                    help="Export de elementos de DIgSILENT (.xlsx)")
    ap.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsx.exists():
        print(f"No existe {args.xlsx}")
        return 1
    print(json.dumps(export_digsilent_data(args.xlsx, args.outdir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

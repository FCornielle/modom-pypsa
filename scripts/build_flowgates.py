#!/usr/bin/env python3
"""Construye la capa canónica de `flowgates` desde la hoja `e_fgate` del MODOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.flowgates import export_flowgates


DEFAULT_XLSM = REPO_ROOT / "data" / "raw" / "MODOM_DIARIO_dd-mm-yyyy_V449.xlsm"
DEFAULT_OUTDIR = REPO_ROOT / "data" / "processed" / "flowgates"
DEFAULT_BRANCH_DIR = REPO_ROOT / "data" / "processed" / "pypsa_branch_components"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsm", type=Path, default=DEFAULT_XLSM)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--branch-dir", type=Path, default=DEFAULT_BRANCH_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        raise FileNotFoundError(f"No existe el workbook XLSM: {args.xlsm}")

    payload = export_flowgates(args.xlsm, args.outdir, args.branch_dir)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

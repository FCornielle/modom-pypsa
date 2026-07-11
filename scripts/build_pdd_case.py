#!/usr/bin/env python3
"""Ingiere un PDD publicado por el OC al store canónico por fecha (data/processed/pdd/)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.pdd import export_pdd


DEFAULT_OUT_ROOT = REPO_ROOT / "data" / "processed" / "pdd"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, required=True, help="Ruta al PDD .xlsx")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsx.exists():
        raise FileNotFoundError(f"No existe el PDD: {args.xlsx}")
    payload = export_pdd(args.xlsx, args.out_root)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

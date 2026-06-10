#!/usr/bin/env python3
"""Extrae los resultados del propio MODOM (despacho, flujos, ENS) como verdad de referencia."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.modom_results import DEFAULT_DATA_DIR, export_modom_results


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsm", type=Path, required=True, help="Caso MODOM (.xlsm)")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.xlsm.exists():
        print(f"No existe {args.xlsm}")
        return 1
    summary = export_modom_results(args.xlsm, args.data_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

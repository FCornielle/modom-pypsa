#!/usr/bin/env python3
"""Extrae el CVP declarado y el combustible oficial por unidad desde VEROPE (Programación del SENI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.declared_cvp import DEFAULT_OUT, export_declared_cvp


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search-root", type=Path, default=REPO_ROOT / "data" / "external",
                    help="Carpeta donde buscar 'VERIFICACION CVP*.xlsx'")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(export_declared_cvp(args.search_root, args.out), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

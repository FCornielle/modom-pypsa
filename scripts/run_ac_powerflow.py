#!/usr/bin/env python3
"""Corre el flujo de potencia AC (pandapower) y reporta fidelidad de tensión vs MODOM."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.ac_network import DEFAULT_DATA_DIR, DEFAULT_RESULTS_DIR, run_ac


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    report = run_ac(args.data_dir, args.results_dir)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

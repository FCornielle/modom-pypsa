#!/usr/bin/env python3
"""Construye y resuelve la primera red `pypsa.Network()` real desde la capa canónica."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.pypsa_network import (
    DEFAULT_DATA_DIR,
    DEFAULT_RESULTS_DIR,
    build_network,
    export_results,
    solve_network,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--solver", default="highs")
    parser.add_argument(
        "--no-solve",
        action="store_true",
        help="Solo construir y reportar la red, sin optimizar.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    n = build_network(data_dir=args.data_dir)
    print(json.dumps(n.meta, indent=2, ensure_ascii=False))
    if args.no_solve:
        return 0
    solve_network(n, solver_name=args.solver)
    summary = export_results(n, outdir=args.outdir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

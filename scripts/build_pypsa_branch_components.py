#!/usr/bin/env python3
"""Construye la traducción v1 de `branches` a componentes PyPSA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.pypsa_branch_components import export_pypsa_branch_components


DEFAULT_BRANCHES = REPO_ROOT / "data" / "processed" / "branches" / "branches.csv"
DEFAULT_BUSES = REPO_ROOT / "data" / "processed" / "buses" / "buses.csv"
DEFAULT_OUTDIR = REPO_ROOT / "data" / "processed" / "pypsa_branch_components"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branches", type=Path, default=DEFAULT_BRANCHES)
    parser.add_argument("--buses", type=Path, default=DEFAULT_BUSES)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = export_pypsa_branch_components(args.branches, args.buses, args.outdir)
    print(
        json.dumps(
            {
                "source_branches": str(args.branches),
                "source_buses": str(args.buses),
                "outdir": str(args.outdir),
                **payload["summary"]["counts"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

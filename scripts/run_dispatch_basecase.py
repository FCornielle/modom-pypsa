#!/usr/bin/env python3
"""Ejecuta el primer despacho económico base desde la capa canónica."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.dispatch import DEFAULT_DATA_DIR, DEFAULT_RESULTS_DIR, run_copperplate_dispatch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--snapshot-id", default="h_01")
    parser.add_argument("--load-block-id", default="h_01")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_copperplate_dispatch(
        data_dir=args.data_dir,
        snapshot_id=args.snapshot_id,
        load_block_id=args.load_block_id,
        outdir=args.outdir,
    )
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

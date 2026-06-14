#!/usr/bin/env python3
"""Corre el lazo iterativo DC↔AC→MODOM y persiste la corrida en results/runs/."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.iterative import DEFAULT_EXPORT, run_iterative


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hour", default="h_19")
    ap.add_argument("--all", action="store_true", help="correr las 24 horas")
    ap.add_argument("--max-iter", type=int, default=8)
    ap.add_argument("--tol", type=float, default=1e-3)
    ap.add_argument("--damping", type=float, default=0.5)
    ap.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT)
    ap.add_argument("--project-id", default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    hours = None if args.all else [args.hour]  # None => 24 h en UNA corrida
    m = run_iterative(hours=hours, max_iter=args.max_iter, tol=args.tol,
                      damping=args.damping, export_dir=args.export_dir,
                      project_id=args.project_id)
    s = m["summary"]
    print(f"{m['status']} | horas={s['n_hours']} iters={s['n_iterations']} "
          f"delta={s.get('final_delta')} pico={s.get('hour')} "
          f"losses={s.get('losses_mw')} MW V={s.get('v_min')}-{s.get('v_max')} "
          f"-> {m['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

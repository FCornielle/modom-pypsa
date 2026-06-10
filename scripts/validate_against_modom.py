#!/usr/bin/env python3
"""Compara el despacho de PyPSA contra la verdad de referencia del MODOM y reporta fidelidad."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa.validation import (
    DEFAULT_MODOM_DIR,
    DEFAULT_RESULTS_DIR,
    build_report,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--modom-dir", type=Path, default=DEFAULT_MODOM_DIR)
    ap.add_argument("--out", type=Path,
                    default=DEFAULT_RESULTS_DIR / "fidelity_report.json")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args.results_dir, args.modom_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    gd = report["generator_dispatch"]
    bf = report["branch_flows"]
    en = report["ens"]
    print("=" * 56)
    print(f"  FIDELIDAD vs MODOM   ->   score {report['fidelity_score']} / 100")
    print("=" * 56)
    print(f"Despacho por generador ({gd['common_generators']} comunes):")
    print(f"  por unidad/hora : {gd['per_unit_hourly']}")
    print(f"  total sistema   : {gd['system_total_hourly']}")
    print(f"Flujos de rama ({bf.get('matched_branches', 0)} emparejadas de "
          f"{bf.get('modom_branches', 0)} MODOM):")
    print(f"  |flujo|         : {bf.get('abs_flow')}")
    print(f"ENS: nuestra {en['ours_ens_mwh']} MWh vs MODOM {en['modom_ens_mwh']} MWh "
          f"(dif {en['abs_diff_mwh']})")
    print(f"\nReporte completo -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

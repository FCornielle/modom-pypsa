#!/usr/bin/env python3
"""Inyecta el despacho PyPSA/MODOM sobre la red AC de DIgSILENT y agrega a 717 barras.

Corre el flujo AC (pandapower) para las 24 horas usando el export DIgSILENT como red
física y NUESTRO despacho MODOM como punto de operación (cruce por `for_name`/W-code).
Vuelca por hora: tensiones en las 717 barras MODOM, cargabilidad de ramas, y un
resumen con cobertura del cruce.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd

from modom_pypsa.ac_inject import run_ac_modom

DEFAULT_EXPORT = REPO_ROOT / "data/external/salida_PDD_30_09_2025_20260613_022117"
DEFAULT_OUT = REPO_ROOT / "data/processed/ac_modom"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--hours", nargs="*", default=[f"h_{i:02d}" for i in range(1, 25)])
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summaries, all_bus, all_br = [], [], []
    for h in args.hours:
        net, ctx, bus_res, br_res, s = run_ac_modom(
            args.export_dir, hour=h, root=str(REPO_ROOT))
        summaries.append(s)
        bus_res.insert(0, "hour", h)
        all_bus.append(bus_res)
        if len(br_res):
            br_res.insert(0, "hour", h)
            all_br.append(br_res)
        print(f"{h}: conv={s['converged']} V={s['v_min']:.3f}-{s['v_max']:.3f} "
              f"<0.9={s['n_v_below_090']} Vbus={s['modom_buses_with_v']}/717 "
              f"gen_cov={s['gen_coverage']:.0%} load_cov={s['load_coverage']:.0%}")

    pd.concat(all_bus, ignore_index=True).to_csv(
        args.out_dir / "bus_voltages_24h.csv", index=False)
    if all_br:
        pd.concat(all_br, ignore_index=True).to_csv(
            args.out_dir / "branch_loading_24h.csv", index=False)
    pd.DataFrame(summaries).to_csv(args.out_dir / "summary_24h.csv", index=False)
    (args.out_dir / "summary_24h.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEscrito en {args.out_dir} | convergieron "
          f"{sum(s['converged'] for s in summaries)}/{len(summaries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Corre el MILP completo del MODOM en PyPSA (commitment co-optimizado).

Uso:
    .venv/Scripts/python.exe scripts/run_milp.py [--no-reserves] [--gap 0.02] [--time 600]

Requiere los parámetros ingeridos (scripts/build_modom_params.py). Escribe resultados en
results/pypsa_milp/ e imprime un resumen + validación contra el MODOM.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-reserves", action="store_true", help="desactiva eq. 10–15")
    ap.add_argument("--gap", type=float, default=0.02, help="mip_rel_gap")
    ap.add_argument("--time", type=float, default=600.0, help="time_limit (s)")
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO / "src"))
    from modom_pypsa import pypsa_milp as milp

    n = milp.build_milp_network(with_reserves=not args.no_reserves)
    print("counts:", json.dumps(n.meta["counts"], ensure_ascii=False))
    milp.solve_milp(n, mip_rel_gap=args.gap, time_limit=args.time)
    if n.objective is None:
        print("INFACTIBLE / no resuelto")
        return
    summary = milp.export_results(n)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

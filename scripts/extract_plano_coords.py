#!/usr/bin/env python3
"""Rescata coordenadas de buses desde el plano geografico del OC.

Toma `data/external/buses_with_coords.csv` y, para los buses SIN coordenada real
(coord_source != smc_match) que tienen etiqueta en el plano vectorial, asigna
(lat, lon) por interpolacion local (IDW) anclada en los buses que SI tienen
coords reales. Nunca toca los `smc_match`. Ver `modom_pypsa.plano_coordinates`.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from modom_pypsa import plano_coordinates as pc


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    ap.add_argument(
        "--buses-csv",
        type=Path,
        default=REPO_ROOT / "data" / "external" / "buses_with_coords.csv",
    )
    ap.add_argument("--min-jaccard", type=float, default=0.85)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.buses_csv.exists():
        print(f"No existe {args.buses_csv}. Corre primero join_smc_coordinates.py.")
        return 1
    try:
        pdf = pc.find_plano_pdf(args.data_dir)
    except FileNotFoundError as exc:
        print(str(exc))
        print("Guarda el 'Plano RD Lineas Transmision *.pdf' del OC en data/.")
        return 1

    with args.buses_csv.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0].keys()) if rows else []

    labels = pc.extract_labels(pdf)
    coords, stats = pc.georeference_gap_buses(rows, labels, min_jaccard=args.min_jaccard)

    updated = 0
    for r in rows:
        bid = (r.get("bus_id_modom") or "").strip()
        if bid in coords:
            lon, lat = coords[bid]
            r["lat"] = f"{lat:.5f}"
            r["lon"] = f"{lon:.5f}"
            r["coord_source"] = "plano_idw"
            updated += 1

    with args.buses_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # auditoria: que etiqueta se uso por bus
    matches = pc.match_labels_to_buses(labels, rows, min_jaccard=args.min_jaccard)
    audit = args.buses_csv.parent / "plano_substation_matches.csv"
    with audit.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bus_id_modom", "bus_name", "plano_label", "plano_x", "plano_y", "applied"])
        for r in rows:
            bid = (r.get("bus_id_modom") or "").strip()
            if bid in matches:
                lab = matches[bid]
                w.writerow([bid, r.get("bus_name", ""), lab.text,
                            f"{lab.x:.1f}", f"{lab.y:.1f}", "yes" if bid in coords else "no"])

    summary = {"plano_pdf": pdf.name, "updated_buses": updated, **stats,
               "audit_csv": str(audit)}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

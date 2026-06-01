"""Construcción inicial de la tabla canónica `buses`."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from .xlsm import XlsmReader


LEADING_STAR_RE = re.compile(r"^\*\s*")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean(value: str) -> str:
    return str(value or "").strip()


def normalize_bus_code(value: str) -> str:
    code = clean(value)
    code = LEADING_STAR_RE.sub("", code)
    code = code.replace(" ", "")
    return code


def extract_mapping_buses(reader: XlsmReader) -> list[dict[str, str]]:
    matrix = reader.read_sheet_matrix("MAPEO TODAS LAS BARRAS")
    rows: list[dict[str, str]] = []
    for row in matrix[3:]:
        if len(row) < 5 or not clean(row[0]):
            continue
        rows.append(
            {
                "bus_old": normalize_bus_code(row[0]),
                "bus_old_name": clean(row[1]),
                "bus_new": normalize_bus_code(row[2]),
                "bus_new_name": clean(row[3]),
                "code_changed": clean(row[4]),
            }
        )
    return rows


def extract_e_datred_bus_counts(reader: XlsmReader) -> Counter[str]:
    matrix = reader.read_sheet_matrix("e_datred")
    counts: Counter[str] = Counter()
    for row in matrix[3:]:
        if len(row) < 3:
            continue
        for idx in (0, 2):
            code = normalize_bus_code(row[idx])
            if code:
                counts[code] += 1
    return counts


def build_buses(reader: XlsmReader) -> dict[str, object]:
    mapping_rows = extract_mapping_buses(reader)
    red_counts = extract_e_datred_bus_counts(reader)

    buses_by_id: dict[str, dict[str, object]] = {}
    for row in mapping_rows:
        bus_id = str(row["bus_new"])
        buses_by_id[bus_id] = {
            "bus_id_modom": bus_id,
            "bus_name": row["bus_new_name"],
            "bus_id_legacy": row["bus_old"],
            "bus_name_legacy": row["bus_old_name"],
            "code_changed": row["code_changed"],
            "appears_in_mapping": True,
            "appears_in_e_datred": bus_id in red_counts,
            "e_datred_endpoint_count": int(red_counts.get(bus_id, 0)),
            "source_sheet_primary": "MAPEO TODAS LAS BARRAS",
            "bus_origin": "mapping",
        }

    for bus_id, endpoint_count in red_counts.items():
        if bus_id in buses_by_id:
            continue
        buses_by_id[bus_id] = {
            "bus_id_modom": bus_id,
            "bus_name": "",
            "bus_id_legacy": "",
            "bus_name_legacy": "",
            "code_changed": "",
            "appears_in_mapping": False,
            "appears_in_e_datred": True,
            "e_datred_endpoint_count": int(endpoint_count),
            "source_sheet_primary": "e_datred",
            "bus_origin": "e_datred_only",
        }

    buses = list(buses_by_id.values())
    buses.sort(key=lambda item: str(item["bus_id_modom"]))

    mapped_bus_ids = {str(row["bus_new"]) for row in mapping_rows}
    red_bus_ids = set(red_counts)
    summary = {
        "source_sheets": ["MAPEO TODAS LAS BARRAS", "e_datred"],
        "counts": {
            "mapping_row_count": len(mapping_rows),
            "mapping_bus_count": len(mapped_bus_ids),
            "e_datred_bus_count": len(red_bus_ids),
            "buses_row_count": len(buses),
            "mapping_and_e_datred_overlap_count": len(mapped_bus_ids & red_bus_ids),
            "e_datred_only_bus_count": len(red_bus_ids - mapped_bus_ids),
            "mapping_only_bus_count": len(mapped_bus_ids - red_bus_ids),
        },
        "reconciliation": {
            "e_datred_only_bus_sample": sorted(list(red_bus_ids - mapped_bus_ids))[:40],
            "mapping_only_bus_sample": sorted(list(mapped_bus_ids - red_bus_ids))[:40],
        },
    }
    return {
        "buses": buses,
        "summary": summary,
    }


def export_buses(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    reader = XlsmReader(xlsm_path)
    payload = build_buses(reader)
    write_csv(
        outdir / "buses.csv",
        payload["buses"],
        fieldnames=[
            "bus_id_modom",
            "bus_name",
            "bus_id_legacy",
            "bus_name_legacy",
            "code_changed",
            "appears_in_mapping",
            "appears_in_e_datred",
            "e_datred_endpoint_count",
            "source_sheet_primary",
            "bus_origin",
        ],
    )
    write_json(outdir / "buses_reconciliation_summary.json", payload["summary"])
    return payload

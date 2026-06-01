"""Construcción inicial de la tabla canónica `branches`."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .buses import build_buses, normalize_bus_code
from .xlsm import XlsmReader


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


def to_float(value: str) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def infer_branch_type(circuit_id: str) -> str:
    if clean(circuit_id).startswith("T"):
        return "transformer"
    return "line"


def build_branch_id(from_bus: str, to_bus: str, circuit_id: str) -> str:
    return f"{from_bus}__{to_bus}__{circuit_id}"


def build_branches(reader: XlsmReader) -> dict[str, object]:
    buses_payload = build_buses(reader)
    bus_ids = {str(row["bus_id_modom"]) for row in buses_payload["buses"]}

    matrix = reader.read_sheet_matrix("e_datred")
    branches: list[dict[str, object]] = []
    missing_bus_refs: list[dict[str, object]] = []
    branch_base_id_counts: Counter[str] = Counter()

    for row_idx, row in enumerate(matrix[3:], start=4):
        if len(row) < 11 or not clean(row[0]):
            continue

        from_bus = normalize_bus_code(row[0])
        to_bus = normalize_bus_code(row[2])
        circuit_id = clean(row[4])
        branch_type = infer_branch_type(circuit_id)
        branch_base_id = build_branch_id(from_bus, to_bus, circuit_id)
        branch_base_id_counts[branch_base_id] += 1
        branch_parallel_index = int(branch_base_id_counts[branch_base_id])
        branch_id = (
            branch_base_id
            if branch_parallel_index == 1
            else f"{branch_base_id}__p{branch_parallel_index}"
        )

        from_bus_in_buses = from_bus in bus_ids
        to_bus_in_buses = to_bus in bus_ids
        if not from_bus_in_buses or not to_bus_in_buses:
            missing_bus_refs.append(
                {
                    "source_row_number": row_idx,
                    "branch_id": branch_id,
                    "branch_base_id": branch_base_id,
                    "from_bus": from_bus,
                    "to_bus": to_bus,
                    "from_bus_in_buses": from_bus_in_buses,
                    "to_bus_in_buses": to_bus_in_buses,
                }
            )

        branches.append(
            {
                "branch_id": branch_id,
                "branch_base_id": branch_base_id,
                "branch_parallel_index": branch_parallel_index,
                "from_bus": from_bus,
                "to_bus": to_bus,
                "circuit_id": circuit_id,
                "branch_type": branch_type,
                "r_pu": to_float(row[6]) if to_float(row[6]) is not None else "",
                "x_pu": to_float(row[7]) if to_float(row[7]) is not None else "",
                "fmax_mw": to_float(row[8]) if to_float(row[8]) is not None else "",
                "in_service_base": clean(row[9]),
                "closure_flag": clean(row[10]),
                "from_bus_in_buses": from_bus_in_buses,
                "to_bus_in_buses": to_bus_in_buses,
                "source_sheet": "e_datred",
                "source_row_number": row_idx,
            }
        )

    branches.sort(key=lambda item: str(item["branch_id"]))
    type_counts = Counter(str(row["branch_type"]) for row in branches)
    duplicate_branch_base_ids = [
        branch_base_id
        for branch_base_id, count in branch_base_id_counts.items()
        if count > 1
    ]

    summary = {
        "source_sheets": ["e_datred", "buses"],
        "counts": {
            "branches_row_count": len(branches),
            "line_count": int(type_counts.get("line", 0)),
            "transformer_count": int(type_counts.get("transformer", 0)),
            "missing_bus_reference_count": len(missing_bus_refs),
            "duplicate_branch_base_id_count": len(duplicate_branch_base_ids),
        },
        "consistency_flags": {
            "all_branch_endpoints_resolved_in_buses": len(missing_bus_refs) == 0,
            "branch_ids_are_unique": True,
        },
        "reconciliation": {
            "missing_bus_reference_sample": missing_bus_refs[:20],
            "duplicate_branch_base_id_sample": duplicate_branch_base_ids[:20],
        },
    }
    return {
        "branches": branches,
        "summary": summary,
    }


def export_branches(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    reader = XlsmReader(xlsm_path)
    payload = build_branches(reader)
    write_csv(
        outdir / "branches.csv",
        payload["branches"],
        fieldnames=[
            "branch_id",
            "branch_base_id",
            "branch_parallel_index",
            "from_bus",
            "to_bus",
            "circuit_id",
            "branch_type",
            "r_pu",
            "x_pu",
            "fmax_mw",
            "in_service_base",
            "closure_flag",
            "from_bus_in_buses",
            "to_bus_in_buses",
            "source_sheet",
            "source_row_number",
        ],
    )
    write_json(outdir / "branches_reconciliation_summary.json", payload["summary"])
    return payload

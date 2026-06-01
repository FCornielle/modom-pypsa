"""Construcción inicial de la tabla canónica `loads_time_series`."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from .xlsm import XlsmReader


DEMAND_SUFFIX_RE = re.compile(r"-D\d+$")


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


def canonicalize_load_id(load_id_raw: str) -> str:
    """Normaliza ids de `PDemanda` hacia la convención base de `e_datdem`.

    Evidencia del caso V449:
    - `PDemanda` usa sufijos tipo `-D1`, `-D2`
    - muchos ids equivalen a los de `e_datdem` si se reemplaza prefijo `Z` por `W`
      y se elimina el sufijo `-Dk`
    """
    code = clean(load_id_raw)
    code = DEMAND_SUFFIX_RE.sub("", code)
    if code.startswith("Z"):
        code = "W" + code[1:]
    return code


def extract_load_metadata_ids(reader: XlsmReader) -> list[str]:
    matrix = reader.read_sheet_matrix("e_datdem")
    out: list[str] = []
    for row in matrix[5:]:
        if not row:
            continue
        code = clean(row[0])
        if not code or code == "*":
            continue
        out.append(code)
    return out


def parse_smc_hours_row(row: list[str], start_idx: int = 9, end_idx: int = 33) -> list[float]:
    values: list[float] = []
    for idx in range(start_idx, min(len(row), end_idx)):
        value = to_float(row[idx])
        values.append(value if value is not None else 0.0)
    return values


def build_smc_load_registry(reader: XlsmReader) -> dict[str, dict[str, object]]:
    """Construye un registro por `ID DIGSILENT` usando `DEMANDA SMC`."""
    metadata_ids = set(extract_load_metadata_ids(reader))
    if "DEMANDA SMC" not in reader.workbook_sheet_names():
        return {}
    matrix = reader.read_sheet_matrix("DEMANDA SMC")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)

    for row in matrix[1:]:
        if len(row) < 10:
            continue
        load_id_raw = clean(row[5])
        bus_id = clean(row[6])
        if not load_id_raw or not bus_id:
            continue
        grouped[load_id_raw].append(
            {
                "smc_load_id": clean(row[0]),
                "status": clean(row[3]),
                "operator": clean(row[4]),
                "bus_id": bus_id,
                "load_name": clean(row[7]),
                "load_type": clean(row[8]),
                "energy_sum_mw": sum(parse_smc_hours_row(row)),
            }
        )

    registry: dict[str, dict[str, object]] = {}
    for load_id_raw, items in grouped.items():
        bus_candidates = sorted({str(item["bus_id"]) for item in items})
        active_bus_candidates = sorted(
            {
                str(item["bus_id"])
                for item in items
                if str(item["status"]).lower() == "activo"
            }
        )
        metadata_bus_candidates = sorted(
            {
                str(item["bus_id"])
                for item in items
                if str(item["bus_id"]) in metadata_ids
            }
        )

        resolved_bus_id = ""
        resolution_method = "unresolved"

        if len(bus_candidates) == 1:
            resolved_bus_id = bus_candidates[0]
            resolution_method = "unique_bus_in_demanda_smc"
        elif len(active_bus_candidates) == 1:
            resolved_bus_id = active_bus_candidates[0]
            resolution_method = "unique_active_bus_in_demanda_smc"
        elif len(metadata_bus_candidates) == 1:
            resolved_bus_id = metadata_bus_candidates[0]
            resolution_method = "unique_bus_matching_e_datdem"
        else:
            bus_energy: dict[str, float] = defaultdict(float)
            for item in items:
                bus_energy[str(item["bus_id"])] += float(item["energy_sum_mw"])
            if bus_energy:
                ordered = sorted(bus_energy.items(), key=lambda kv: (-kv[1], kv[0]))
                if len(ordered) == 1 or (
                    len(ordered) > 1 and ordered[0][1] > ordered[1][1]
                ):
                    resolved_bus_id = ordered[0][0]
                    resolution_method = "highest_energy_bus_in_demanda_smc"

        registry[load_id_raw] = {
            "load_id_raw": load_id_raw,
            "resolved_bus_id": resolved_bus_id,
            "resolution_method": resolution_method,
            "bus_candidate_count": len(bus_candidates),
            "bus_candidates": bus_candidates,
            "active_bus_candidates": active_bus_candidates,
            "metadata_bus_candidates": metadata_bus_candidates,
            "smc_row_count": len(items),
            "smc_load_id_examples": sorted(
                {str(item["smc_load_id"]) for item in items if str(item["smc_load_id"])}
            )[:10],
            "load_name_examples": sorted(
                {str(item["load_name"]) for item in items if str(item["load_name"])}
            )[:10],
            "load_type_examples": sorted(
                {str(item["load_type"]) for item in items if str(item["load_type"])}
            ),
        }
    return registry


def extract_pdemanda_raw_long(
    reader: XlsmReader,
    smc_registry: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Extrae `PDemanda` a formato largo sin perder filas repetidas."""
    matrix = reader.read_sheet_matrix("PDemanda")
    if not matrix:
        return {"raw_rows": [], "block_labels": []}

    header = matrix[0]
    block_labels = [clean(value) for value in header[1:] if clean(value)]
    raw_rows: list[dict[str, object]] = []

    for source_row_number, row in enumerate(matrix[1:], start=2):
        load_id_raw = clean(row[0]) if row else ""
        if not load_id_raw:
            continue
        for col_idx, block_label in enumerate(block_labels, start=1):
            value = row[col_idx] if col_idx < len(row) else ""
            p_set_mw = to_float(value)
            raw_rows.append(
                {
                    "load_id_raw": load_id_raw,
                    "load_id_canonical_heuristic": canonicalize_load_id(load_id_raw),
                    "resolved_bus_id": str(
                        smc_registry.get(load_id_raw, {}).get("resolved_bus_id", "")
                    ),
                    "bus_resolution_method": str(
                        smc_registry.get(load_id_raw, {}).get("resolution_method", "not_found")
                    ),
                    "source_row_number": source_row_number,
                "time_block_group": "load_blocks_pdemanda_24h",
                "time_block_id": f"h_{int(block_label):02d}",
                "time_block_order": int(block_label),
                "hour_block_start_label": f"{int(block_label) - 1:02d}:00",
                "snapshot_id": f"h_{int(block_label):02d}",
                "p_set_mw": p_set_mw if p_set_mw is not None else "",
                "source_sheet": "PDemanda",
                }
            )

    return {"raw_rows": raw_rows, "block_labels": block_labels}


def aggregate_load_rows(raw_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Agrega filas repetidas de `PDemanda` por barra resuelta y bloque."""
    grouped: dict[tuple[str, str], dict[str, object]] = {}

    for row in raw_rows:
        resolved_key = str(row["resolved_bus_id"]) or str(row["load_id_canonical_heuristic"])
        key = (resolved_key, str(row["time_block_id"]))
        current = grouped.get(key)
        value = row["p_set_mw"]
        value_num = float(value) if value != "" else 0.0

        if current is None:
            grouped[key] = {
                "load_id": resolved_key,
                "load_id_source": (
                    "resolved_bus_id" if str(row["resolved_bus_id"]) else "heuristic_load_id"
                ),
                "time_block_group": row["time_block_group"],
                "time_block_id": row["time_block_id"],
                "time_block_order": row["time_block_order"],
                "hour_block_start_label": row["hour_block_start_label"],
                "snapshot_id": row["snapshot_id"],
                "p_set_mw": value_num,
                "source_sheet": "PDemanda",
                "aggregation_row_count": 1,
                "load_id_raw_examples": [row["load_id_raw"]],
                "bus_resolution_method_examples": [row["bus_resolution_method"]],
            }
            continue

        current["p_set_mw"] = float(current["p_set_mw"]) + value_num
        current["aggregation_row_count"] = int(current["aggregation_row_count"]) + 1
        examples = list(current["load_id_raw_examples"])
        if row["load_id_raw"] not in examples:
            examples.append(row["load_id_raw"])
        current["load_id_raw_examples"] = examples
        method_examples = list(current["bus_resolution_method_examples"])
        if row["bus_resolution_method"] not in method_examples:
            method_examples.append(str(row["bus_resolution_method"]))
        current["bus_resolution_method_examples"] = method_examples

    rows = list(grouped.values())
    rows.sort(key=lambda item: (str(item["load_id"]), int(item["time_block_order"])))
    for row in rows:
        row["load_id_raw_examples"] = "|".join(row["load_id_raw_examples"])
        row["bus_resolution_method_examples"] = "|".join(row["bus_resolution_method_examples"])
    return rows


def build_loads_time_series(reader: XlsmReader) -> dict[str, object]:
    smc_registry = build_smc_load_registry(reader)
    extracted = extract_pdemanda_raw_long(reader, smc_registry)
    raw_rows = list(extracted["raw_rows"])
    block_labels = list(extracted["block_labels"])
    canonical_rows = aggregate_load_rows(raw_rows)

    pdemanda_raw_ids = [str(row["load_id_raw"]) for row in raw_rows[:: max(len(block_labels), 1)]]
    canonical_ids = sorted({str(row["load_id"]) for row in canonical_rows})
    e_datdem_ids = extract_load_metadata_ids(reader)

    canonical_set = set(canonical_ids)
    metadata_set = set(e_datdem_ids)
    unresolved_registry = [
        item for item in smc_registry.values() if not str(item["resolved_bus_id"])
    ]
    unresolved_registry.sort(key=lambda item: str(item["load_id_raw"]))

    reconciliation_summary = {
        "source_sheets": ["PDemanda", "DEMANDA SMC", "e_datdem"],
        "time_block_group": "load_blocks_pdemanda_24h",
        "hour_block_convention": {
            "h_01": "00:00-00:59",
            "h_24": "23:00-23:59",
        },
        "counts": {
            "pdemanda_raw_row_count": len(raw_rows),
            "pdemanda_raw_load_count": len(set(pdemanda_raw_ids)),
            "loads_time_series_row_count": len(canonical_rows),
            "loads_time_series_load_count": len(canonical_set),
            "e_datdem_load_count": len(metadata_set),
            "time_block_count": len(block_labels),
            "demanda_smc_registry_count": len(smc_registry),
            "resolved_bus_registry_count": sum(
                1 for item in smc_registry.values() if str(item["resolved_bus_id"])
            ),
            "unresolved_bus_registry_count": len(unresolved_registry),
        },
        "consistency_flags": {
            "uses_explicit_snapshot_mapping": False,
            "uses_canonical_24h_snapshots": True,
            "requires_snapshot_translation": False,
            "all_pdemanda_ids_found_in_demanda_smc": all(
                load_id in smc_registry for load_id in set(pdemanda_raw_ids)
            ),
        },
        "reconciliation": {
            "canonical_vs_e_datdem_exact_overlap_count": len(canonical_set & metadata_set),
            "canonical_not_in_e_datdem_sample": sorted(list(canonical_set - metadata_set))[:25],
            "e_datdem_not_in_canonical_sample": sorted(list(metadata_set - canonical_set))[:25],
            "unresolved_bus_registry_sample": unresolved_registry[:10],
        },
    }

    return {
        "raw_long_rows": raw_rows,
        "loads_time_series": canonical_rows,
        "smc_load_registry": list(smc_registry.values()),
        "reconciliation_summary": reconciliation_summary,
    }


def export_loads_time_series(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    reader = XlsmReader(xlsm_path)
    payload = build_loads_time_series(reader)

    write_csv(
        outdir / "pdemanda_raw_long.csv",
        payload["raw_long_rows"],
        fieldnames=[
            "load_id_raw",
            "load_id_canonical_heuristic",
            "resolved_bus_id",
            "bus_resolution_method",
            "source_row_number",
            "time_block_group",
            "time_block_id",
            "time_block_order",
            "hour_block_start_label",
            "snapshot_id",
            "p_set_mw",
            "source_sheet",
        ],
    )
    write_csv(
        outdir / "loads_time_series.csv",
        payload["loads_time_series"],
        fieldnames=[
            "load_id",
            "load_id_source",
            "time_block_group",
            "time_block_id",
            "time_block_order",
            "hour_block_start_label",
            "snapshot_id",
            "p_set_mw",
            "source_sheet",
            "aggregation_row_count",
            "load_id_raw_examples",
            "bus_resolution_method_examples",
        ],
    )
    write_csv(
        outdir / "smc_load_registry.csv",
        payload["smc_load_registry"],
        fieldnames=[
            "load_id_raw",
            "resolved_bus_id",
            "resolution_method",
            "bus_candidate_count",
            "bus_candidates",
            "active_bus_candidates",
            "metadata_bus_candidates",
            "smc_row_count",
            "smc_load_id_examples",
            "load_name_examples",
            "load_type_examples",
        ],
    )
    write_json(
        outdir / "loads_time_series_reconciliation_summary.json",
        payload["reconciliation_summary"],
    )
    return payload

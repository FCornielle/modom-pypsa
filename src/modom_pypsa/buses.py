"""Construcción inicial de la tabla canónica `buses`."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from .xlsm import XlsmReader


LEADING_STAR_RE = re.compile(r"^\*\s*")
VOLTAGE_RE = re.compile(
    r"(?<!\d)(345|230|138|115|69|34\.5|20|13\.8|13\.5|12\.47|12\.5|7\.2|4\.2|4\.16)(?!\d)"
)


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


def classify_bus_role(bus_name: str, bus_name_legacy: str) -> str:
    """Marca terminales virtuales de generador.

    En `MODOM` los bornes de baja tensión de los generadores aparecen como
    barras `TERMINAL ... VIRTUAL`. Su `v_nom_kv` real es la tensión nominal del
    generador, que el libro no trae explícitamente. Etiquetarlos permite separar
    una ausencia esperada (terminal de generador) de un hueco genuinamente
    desconocido, sin inventar tensiones.
    """
    text = " ".join(part for part in [clean(bus_name), clean(bus_name_legacy)] if part).upper()
    if "TERMINAL" in text or "VIRTUAL" in text:
        return "generator_terminal"
    return "network"


def infer_bus_voltage(
    bus_id: str,
    bus_name: str,
    bus_name_legacy: str,
) -> tuple[float | None, str, str]:
    text = " ".join(part for part in [clean(bus_name), clean(bus_name_legacy)] if part)
    matches = VOLTAGE_RE.findall(text)
    if matches:
        return float(matches[0]), "name_explicit", "high"

    suffix = clean(bus_id)[-1:] if clean(bus_id) else ""
    if suffix == "E":
        return 138.0, "suffix_E_default", "medium"
    if suffix == "F":
        return 69.0, "suffix_F_default", "medium"
    return None, "unresolved", "low"


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


def extract_transformer_neighbors(reader: XlsmReader) -> dict[str, set[str]]:
    matrix = reader.read_sheet_matrix("e_datred")
    neighbors: dict[str, set[str]] = {}
    for row in matrix[3:]:
        if len(row) < 5:
            continue
        from_bus = normalize_bus_code(row[0])
        to_bus = normalize_bus_code(row[2])
        circuit_id = clean(row[4])
        if not from_bus or not to_bus or not circuit_id.startswith("T"):
            continue
        neighbors.setdefault(from_bus, set()).add(to_bus)
        neighbors.setdefault(to_bus, set()).add(from_bus)
    return neighbors


def extract_line_neighbors(reader: XlsmReader) -> dict[str, set[str]]:
    """Vecinos conectados por línea (`L...`).

    Una línea no cambia el nivel de tensión: ambos extremos comparten `v_nom`.
    Esto permite resolver tensiones por consenso eléctrico real, no por heurística.
    """
    matrix = reader.read_sheet_matrix("e_datred")
    neighbors: dict[str, set[str]] = {}
    for row in matrix[3:]:
        if len(row) < 5:
            continue
        from_bus = normalize_bus_code(row[0])
        to_bus = normalize_bus_code(row[2])
        circuit_id = clean(row[4])
        if not from_bus or not to_bus or not circuit_id.startswith("L"):
            continue
        neighbors.setdefault(from_bus, set()).add(to_bus)
        neighbors.setdefault(to_bus, set()).add(from_bus)
    return neighbors


def build_buses(reader: XlsmReader) -> dict[str, object]:
    mapping_rows = extract_mapping_buses(reader)
    red_counts = extract_e_datred_bus_counts(reader)
    transformer_neighbors = extract_transformer_neighbors(reader)
    line_neighbors = extract_line_neighbors(reader)

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

    voltage_method_counts: Counter[str] = Counter()
    unresolved_voltage_rows: list[dict[str, object]] = []
    for item in buses_by_id.values():
        v_nom_kv, method, confidence = infer_bus_voltage(
            bus_id=str(item["bus_id_modom"]),
            bus_name=str(item["bus_name"]),
            bus_name_legacy=str(item["bus_name_legacy"]),
        )
        item["v_nom_kv"] = v_nom_kv if v_nom_kv is not None else ""
        item["v_nom_inference_method"] = method
        item["v_nom_confidence"] = confidence
        item["bus_role"] = classify_bus_role(
            str(item["bus_name"]), str(item["bus_name_legacy"])
        )

    line_inferred_count = 0
    for item in buses_by_id.values():
        if item["v_nom_kv"] != "":
            continue
        bus_id = str(item["bus_id_modom"])
        neighbor_values = sorted(
            {
                buses_by_id[other]["v_nom_kv"]
                for other in line_neighbors.get(bus_id, set())
                if other in buses_by_id and buses_by_id[other]["v_nom_kv"] != ""
            }
        )
        if len(neighbor_values) == 1:
            item["v_nom_kv"] = neighbor_values[0]
            item["v_nom_inference_method"] = "topology_line_consensus"
            item["v_nom_confidence"] = "medium"
            line_inferred_count += 1

    topology_inferred_count = 0
    for item in buses_by_id.values():
        if item["v_nom_kv"] != "":
            continue
        bus_id = str(item["bus_id_modom"])
        suffix = bus_id[-1:] if bus_id else ""
        if suffix not in {"C", "D"}:
            continue
        neighbor_values = sorted(
            {
                buses_by_id[other]["v_nom_kv"]
                for other in transformer_neighbors.get(bus_id, set())
                if other in buses_by_id and buses_by_id[other]["v_nom_kv"] != ""
            }
        )
        if len(neighbor_values) == 1:
            item["v_nom_kv"] = neighbor_values[0]
            item["v_nom_inference_method"] = "topology_transformer_consensus"
            item["v_nom_confidence"] = "low"
            topology_inferred_count += 1

    for item in buses_by_id.values():
        voltage_method_counts[str(item["v_nom_inference_method"])] += 1
        if item["v_nom_kv"] == "":
            unresolved_voltage_rows.append(
                {
                    "bus_id_modom": item["bus_id_modom"],
                    "bus_name": item["bus_name"],
                    "bus_id_legacy": item["bus_id_legacy"],
                    "bus_name_legacy": item["bus_name_legacy"],
                    "bus_origin": item["bus_origin"],
                    "bus_role": item["bus_role"],
                }
            )

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
            "buses_with_v_nom_kv_count": len(buses) - len(unresolved_voltage_rows),
            "buses_without_v_nom_kv_count": len(unresolved_voltage_rows),
            "v_nom_name_explicit_count": int(voltage_method_counts.get("name_explicit", 0)),
            "v_nom_suffix_E_default_count": int(voltage_method_counts.get("suffix_E_default", 0)),
            "v_nom_suffix_F_default_count": int(voltage_method_counts.get("suffix_F_default", 0)),
            "v_nom_topology_line_consensus_count": line_inferred_count,
            "v_nom_topology_transformer_consensus_count": topology_inferred_count,
            "unresolved_generator_terminal_count": sum(
                1 for row in unresolved_voltage_rows if row["bus_role"] == "generator_terminal"
            ),
            "unresolved_network_count": sum(
                1 for row in unresolved_voltage_rows if row["bus_role"] == "network"
            ),
        },
        "consistency_flags": {
            "all_buses_have_v_nom_kv": len(unresolved_voltage_rows) == 0,
        },
        "reconciliation": {
            "e_datred_only_bus_sample": sorted(list(red_bus_ids - mapped_bus_ids))[:40],
            "mapping_only_bus_sample": sorted(list(mapped_bus_ids - red_bus_ids))[:40],
            "unresolved_v_nom_bus_sample": unresolved_voltage_rows[:40],
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
            "v_nom_kv",
            "v_nom_inference_method",
            "v_nom_confidence",
            "bus_role",
            "source_sheet_primary",
            "bus_origin",
        ],
    )
    write_json(outdir / "buses_reconciliation_summary.json", payload["summary"])
    return payload

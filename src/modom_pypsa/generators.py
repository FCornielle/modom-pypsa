"""Construcción inicial de la tabla canónica `generators`."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

from .buses import build_buses, normalize_bus_code
from .xlsm import XlsmReader


GENERATOR_CODE_RE = re.compile(r"^G\d\S+$")
SITE_STOPWORDS = {
    "PARQUE",
    "EOLICO",
    "EÓLICO",
    "SOLAR",
    "FOTOVOLTAICO",
    "PLANTA",
    "CENTRAL",
}


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


def normalize_site_name(name: str) -> str:
    text = clean(name).upper()
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [token for token in text.split() if token and token not in SITE_STOPWORDS]
    return " ".join(tokens)


def parse_primary_e_datgen(reader: XlsmReader) -> list[dict[str, object]]:
    """Extrae solo el bloque primario de inventario base de `e_datgen`."""
    matrix = reader.read_sheet_matrix("e_datgen")
    rows: list[dict[str, object]] = []

    for row_idx, row in enumerate(matrix[4:], start=5):
        code = clean(row[0]) if row else ""
        if code == "+":
            break
        if not GENERATOR_CODE_RE.fullmatch(code):
            continue
        enabled_flag = clean(row[1]) if len(row) > 1 else ""
        pmax = clean(row[2]) if len(row) > 2 else ""
        pmin = clean(row[3]) if len(row) > 3 else ""
        if enabled_flag not in {"0", "1"} or pmax == "" or pmin == "":
            continue

        rows.append(
            {
                "generator_id": code,
                "enabled_flag": enabled_flag,
                "pmax_mw": to_float(row[2]) if to_float(row[2]) is not None else "",
                "pmin_mw": to_float(row[3]) if to_float(row[3]) is not None else "",
                "cvp": to_float(row[4]) if len(row) > 4 and to_float(row[4]) is not None else "",
                "technology_group": clean(row[5]) if len(row) > 5 else "",
                "ssaa": to_float(row[6]) if len(row) > 6 and to_float(row[6]) is not None else "",
                "mrpf": to_float(row[7]) if len(row) > 7 and to_float(row[7]) is not None else "",
                "mrsf": to_float(row[8]) if len(row) > 8 and to_float(row[8]) is not None else "",
                "factora": to_float(row[9]) if len(row) > 9 and to_float(row[9]) is not None else "",
                "heat_parameter": to_float(row[10]) if len(row) > 10 and to_float(row[10]) is not None else "",
                "pgn_mw": to_float(row[11]) if len(row) > 11 and to_float(row[11]) is not None else "",
                "source_row_number": row_idx,
                "source_sheet_primary": "e_datgen",
            }
        )
    return rows


def parse_generator_mapping(reader: XlsmReader) -> dict[str, dict[str, str]]:
    matrix = reader.read_sheet_matrix("MAPEO CENTRALES DE GENERACION")
    out: dict[str, dict[str, str]] = {}
    for row in matrix[4:]:
        if len(row) < 4 or not clean(row[1]):
            continue
        out[clean(row[1])] = {
            "generator_id_legacy": clean(row[0]),
            "generator_name": clean(row[2]),
            "code_changed": clean(row[3]),
        }
    return out


def parse_factor_node_injection(reader: XlsmReader) -> dict[str, dict[str, str]]:
    matrix = reader.read_sheet_matrix("Factores de Nodo (Inyección)")
    out: dict[str, dict[str, str]] = {}
    for row in matrix[2:]:
        if len(row) < 4 or not clean(row[0]):
            continue
        out[clean(row[0])] = {
            "generator_name_factor_node": clean(row[1]),
            "bus_id_factor_node": normalize_bus_code(row[2]),
            "smc_point_id": clean(row[3]),
        }
    return out


def parse_centrales_zonas(reader: XlsmReader) -> dict[str, dict[str, str]]:
    matrix = reader.read_sheet_matrix("Centrales (Zonas)")
    out: dict[str, dict[str, str]] = {}
    for row in matrix[2:]:
        if len(row) < 5 or not clean(row[0]):
            continue
        out[clean(row[0])] = {
            "grid_name": clean(row[1]),
            "terminal_bus_id": normalize_bus_code(row[4]),
        }
    return out


def parse_availability_names(reader: XlsmReader) -> dict[str, str]:
    matrix = reader.read_sheet_matrix("Reporte de Disponibilidad")
    out: dict[str, str] = {}
    for row in matrix[1:]:
        if len(row) < 2 or not clean(row[0]):
            continue
        out[clean(row[0])] = clean(row[1])
    return out


def build_generators(reader: XlsmReader) -> dict[str, object]:
    buses_payload = build_buses(reader)
    bus_lookup: dict[str, str] = {}
    for row in buses_payload["buses"]:
        bus_id_modom = str(row["bus_id_modom"])
        bus_lookup[bus_id_modom] = bus_id_modom
        bus_id_legacy = clean(str(row.get("bus_id_legacy", "")))
        if bus_id_legacy:
            bus_lookup[bus_id_legacy] = bus_id_modom
    bus_ids = set(bus_lookup.values())

    primary_rows = parse_primary_e_datgen(reader)
    mapping = parse_generator_mapping(reader)
    factor_nodes = parse_factor_node_injection(reader)
    centrales = parse_centrales_zonas(reader)
    availability_names = parse_availability_names(reader)

    normalized_factor_sites: dict[str, set[str]] = defaultdict(set)
    for item in factor_nodes.values():
        site_name = normalize_site_name(item["generator_name_factor_node"])
        if site_name and item["bus_id_factor_node"]:
            normalized_factor_sites[site_name].add(item["bus_id_factor_node"])

    generators: list[dict[str, object]] = []
    unresolved_bus_rows: list[dict[str, object]] = []

    for row in primary_rows:
        generator_id = str(row["generator_id"])
        mapped = mapping.get(generator_id, {})
        factor = factor_nodes.get(generator_id, {})
        central = centrales.get(generator_id, {})

        generator_name = (
            mapped.get("generator_name")
            or availability_names.get(generator_id)
            or factor.get("generator_name_factor_node")
            or ""
        )

        bus_id = ""
        bus_resolution_method = "unresolved"
        factor_bus = bus_lookup.get(str(factor.get("bus_id_factor_node", "")), "")
        central_bus = bus_lookup.get(str(central.get("terminal_bus_id", "")), "")
        if factor_bus:
            bus_id = factor_bus
            bus_resolution_method = "factor_node_injection"
        elif central_bus:
            bus_id = central_bus
            bus_resolution_method = "centrales_zonas_terminal"
        else:
            site_name = normalize_site_name(generator_name)
            site_buses = sorted(
                {
                    bus_lookup[candidate]
                    for candidate in normalized_factor_sites.get(site_name, set())
                    if candidate in bus_lookup
                }
            )
            if len(site_buses) == 1:
                bus_id = site_buses[0]
                bus_resolution_method = "site_name_inferred_from_factor_node_peer"

        bus_id_in_buses = bus_id in bus_ids if bus_id else False
        if bus_id and not bus_id_in_buses:
            bus_id = ""
            bus_resolution_method = "unresolved"
            bus_id_in_buses = False

        item = {
            "generator_id": generator_id,
            "generator_name": generator_name,
            "generator_id_legacy": mapped.get("generator_id_legacy", ""),
            "code_changed": mapped.get("code_changed", ""),
            "bus_id": bus_id,
            "bus_resolution_method": bus_resolution_method,
            "bus_id_in_buses": bus_id_in_buses,
            "enabled_flag": row["enabled_flag"],
            "pmax_mw": row["pmax_mw"],
            "pmin_mw": row["pmin_mw"],
            "cvp": row["cvp"],
            "technology_group": row["technology_group"],
            "ssaa": row["ssaa"],
            "mrpf": row["mrpf"],
            "mrsf": row["mrsf"],
            "factora": row["factora"],
            "heat_parameter": row["heat_parameter"],
            "pgn_mw": row["pgn_mw"],
            "source_sheet_primary": row["source_sheet_primary"],
            "source_row_number": row["source_row_number"],
            "source_name_sheet": (
                "MAPEO CENTRALES DE GENERACION"
                if mapped.get("generator_name")
                else "Reporte de Disponibilidad"
                if availability_names.get(generator_id)
                else "Factores de Nodo (Inyección)"
                if factor.get("generator_name_factor_node")
                else ""
            ),
            "factor_node_bus_id": factor.get("bus_id_factor_node", ""),
            "factor_node_smc_point_id": factor.get("smc_point_id", ""),
            "centrales_terminal_bus_id": central.get("terminal_bus_id", ""),
        }
        generators.append(item)
        if not bus_id:
            unresolved_bus_rows.append(
                {
                    "generator_id": generator_id,
                    "generator_name": generator_name,
                    "technology_group": row["technology_group"],
                }
            )

    generators.sort(key=lambda item: str(item["generator_id"]))
    summary = {
        "source_sheets": [
            "e_datgen",
            "MAPEO CENTRALES DE GENERACION",
            "Factores de Nodo (Inyección)",
            "Centrales (Zonas)",
            "Reporte de Disponibilidad",
        ],
        "counts": {
            "generators_row_count": len(generators),
            "resolved_bus_count": sum(1 for row in generators if str(row["bus_id"])),
            "unresolved_bus_count": sum(1 for row in generators if not str(row["bus_id"])),
            "mapped_name_count": sum(1 for row in generators if str(row["generator_name"])),
        },
        "consistency_flags": {
            "all_generator_ids_unique": len({str(row["generator_id"]) for row in generators}) == len(generators),
            "all_resolved_buses_exist_in_buses": all(
                (not str(row["bus_id"])) or bool(row["bus_id_in_buses"]) for row in generators
            ),
        },
        "reconciliation": {
            "unresolved_bus_sample": unresolved_bus_rows[:20],
        },
    }
    return {
        "generators": generators,
        "summary": summary,
    }


def export_generators(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    reader = XlsmReader(xlsm_path)
    payload = build_generators(reader)
    write_csv(
        outdir / "generators.csv",
        payload["generators"],
        fieldnames=[
            "generator_id",
            "generator_name",
            "generator_id_legacy",
            "code_changed",
            "bus_id",
            "bus_resolution_method",
            "bus_id_in_buses",
            "enabled_flag",
            "pmax_mw",
            "pmin_mw",
            "cvp",
            "technology_group",
            "ssaa",
            "mrpf",
            "mrsf",
            "factora",
            "heat_parameter",
            "pgn_mw",
            "source_sheet_primary",
            "source_row_number",
            "source_name_sheet",
            "factor_node_bus_id",
            "factor_node_smc_point_id",
            "centrales_terminal_bus_id",
        ],
    )
    write_json(outdir / "generators_reconciliation_summary.json", payload["summary"])
    return payload

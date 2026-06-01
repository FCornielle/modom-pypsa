"""Exporta una traducción v1 de ramas canónicas a componentes PyPSA."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def clean(value: object) -> str:
    return str(value or "").strip()


def to_float(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_bus_lookup(buses: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {clean(row.get("bus_id_modom")): row for row in buses if clean(row.get("bus_id_modom"))}


def infer_voltage_pair_status(
    component: str,
    v_nom_bus0_kv: float | None,
    v_nom_bus1_kv: float | None,
) -> str:
    if v_nom_bus0_kv is None or v_nom_bus1_kv is None:
        return "missing_bus_v_nom"
    if component in {"line", "auxiliary_tap_link"}:
        if v_nom_bus0_kv == v_nom_bus1_kv:
            return "same_voltage_ok"
        return "line_voltage_mismatch"
    if component == "transformer":
        if v_nom_bus0_kv == v_nom_bus1_kv:
            return "same_voltage_transformer_suspect"
        return "different_voltage_ok"
    return "component_voltage_status_unknown"


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_pypsa_branch_components(
    branches: list[dict[str, str]],
    buses: list[dict[str, str]],
) -> dict[str, object]:
    lines: list[dict[str, object]] = []
    transformers: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    bus_lookup = build_bus_lookup(buses)

    for row in branches:
        include = clean(row.get("pypsa_v1_include")).lower() == "true"
        component = clean(row.get("pypsa_v1_component"))
        branch_id = clean(row.get("branch_id"))
        source_row_number = clean(row.get("source_row_number"))
        bus0 = clean(row.get("from_bus"))
        bus1 = clean(row.get("to_bus"))
        bus0_data = bus_lookup.get(bus0, {})
        bus1_data = bus_lookup.get(bus1, {})
        v_nom_bus0_kv = to_float(bus0_data.get("v_nom_kv"))
        v_nom_bus1_kv = to_float(bus1_data.get("v_nom_kv"))
        voltage_pair_status = infer_voltage_pair_status(component, v_nom_bus0_kv, v_nom_bus1_kv)
        base_payload = {
            "name": branch_id,
            "bus0": bus0,
            "bus1": bus1,
            "v_nom_bus0_kv": v_nom_bus0_kv if v_nom_bus0_kv is not None else "",
            "v_nom_bus1_kv": v_nom_bus1_kv if v_nom_bus1_kv is not None else "",
            "voltage_pair_status": voltage_pair_status,
            "r_pu_hint": to_float(row.get("r_pu")) if to_float(row.get("r_pu")) is not None else "",
            "x_pu_hint": to_float(row.get("x_pu")) if to_float(row.get("x_pu")) is not None else "",
            "s_nom_mva_hint": (
                to_float(row.get("fmax_mw")) if to_float(row.get("fmax_mw")) is not None else ""
            ),
            "source_branch_id": branch_id,
            "source_branch_type": clean(row.get("branch_type")),
            "source_row_number": source_row_number,
            "notes": clean(row.get("pypsa_v1_mapping_reason")),
        }

        if not include:
            excluded.append(
                {
                    "branch_id": branch_id,
                    "branch_type": clean(row.get("branch_type")),
                    "from_bus": clean(row.get("from_bus")),
                    "to_bus": clean(row.get("to_bus")),
                    "pypsa_v1_component": component,
                    "exclusion_reason": clean(row.get("pypsa_v1_mapping_reason")),
                    "closure_semantics_hint": clean(row.get("closure_semantics_hint")),
                    "operational_status": clean(row.get("operational_status")),
                    "closure_flag": clean(row.get("closure_flag")),
                    "tap_ratio_hint": clean(row.get("tap_ratio_hint")),
                    "v_nom_bus0_kv": v_nom_bus0_kv if v_nom_bus0_kv is not None else "",
                    "v_nom_bus1_kv": v_nom_bus1_kv if v_nom_bus1_kv is not None else "",
                    "voltage_pair_status": voltage_pair_status,
                    "source_row_number": source_row_number,
                }
            )
            continue

        if component == "line":
            lines.append(base_payload)
            continue

        if component == "transformer":
            transformers.append(
                {
                    **base_payload,
                    "tap_ratio_hint": (
                        to_float(row.get("tap_ratio_hint"))
                        if to_float(row.get("tap_ratio_hint")) is not None
                        else ""
                    ),
                    "has_tap_ratio_hint": clean(row.get("tap_ratio_hint")) != "",
                    "tap_side_hint": "",
                }
            )
            continue

        excluded.append(
            {
                "branch_id": branch_id,
                "branch_type": clean(row.get("branch_type")),
                "from_bus": clean(row.get("from_bus")),
                "to_bus": clean(row.get("to_bus")),
                "pypsa_v1_component": component,
                "exclusion_reason": "unsupported_pypsa_v1_component",
                "closure_semantics_hint": clean(row.get("closure_semantics_hint")),
                "operational_status": clean(row.get("operational_status")),
                "closure_flag": clean(row.get("closure_flag")),
                "tap_ratio_hint": clean(row.get("tap_ratio_hint")),
                "v_nom_bus0_kv": v_nom_bus0_kv if v_nom_bus0_kv is not None else "",
                "v_nom_bus1_kv": v_nom_bus1_kv if v_nom_bus1_kv is not None else "",
                "voltage_pair_status": voltage_pair_status,
                "source_row_number": source_row_number,
            }
        )

    summary = {
        "counts": {
            "input_buses": len(buses),
            "input_branches": len(branches),
            "pypsa_v1_lines": len(lines),
            "pypsa_v1_transformers": len(transformers),
            "pypsa_v1_excluded_branches": len(excluded),
            "pypsa_v1_transformers_with_tap_ratio_hint": sum(
                1 for row in transformers if row["has_tap_ratio_hint"]
            ),
            "line_same_voltage_ok_count": sum(
                1 for row in lines if row["voltage_pair_status"] == "same_voltage_ok"
            ),
            "line_voltage_mismatch_count": sum(
                1 for row in lines if row["voltage_pair_status"] == "line_voltage_mismatch"
            ),
            "line_missing_bus_v_nom_count": sum(
                1 for row in lines if row["voltage_pair_status"] == "missing_bus_v_nom"
            ),
            "transformer_different_voltage_ok_count": sum(
                1 for row in transformers if row["voltage_pair_status"] == "different_voltage_ok"
            ),
            "transformer_same_voltage_suspect_count": sum(
                1
                for row in transformers
                if row["voltage_pair_status"] == "same_voltage_transformer_suspect"
            ),
            "transformer_missing_bus_v_nom_count": sum(
                1 for row in transformers if row["voltage_pair_status"] == "missing_bus_v_nom"
            ),
        },
        "assumptions": [
            "Las columnas `r_pu_hint`, `x_pu_hint` y `s_nom_mva_hint` son insumos provisionales para PyPSA v1, no una validación final de unidades.",
            "Los enlaces clasificados como `auxiliary_tap_link` se excluyen del modelo serie v1.",
            "Los transformadores con `tap_ratio_hint` conservan el valor observado en `closure_flag`, pero la semántica final de tap_side y base sigue pendiente.",
            "La consistencia de `v_nom_kv` se usa como auditoría estructural de la exportación v1, no como sustituto de una validación completa de parámetros eléctricos.",
        ],
    }
    return {
        "lines": lines,
        "transformers": transformers,
        "excluded": excluded,
        "summary": summary,
    }


def export_pypsa_branch_components(
    branches_path: Path,
    buses_path: Path,
    outdir: Path,
) -> dict[str, object]:
    payload = build_pypsa_branch_components(read_csv(branches_path), read_csv(buses_path))
    write_csv(
        outdir / "lines_v1.csv",
        payload["lines"],
        [
            "name",
            "bus0",
            "bus1",
            "v_nom_bus0_kv",
            "v_nom_bus1_kv",
            "voltage_pair_status",
            "r_pu_hint",
            "x_pu_hint",
            "s_nom_mva_hint",
            "source_branch_id",
            "source_branch_type",
            "source_row_number",
            "notes",
        ],
    )
    write_csv(
        outdir / "transformers_v1.csv",
        payload["transformers"],
        [
            "name",
            "bus0",
            "bus1",
            "v_nom_bus0_kv",
            "v_nom_bus1_kv",
            "voltage_pair_status",
            "r_pu_hint",
            "x_pu_hint",
            "s_nom_mva_hint",
            "tap_ratio_hint",
            "has_tap_ratio_hint",
            "tap_side_hint",
            "source_branch_id",
            "source_branch_type",
            "source_row_number",
            "notes",
        ],
    )
    write_csv(
        outdir / "excluded_branches_v1.csv",
        payload["excluded"],
        [
            "branch_id",
            "branch_type",
            "from_bus",
            "to_bus",
            "pypsa_v1_component",
            "exclusion_reason",
            "closure_semantics_hint",
            "operational_status",
            "closure_flag",
            "tap_ratio_hint",
            "v_nom_bus0_kv",
            "v_nom_bus1_kv",
            "voltage_pair_status",
            "source_row_number",
        ],
    )
    write_json(outdir / "pypsa_branch_components_summary.json", payload["summary"])
    return payload

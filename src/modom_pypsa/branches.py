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


def infer_series_parameter_status(r_pu: float | None, x_pu: float | None) -> str:
    if r_pu is None or x_pu is None:
        return "missing_series_parameter"
    if x_pu <= 0:
        return "nonpositive_reactance"
    if r_pu < 0:
        return "negative_resistance"
    return "series_parameter_present"


def infer_operational_status(in_service_base: str, closure_flag: str) -> str:
    status = clean(in_service_base)
    closure = clean(closure_flag)
    if status == "0":
        return "out_of_service"
    if closure == "0":
        return "open"
    if closure == "1":
        return "closed"
    return "closure_fractional_or_unknown"


def infer_closure_semantics_hint(
    branch_type: str,
    closure_flag: str,
    from_bus_name: str,
    to_bus_name: str,
    operational_status: str,
) -> str:
    closure = clean(closure_flag)
    if closure in {"", "0", "1"}:
        return "binary_switch_state"
    if operational_status == "out_of_service":
        return "nonbinary_control_value_on_out_of_service_branch"
    names_upper = f"{clean(from_bus_name)} {clean(to_bus_name)}".upper()
    if branch_type == "transformer":
        return "tap_ratio_like"
    if "TAP " in names_upper or names_upper.startswith("TAP"):
        return "tap_link_like"
    return "nonbinary_network_parameter_unknown"


def infer_pypsa_v1_mapping(
    branch_type: str,
    operational_status: str,
    closure_semantics_hint: str,
    closure_flag: str,
) -> dict[str, object]:
    tap_ratio_hint = ""
    if closure_semantics_hint == "tap_ratio_like":
        tap_ratio_hint = closure_flag
        if operational_status == "out_of_service":
            return {
                "pypsa_v1_component": "transformer",
                "pypsa_v1_include": False,
                "tap_ratio_hint": tap_ratio_hint,
                "pypsa_v1_mapping_reason": "out_of_service_transformer_with_tap_ratio",
            }
        return {
            "pypsa_v1_component": "transformer",
            "pypsa_v1_include": True,
            "tap_ratio_hint": tap_ratio_hint,
            "pypsa_v1_mapping_reason": "transformer_with_tap_ratio",
        }

    if closure_semantics_hint == "tap_link_like":
        return {
            "pypsa_v1_component": "auxiliary_tap_link",
            "pypsa_v1_include": False,
            "tap_ratio_hint": closure_flag,
            "pypsa_v1_mapping_reason": "excluded_auxiliary_tap_link",
        }

    if operational_status == "out_of_service":
        return {
            "pypsa_v1_component": branch_type,
            "pypsa_v1_include": False,
            "tap_ratio_hint": tap_ratio_hint,
            "pypsa_v1_mapping_reason": "out_of_service_base_case",
        }

    if closure_semantics_hint == "nonbinary_network_parameter_unknown":
        return {
            "pypsa_v1_component": branch_type,
            "pypsa_v1_include": False,
            "tap_ratio_hint": closure_flag,
            "pypsa_v1_mapping_reason": "nonbinary_parameter_pending_interpretation",
        }

    return {
        "pypsa_v1_component": branch_type,
        "pypsa_v1_include": True,
        "tap_ratio_hint": tap_ratio_hint,
        "pypsa_v1_mapping_reason": "standard_branch",
    }


def build_branches(reader: XlsmReader) -> dict[str, object]:
    buses_payload = build_buses(reader)
    bus_ids = {str(row["bus_id_modom"]) for row in buses_payload["buses"]}
    bus_names = {
        str(row["bus_id_modom"]): str(row.get("bus_name", ""))
        for row in buses_payload["buses"]
    }

    matrix = reader.read_sheet_matrix("e_datred")
    branches: list[dict[str, object]] = []
    missing_bus_refs: list[dict[str, object]] = []
    branch_base_id_counts: Counter[str] = Counter()
    closure_nonbinary_rows: list[dict[str, object]] = []
    base_out_of_service_rows: list[dict[str, object]] = []
    series_parameter_issue_rows: list[dict[str, object]] = []
    thermal_limit_issue_rows: list[dict[str, object]] = []

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
        from_bus_name = bus_names.get(from_bus, "")
        to_bus_name = bus_names.get(to_bus, "")
        r_pu = to_float(row[6])
        x_pu = to_float(row[7])
        fmax_mw = to_float(row[8])
        in_service_base = clean(row[9])
        closure_flag = clean(row[10])
        series_parameter_status = infer_series_parameter_status(r_pu, x_pu)
        operational_status = infer_operational_status(in_service_base, closure_flag)
        closure_flag_is_binary = closure_flag in {"0", "1"}
        closure_semantics_hint = infer_closure_semantics_hint(
            branch_type=branch_type,
            closure_flag=closure_flag,
            from_bus_name=from_bus_name,
            to_bus_name=to_bus_name,
            operational_status=operational_status,
        )
        pypsa_v1_mapping = infer_pypsa_v1_mapping(
            branch_type=branch_type,
            operational_status=operational_status,
            closure_semantics_hint=closure_semantics_hint,
            closure_flag=closure_flag,
        )
        thermal_limit_status = (
            "positive_thermal_limit"
            if fmax_mw is not None and fmax_mw > 0
            else "missing_or_nonpositive_thermal_limit"
        )

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

        if not closure_flag_is_binary:
            closure_nonbinary_rows.append(
                {
                    "source_row_number": row_idx,
                    "branch_id": branch_id,
                    "closure_flag": closure_flag,
                    "closure_semantics_hint": closure_semantics_hint,
                }
            )
        if operational_status == "out_of_service":
            base_out_of_service_rows.append(
                {
                    "source_row_number": row_idx,
                    "branch_id": branch_id,
                    "in_service_base": in_service_base,
                }
            )
        if series_parameter_status != "series_parameter_present":
            series_parameter_issue_rows.append(
                {
                    "source_row_number": row_idx,
                    "branch_id": branch_id,
                    "series_parameter_status": series_parameter_status,
                    "r_pu": r_pu if r_pu is not None else "",
                    "x_pu": x_pu if x_pu is not None else "",
                }
            )
        if thermal_limit_status != "positive_thermal_limit":
            thermal_limit_issue_rows.append(
                {
                    "source_row_number": row_idx,
                    "branch_id": branch_id,
                    "fmax_mw": fmax_mw if fmax_mw is not None else "",
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
                "r_pu": r_pu if r_pu is not None else "",
                "x_pu": x_pu if x_pu is not None else "",
                "fmax_mw": fmax_mw if fmax_mw is not None else "",
                "in_service_base": in_service_base,
                "closure_flag": closure_flag,
                "series_parameter_status": series_parameter_status,
                "thermal_limit_status": thermal_limit_status,
                "closure_flag_is_binary": closure_flag_is_binary,
                "operational_status": operational_status,
                "closure_semantics_hint": closure_semantics_hint,
                "pypsa_v1_component": pypsa_v1_mapping["pypsa_v1_component"],
                "pypsa_v1_include": pypsa_v1_mapping["pypsa_v1_include"],
                "tap_ratio_hint": pypsa_v1_mapping["tap_ratio_hint"],
                "pypsa_v1_mapping_reason": pypsa_v1_mapping["pypsa_v1_mapping_reason"],
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
            "closure_nonbinary_count": len(closure_nonbinary_rows),
            "base_out_of_service_count": len(base_out_of_service_rows),
            "series_parameter_issue_count": len(series_parameter_issue_rows),
            "thermal_limit_issue_count": len(thermal_limit_issue_rows),
            "closure_semantics_tap_ratio_like_count": sum(
                1
                for row in branches
                if row["closure_semantics_hint"] == "tap_ratio_like"
            ),
            "closure_semantics_tap_link_like_count": sum(
                1
                for row in branches
                if row["closure_semantics_hint"] == "tap_link_like"
            ),
            "pypsa_v1_included_count": sum(1 for row in branches if row["pypsa_v1_include"]),
            "pypsa_v1_excluded_count": sum(1 for row in branches if not row["pypsa_v1_include"]),
            "pypsa_v1_transformer_tap_candidate_count": sum(
                1
                for row in branches
                if row["pypsa_v1_mapping_reason"] == "transformer_with_tap_ratio"
            ),
            "pypsa_v1_auxiliary_tap_link_count": sum(
                1
                for row in branches
                if row["pypsa_v1_component"] == "auxiliary_tap_link"
            ),
        },
        "consistency_flags": {
            "all_branch_endpoints_resolved_in_buses": len(missing_bus_refs) == 0,
            "branch_ids_are_unique": True,
            "all_branches_have_series_parameters": len(series_parameter_issue_rows) == 0,
            "all_branches_have_positive_thermal_limit": len(thermal_limit_issue_rows) == 0,
            "closure_flags_are_binary": len(closure_nonbinary_rows) == 0,
            "branch_units_confirmed_for_pypsa": False,
        },
        "reconciliation": {
            "missing_bus_reference_sample": missing_bus_refs[:20],
            "duplicate_branch_base_id_sample": duplicate_branch_base_ids[:20],
            "closure_nonbinary_sample": closure_nonbinary_rows[:20],
            "base_out_of_service_sample": base_out_of_service_rows[:20],
            "series_parameter_issue_sample": series_parameter_issue_rows[:20],
            "thermal_limit_issue_sample": thermal_limit_issue_rows[:20],
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
            "series_parameter_status",
            "thermal_limit_status",
            "closure_flag_is_binary",
            "operational_status",
            "closure_semantics_hint",
            "pypsa_v1_component",
            "pypsa_v1_include",
            "tap_ratio_hint",
            "pypsa_v1_mapping_reason",
            "from_bus_in_buses",
            "to_bus_in_buses",
            "source_sheet",
            "source_row_number",
        ],
    )
    write_json(outdir / "branches_reconciliation_summary.json", payload["summary"])
    return payload

"""Despacho económico base para la capa canónica de MODOM.

La primera versión implementa un caso `copperplate` de un solo snapshot:

- demanda agregada de un bloque horario
- disponibilidad de generación de un período de despacho
- despacho por orden de mérito usando `cvp` como costo marginal

Este módulo no intenta todavía replicar el OPF de red de PyPSA. Antes de eso
hay que resolver al menos:

- nivel de tensión de barras
- unidades correctas de impedancia para ramas
- tratamiento operativo completo de `p_min`
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results" / "dispatch_basecase"
MISSING_COST_FALLBACK = 1_000_000.0


@dataclass(frozen=True)
class DispatchInputs:
    generators_path: Path
    availability_path: Path
    loads_path: Path
    buses_path: Path
    branches_path: Path
    snapshots_path: Path


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


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_inputs(data_dir: Path) -> DispatchInputs:
    return DispatchInputs(
        generators_path=data_dir / "generators" / "generators.csv",
        availability_path=data_dir / "generator_availability" / "generator_availability.csv",
        loads_path=data_dir / "loads_time_series" / "loads_time_series.csv",
        buses_path=data_dir / "buses" / "buses.csv",
        branches_path=data_dir / "branches" / "branches.csv",
        snapshots_path=data_dir / "snapshots" / "snapshots.csv",
    )


def validate_dispatch_inputs(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, object]:
    inputs = resolve_inputs(data_dir)
    missing_files = [str(path) for path in inputs.__dict__.values() if not path.exists()]
    if missing_files:
        return {
            "ok": False,
            "errors": [{"type": "missing_file", "path": path} for path in missing_files],
            "counts": {},
            "warnings": [],
            "network_constraints_ready": False,
        }

    generators = read_csv(inputs.generators_path)
    availability = read_csv(inputs.availability_path)
    loads = read_csv(inputs.loads_path)
    buses = read_csv(inputs.buses_path)
    branches = read_csv(inputs.branches_path)
    snapshots = read_csv(inputs.snapshots_path)

    generator_ids = {clean(row["generator_id"]) for row in generators}
    availability_ids = {clean(row["generator_id"]) for row in availability}
    load_ids = {clean(row["load_id"]) for row in loads}
    bus_ids = {clean(row["bus_id_modom"]) for row in buses}
    buses_with_v_nom = sum(1 for row in buses if clean(row.get("v_nom_kv")))
    buses_without_v_nom = len(buses) - buses_with_v_nom

    warnings: list[dict[str, object]] = []
    raw_pmax_lt_pmin = 0
    effective_pmax_lt_pmin = 0
    raw_missing_cost = 0
    effective_missing_cost = 0
    missing_bus = 0
    for row in generators:
        pmax = to_float(row.get("pmax_mw"))
        pmin = to_float(row.get("pmin_mw"))
        if pmax is not None and pmin is not None and pmax < pmin:
            raw_pmax_lt_pmin += 1
        effective_pmax = to_float(row.get("effective_pmax_mw"))
        effective_pmin = to_float(row.get("effective_pmin_mw"))
        if (
            effective_pmax is not None
            and effective_pmin is not None
            and effective_pmax < effective_pmin
        ):
            effective_pmax_lt_pmin += 1
        if to_float(row.get("cvp")) is None:
            raw_missing_cost += 1
        if to_float(row.get("effective_cvp")) is None and to_float(row.get("cvp")) is None:
            effective_missing_cost += 1
        if clean(row.get("bus_id")) not in bus_ids:
            missing_bus += 1

    snapshot_ids = {clean(row["snapshot_id"]) for row in snapshots}
    load_blocks = {clean(row["time_block_id"]) for row in loads}

    if effective_pmax_lt_pmin:
        warnings.append(
            {
                "type": "generator_capacity_inconsistency",
                "detail": "Aún hay unidades con límites efectivos inconsistentes.",
                "count": effective_pmax_lt_pmin,
            }
        )
    if effective_missing_cost:
        warnings.append(
            {
                "type": "missing_generator_cost",
                "detail": "Aún hay unidades sin costo marginal efectivo; el despacho base les asigna un costo de respaldo muy alto.",
                "count": effective_missing_cost,
            }
        )

    branch_series_issues = 0
    branch_thermal_issues = 0
    branch_closure_nonbinary = 0
    branch_closure_tap_ratio_like = 0
    branch_closure_tap_link_like = 0
    pypsa_v1_branch_included = 0
    pypsa_v1_branch_excluded = 0
    pypsa_v1_transformer_tap_candidates = 0
    for row in branches:
        series_parameter_status = clean(row.get("series_parameter_status"))
        if series_parameter_status:
            if series_parameter_status != "series_parameter_present":
                branch_series_issues += 1
        else:
            r_pu = to_float(row.get("r_pu"))
            x_pu = to_float(row.get("x_pu"))
            if r_pu is None or x_pu is None or x_pu <= 0 or r_pu < 0:
                branch_series_issues += 1

        thermal_limit_status = clean(row.get("thermal_limit_status"))
        if thermal_limit_status:
            if thermal_limit_status != "positive_thermal_limit":
                branch_thermal_issues += 1
        else:
            fmax_mw = to_float(row.get("fmax_mw"))
            if fmax_mw is None or fmax_mw <= 0:
                branch_thermal_issues += 1

        closure_flag_is_binary = clean(row.get("closure_flag_is_binary")).lower()
        if closure_flag_is_binary:
            if closure_flag_is_binary != "true":
                branch_closure_nonbinary += 1
        elif clean(row.get("closure_flag")) not in {"", "0", "1"}:
            branch_closure_nonbinary += 1
        semantics_hint = clean(row.get("closure_semantics_hint"))
        if semantics_hint == "tap_ratio_like":
            branch_closure_tap_ratio_like += 1
        elif semantics_hint == "tap_link_like":
            branch_closure_tap_link_like += 1
        if clean(row.get("pypsa_v1_include")).lower() == "true":
            pypsa_v1_branch_included += 1
        elif clean(row.get("pypsa_v1_include")).lower() == "false":
            pypsa_v1_branch_excluded += 1
        if clean(row.get("pypsa_v1_mapping_reason")) == "transformer_with_tap_ratio":
            pypsa_v1_transformer_tap_candidates += 1

    network_topology_ready = (
        len(branches) > 0
        and missing_bus == 0
        and len(snapshot_ids) == len(load_blocks)
    )
    branch_series_data_ready = (
        len(branches) > 0
        and branch_series_issues == 0
        and branch_thermal_issues == 0
        and branch_closure_nonbinary == 0
    )
    branch_units_confirmed_for_pypsa = False
    network_constraints_ready = (
        network_topology_ready
        and branch_series_data_ready
        and branch_units_confirmed_for_pypsa
    )

    if len(branches) > 0:
        warnings.append(
            {
                "type": "branch_impedance_units_pending",
                "detail": "Las ramas existen, pero antes de un OPF de red hay que confirmar la conversión de impedancias de MODOM a PyPSA.",
            }
        )
    if branch_closure_nonbinary:
        warnings.append(
            {
                "type": "branch_closure_semantics_pending",
                "detail": "Hay ramas con `closure_flag` no binario; la evidencia actual sugiere valores tipo tap/control en transformadores y enlaces a barras TAP, pero la traducción final a PyPSA sigue pendiente.",
                "count": branch_closure_nonbinary,
            }
        )

    return {
        "ok": True,
        "errors": [],
        "counts": {
            "generators": len(generators),
            "generator_availability_rows": len(availability),
            "loads_rows": len(loads),
            "unique_loads": len(load_ids),
            "buses": len(buses),
            "buses_with_v_nom_kv": buses_with_v_nom,
            "buses_without_v_nom_kv": buses_without_v_nom,
            "branches": len(branches),
            "snapshots": len(snapshot_ids),
            "load_blocks": len(load_blocks),
            "availability_generator_overlap": len(generator_ids & availability_ids),
            "branch_series_issue_count": branch_series_issues,
            "branch_thermal_issue_count": branch_thermal_issues,
            "branch_closure_nonbinary_count": branch_closure_nonbinary,
            "branch_closure_tap_ratio_like_count": branch_closure_tap_ratio_like,
            "branch_closure_tap_link_like_count": branch_closure_tap_link_like,
            "pypsa_v1_branch_included_count": pypsa_v1_branch_included,
            "pypsa_v1_branch_excluded_count": pypsa_v1_branch_excluded,
            "pypsa_v1_transformer_tap_candidate_count": pypsa_v1_transformer_tap_candidates,
            "generators_raw_missing_cost": raw_missing_cost,
            "generators_effective_missing_cost": effective_missing_cost,
            "generators_raw_pmax_lt_pmin": raw_pmax_lt_pmin,
            "generators_effective_pmax_lt_pmin": effective_pmax_lt_pmin,
            "generators_with_missing_bus": missing_bus,
        },
        "warnings": warnings,
        "network_topology_ready": network_topology_ready,
        "branch_series_data_ready": branch_series_data_ready,
        "branch_units_confirmed_for_pypsa": branch_units_confirmed_for_pypsa,
        "network_constraints_ready": network_constraints_ready,
    }


def run_copperplate_dispatch(
    data_dir: Path = DEFAULT_DATA_DIR,
    snapshot_id: str = "h_01",
    load_block_id: str = "h_01",
    outdir: Path | None = DEFAULT_RESULTS_DIR,
) -> dict[str, object]:
    validation = validate_dispatch_inputs(data_dir)
    if not validation["ok"]:
        raise FileNotFoundError("Faltan archivos de entrada para el despacho base.")

    inputs = resolve_inputs(data_dir)
    generators = read_csv(inputs.generators_path)
    availability_rows = read_csv(inputs.availability_path)
    load_rows = read_csv(inputs.loads_path)

    availability_by_generator: dict[str, dict[str, str]] = {}
    for row in availability_rows:
        if clean(row["snapshot_id"]) != snapshot_id:
            continue
        availability_by_generator[clean(row["generator_id"])] = row

    total_load_mw = sum(
        to_float(row.get("p_set_mw")) or 0.0
        for row in load_rows
        if clean(row["time_block_id"]) == load_block_id
    )

    merit_rows: list[dict[str, object]] = []
    for row in generators:
        generator_id = clean(row["generator_id"])
        availability = availability_by_generator.get(generator_id, {})
        enabled = clean(row.get("enabled_flag")) == "1"
        static_pmax = max(
            to_float(row.get("effective_pmax_mw"))
            or to_float(row.get("pmax_mw"))
            or 0.0,
            0.0,
        )
        static_pmin = max(
            to_float(row.get("effective_pmin_mw"))
            or to_float(row.get("pmin_mw"))
            or 0.0,
            0.0,
        )
        available_mw = to_float(availability.get("available_mw"))
        if available_mw is None:
            dispatch_cap_mw = static_pmax
            availability_source = "static_pmax_fallback"
        else:
            dispatch_cap_mw = max(available_mw, 0.0)
            availability_source = "generator_availability"
        dispatch_cap_mw = min(dispatch_cap_mw, max(static_pmax, dispatch_cap_mw))
        marginal_cost = to_float(row.get("effective_cvp"))
        if marginal_cost is None:
            marginal_cost = to_float(row.get("cvp"))
        used_cost_fallback = marginal_cost is None
        effective_cost = marginal_cost if marginal_cost is not None else MISSING_COST_FALLBACK

        merit_rows.append(
            {
                "generator_id": generator_id,
                "generator_name": clean(row.get("generator_name")),
                "bus_id": clean(row.get("bus_id")),
                "technology_group": clean(row.get("technology_group")),
                "enabled": enabled,
                "static_pmax_mw": static_pmax,
                "static_pmin_mw": static_pmin,
                "available_mw": available_mw if available_mw is not None else "",
                "dispatch_cap_mw": dispatch_cap_mw if enabled else 0.0,
                "marginal_cost": effective_cost,
                "used_cost_fallback": used_cost_fallback,
                "availability_source": availability_source,
                "dispatch_mw": 0.0,
            }
        )

    merit_rows.sort(
        key=lambda item: (
            0 if item["enabled"] else 1,
            float(item["marginal_cost"]),
            str(item["generator_id"]),
        )
    )

    remaining_load = total_load_mw
    dispatch_order = 0
    for row in merit_rows:
        dispatch_order += 1
        row["dispatch_order"] = dispatch_order
        cap = float(row["dispatch_cap_mw"]) if row["enabled"] else 0.0
        if remaining_load <= 0 or cap <= 0:
            row["dispatch_mw"] = 0.0
            row["headroom_mw"] = cap
            continue
        dispatched = min(cap, remaining_load)
        row["dispatch_mw"] = dispatched
        row["headroom_mw"] = cap - dispatched
        remaining_load -= dispatched

    dispatched_total_mw = sum(float(row["dispatch_mw"]) for row in merit_rows)
    total_available_mw = sum(float(row["dispatch_cap_mw"]) for row in merit_rows if row["enabled"])
    dispatched_units = [row for row in merit_rows if float(row["dispatch_mw"]) > 0]
    dispatch_cost = sum(float(row["dispatch_mw"]) * float(row["marginal_cost"]) for row in merit_rows)

    technology_dispatch = Counter()
    for row in dispatched_units:
        technology_dispatch[clean(row["technology_group"]) or "unknown"] += round(
            float(row["dispatch_mw"]), 6
        )

    summary = {
        "mode": "copperplate_single_snapshot",
        "snapshot_id": snapshot_id,
        "load_block_id": load_block_id,
        "total_load_mw": total_load_mw,
        "dispatched_total_mw": dispatched_total_mw,
        "unserved_load_mw": max(remaining_load, 0.0),
        "total_available_mw": total_available_mw,
        "spare_available_mw": total_available_mw - dispatched_total_mw,
        "dispatch_cost_variable": dispatch_cost,
        "weighted_average_cost": (dispatch_cost / dispatched_total_mw) if dispatched_total_mw else 0.0,
        "dispatched_unit_count": len(dispatched_units),
        "enabled_unit_count": sum(1 for row in merit_rows if row["enabled"]),
        "cost_fallback_unit_count": sum(1 for row in merit_rows if row["used_cost_fallback"]),
        "technology_dispatch_mw": dict(sorted(technology_dispatch.items())),
        "assumptions": [
            "Se usa demanda agregada del bloque horario seleccionado.",
            "Se usa disponibilidad del snapshot seleccionado.",
            "No se aplican todavía restricciones de red ni flujo de potencia.",
            "Los p_min de generadores se reportan, pero no se imponen en esta primera versión.",
        ],
        "validation": validation,
    }

    fieldnames = [
        "dispatch_order",
        "generator_id",
        "generator_name",
        "bus_id",
        "technology_group",
        "enabled",
        "static_pmax_mw",
        "static_pmin_mw",
        "available_mw",
        "dispatch_cap_mw",
        "dispatch_mw",
        "headroom_mw",
        "marginal_cost",
        "used_cost_fallback",
        "availability_source",
    ]

    if outdir is not None:
        outdir.mkdir(parents=True, exist_ok=True)
        write_csv(outdir / "dispatch_detail.csv", merit_rows, fieldnames)
        write_json(outdir / "dispatch_summary.json", summary)

    return {
        "dispatch_rows": merit_rows,
        "summary": summary,
    }

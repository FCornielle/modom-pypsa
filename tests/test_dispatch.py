from __future__ import annotations

import csv
from pathlib import Path

from modom_pypsa.dispatch import run_copperplate_dispatch, validate_dispatch_inputs


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_dispatch_fixture(base: Path) -> Path:
    data_dir = base / "processed"
    _write_csv(
        data_dir / "buses" / "buses.csv",
        [
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
        [
            {
                "bus_id_modom": "WBUS1",
                "bus_name": "BUS 1",
                "bus_id_legacy": "",
                "bus_name_legacy": "",
                "code_changed": "",
                "appears_in_mapping": "True",
                "appears_in_e_datred": "True",
                "e_datred_endpoint_count": "1",
                "source_sheet_primary": "MAPEO",
                "bus_origin": "mapping",
            }
        ],
    )
    _write_csv(
        data_dir / "branches" / "branches.csv",
        [
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
        [],
    )
    _write_csv(
        data_dir / "snapshots" / "snapshots.csv",
        [
            "snapshot_id",
            "snapshot_order",
            "snapshot_label_modom",
            "time_block_group",
            "source_sheet",
            "horizon_count",
            "time_resolution_minutes",
            "hour_block_start_label",
            "notes",
        ],
        [
            {
                "snapshot_id": "pd001",
                "snapshot_order": "1",
                "snapshot_label_modom": "1",
                "time_block_group": "dispatch",
                "source_sheet": "e_sets",
                "horizon_count": "1",
                "time_resolution_minutes": "60",
                "hour_block_start_label": "00:00",
                "notes": "",
            }
        ],
    )
    _write_csv(
        data_dir / "loads_time_series" / "loads_time_series.csv",
        [
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
        [
            {
                "load_id": "WBUS1",
                "load_id_source": "resolved_bus_id",
                "time_block_group": "load_blocks",
                "time_block_id": "h_01",
                "time_block_order": "1",
                "hour_block_start_label": "00:00",
                "snapshot_id": "",
                "p_set_mw": "80",
                "source_sheet": "PDemanda",
                "aggregation_row_count": "1",
                "load_id_raw_examples": "ZBUS1-D1",
                "bus_resolution_method_examples": "unique",
            }
        ],
    )
    _write_csv(
        data_dir / "generators" / "generators.csv",
        [
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
        [
            {
                "generator_id": "G1",
                "generator_name": "CHEAP",
                "generator_id_legacy": "",
                "code_changed": "",
                "bus_id": "WBUS1",
                "bus_resolution_method": "factor",
                "bus_id_in_buses": "True",
                "enabled_flag": "1",
                "pmax_mw": "100",
                "pmin_mw": "0",
                "cvp": "10",
                "technology_group": "1",
                "ssaa": "",
                "mrpf": "",
                "mrsf": "",
                "factora": "",
                "heat_parameter": "",
                "pgn_mw": "",
                "source_sheet_primary": "e_datgen",
                "source_row_number": "1",
                "source_name_sheet": "",
                "factor_node_bus_id": "WBUS1",
                "factor_node_smc_point_id": "",
                "centrales_terminal_bus_id": "",
            },
            {
                "generator_id": "G2",
                "generator_name": "EXPENSIVE",
                "generator_id_legacy": "",
                "code_changed": "",
                "bus_id": "WBUS1",
                "bus_resolution_method": "factor",
                "bus_id_in_buses": "True",
                "enabled_flag": "1",
                "pmax_mw": "100",
                "pmin_mw": "0",
                "cvp": "20",
                "technology_group": "1",
                "ssaa": "",
                "mrpf": "",
                "mrsf": "",
                "factora": "",
                "heat_parameter": "",
                "pgn_mw": "",
                "source_sheet_primary": "e_datgen",
                "source_row_number": "2",
                "source_name_sheet": "",
                "factor_node_bus_id": "WBUS1",
                "factor_node_smc_point_id": "",
                "centrales_terminal_bus_id": "",
            },
        ],
    )
    _write_csv(
        data_dir / "generator_availability" / "generator_availability.csv",
        [
            "generator_id",
            "generator_name",
            "snapshot_id",
            "snapshot_order",
            "snapshot_label_modom",
            "time_block_group",
            "available_mw",
            "static_pmax_mw",
            "available_pu",
            "source_sheet",
        ],
        [
            {
                "generator_id": "G1",
                "generator_name": "CHEAP",
                "snapshot_id": "pd001",
                "snapshot_order": "1",
                "snapshot_label_modom": "1",
                "time_block_group": "dispatch",
                "available_mw": "50",
                "static_pmax_mw": "100",
                "available_pu": "0.5",
                "source_sheet": "Reporte de Disponibilidad",
            },
            {
                "generator_id": "G2",
                "generator_name": "EXPENSIVE",
                "snapshot_id": "pd001",
                "snapshot_order": "1",
                "snapshot_label_modom": "1",
                "time_block_group": "dispatch",
                "available_mw": "60",
                "static_pmax_mw": "100",
                "available_pu": "0.6",
                "source_sheet": "Reporte de Disponibilidad",
            },
        ],
    )
    return data_dir


def test_validate_dispatch_inputs(tmp_path: Path) -> None:
    data_dir = _build_dispatch_fixture(tmp_path)
    payload = validate_dispatch_inputs(data_dir)
    assert payload["ok"] is True
    assert payload["counts"]["generators"] == 2
    assert payload["counts"]["snapshots"] == 1
    assert payload["counts"]["load_blocks"] == 1
    assert payload["counts"]["buses_with_v_nom_kv"] == 0
    assert payload["counts"]["buses_without_v_nom_kv"] == 1
    assert payload["counts"]["pypsa_v1_branch_included_count"] == 0
    assert payload["counts"]["pypsa_v1_branch_excluded_count"] == 0
    assert payload["network_topology_ready"] is False
    assert payload["branch_series_data_ready"] is False
    assert payload["branch_units_confirmed_for_pypsa"] is False
    assert payload["network_constraints_ready"] is False


def test_run_copperplate_dispatch(tmp_path: Path) -> None:
    data_dir = _build_dispatch_fixture(tmp_path)
    outdir = tmp_path / "results"
    payload = run_copperplate_dispatch(
        data_dir=data_dir,
        snapshot_id="pd001",
        load_block_id="h_01",
        outdir=outdir,
    )

    assert payload["summary"]["total_load_mw"] == 80.0
    assert payload["summary"]["dispatched_total_mw"] == 80.0
    assert payload["summary"]["unserved_load_mw"] == 0.0

    first = payload["dispatch_rows"][0]
    second = payload["dispatch_rows"][1]
    assert first["generator_id"] == "G1"
    assert first["dispatch_mw"] == 50.0
    assert second["generator_id"] == "G2"
    assert second["dispatch_mw"] == 30.0

    assert (outdir / "dispatch_detail.csv").exists()
    assert (outdir / "dispatch_summary.json").exists()

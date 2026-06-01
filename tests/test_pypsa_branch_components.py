from __future__ import annotations

import csv
import json
from pathlib import Path

from modom_pypsa.pypsa_branch_components import export_pypsa_branch_components


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_export_pypsa_branch_components(tmp_path: Path) -> None:
    branches_path = tmp_path / "branches.csv"
    buses_path = tmp_path / "buses.csv"
    outdir = tmp_path / "out"
    _write_csv(
        buses_path,
        ["bus_id_modom", "v_nom_kv"],
        [
            {"bus_id_modom": "B1", "v_nom_kv": "69"},
            {"bus_id_modom": "B2", "v_nom_kv": "69"},
            {"bus_id_modom": "B3", "v_nom_kv": "138"},
            {"bus_id_modom": "B4", "v_nom_kv": "69"},
            {"bus_id_modom": "B5", "v_nom_kv": "69"},
            {"bus_id_modom": "B6", "v_nom_kv": "69"},
        ],
    )
    _write_csv(
        branches_path,
        [
            "branch_id",
            "branch_type",
            "from_bus",
            "to_bus",
            "r_pu",
            "x_pu",
            "fmax_mw",
            "closure_flag",
            "closure_semantics_hint",
            "operational_status",
            "pypsa_v1_component",
            "pypsa_v1_include",
            "tap_ratio_hint",
            "pypsa_v1_mapping_reason",
            "source_row_number",
        ],
        [
            {
                "branch_id": "L_OK",
                "branch_type": "line",
                "from_bus": "B1",
                "to_bus": "B2",
                "r_pu": "0.01",
                "x_pu": "0.05",
                "fmax_mw": "100",
                "closure_flag": "1",
                "closure_semantics_hint": "binary_switch_state",
                "operational_status": "closed",
                "pypsa_v1_component": "line",
                "pypsa_v1_include": "True",
                "tap_ratio_hint": "",
                "pypsa_v1_mapping_reason": "standard_branch",
                "source_row_number": "10",
            },
            {
                "branch_id": "T_TAP",
                "branch_type": "transformer",
                "from_bus": "B3",
                "to_bus": "B4",
                "r_pu": "0.02",
                "x_pu": "0.06",
                "fmax_mw": "80",
                "closure_flag": "1.05",
                "closure_semantics_hint": "tap_ratio_like",
                "operational_status": "closed",
                "pypsa_v1_component": "transformer",
                "pypsa_v1_include": "True",
                "tap_ratio_hint": "1.05",
                "pypsa_v1_mapping_reason": "transformer_with_tap_ratio",
                "source_row_number": "11",
            },
            {
                "branch_id": "L_TAP_LINK",
                "branch_type": "line",
                "from_bus": "B5",
                "to_bus": "B6",
                "r_pu": "0.01",
                "x_pu": "0.02",
                "fmax_mw": "50",
                "closure_flag": "1.03",
                "closure_semantics_hint": "tap_link_like",
                "operational_status": "closure_fractional_or_unknown",
                "pypsa_v1_component": "auxiliary_tap_link",
                "pypsa_v1_include": "False",
                "tap_ratio_hint": "1.03",
                "pypsa_v1_mapping_reason": "excluded_auxiliary_tap_link",
                "source_row_number": "12",
            },
        ],
    )

    payload = export_pypsa_branch_components(branches_path, buses_path, outdir)
    assert payload["summary"]["counts"]["pypsa_v1_lines"] == 1
    assert payload["summary"]["counts"]["pypsa_v1_transformers"] == 1
    assert payload["summary"]["counts"]["pypsa_v1_excluded_branches"] == 1
    assert payload["summary"]["counts"]["pypsa_v1_transformers_with_tap_ratio_hint"] == 1
    assert payload["summary"]["counts"]["line_same_voltage_ok_count"] == 1
    assert payload["summary"]["counts"]["transformer_different_voltage_ok_count"] == 1

    lines = list(csv.DictReader((outdir / "lines_v1.csv").open()))
    transformers = list(csv.DictReader((outdir / "transformers_v1.csv").open()))
    excluded = list(csv.DictReader((outdir / "excluded_branches_v1.csv").open()))

    assert lines[0]["name"] == "L_OK"
    assert lines[0]["voltage_pair_status"] == "same_voltage_ok"
    assert transformers[0]["name"] == "T_TAP"
    assert transformers[0]["voltage_pair_status"] == "different_voltage_ok"
    assert transformers[0]["tap_ratio_hint"] == "1.05"
    assert transformers[0]["has_tap_ratio_hint"] == "True"
    assert excluded[0]["branch_id"] == "L_TAP_LINK"
    assert excluded[0]["exclusion_reason"] == "excluded_auxiliary_tap_link"
    assert excluded[0]["voltage_pair_status"] == "same_voltage_ok"

    summary = json.loads((outdir / "pypsa_branch_components_summary.json").read_text())
    assert summary["counts"]["input_branches"] == 3

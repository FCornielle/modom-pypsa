from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pypsa")
pytest.importorskip("pandas")

from modom_pypsa.pypsa_network import build_network, export_results, solve_network


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def _build_canonical(data_dir: Path) -> None:
    """Red mínima de 2 barras: A (generador) --línea-- B (demanda)."""
    _write(
        data_dir / "snapshots" / "snapshots.csv",
        "snapshot_id,snapshot_order",
        ["h_01,1", "h_02,2"],
    )
    _write(
        data_dir / "buses" / "buses.csv",
        "bus_id_modom,bus_name,v_nom_kv,v_nom_inference_method,v_nom_confidence,bus_role",
        ["A,BARRA A,138.0,name_explicit,high,network", "B,BARRA B,138.0,name_explicit,high,network"],
    )
    _write(
        data_dir / "pypsa_branch_components" / "lines_v1.csv",
        "name,bus0,bus1,r_pu_hint,x_pu_hint,s_nom_mva_hint",
        ["A__B__L1,A,B,0.001,0.01,500.0"],
    )
    _write(
        data_dir / "pypsa_branch_components" / "transformers_v1.csv",
        "name,bus0,bus1,r_pu_hint,x_pu_hint,s_nom_mva_hint,tap_ratio_hint",
        [],
    )
    _write(
        data_dir / "generators" / "generators.csv",
        "generator_id,generator_name,bus_id,enabled_flag,effective_pmax_mw,effective_pmin_mw,cvp,effective_cvp,technology_group",
        ["G1,GEN UNO,A,1,200.0,0.0,30.0,30.0,1"],
    )
    _write(
        data_dir / "generator_availability" / "generator_availability.csv",
        "generator_id,snapshot_id,available_mw",
        ["G1,h_01,200.0", "G1,h_02,200.0"],
    )
    _write(
        data_dir / "loads_time_series" / "loads_time_series.csv",
        "load_id,snapshot_id,p_set_mw",
        ["B,h_01,100.0", "B,h_02,80.0"],
    )


def test_build_network_assembles(tmp_path: Path) -> None:
    _build_canonical(tmp_path)
    n = build_network(data_dir=tmp_path)
    assert len(n.buses) == 2
    assert len(n.lines) == 1
    assert "G1" in n.generators.index
    # holgura por barra con demanda + generador real
    assert (n.generators.carrier == "unserved").sum() == 1
    assert len(n.snapshots) == 2


def test_modom_commitment_forces_on_off_and_pmin(tmp_path: Path) -> None:
    """Con commitment del MODOM: apaga lo no-commiteado y exige Pmin en lo encendido."""
    _build_canonical(tmp_path)
    # G1 con Pmin = 50 MW (p_nom = 200 -> pmin_pu = 0.25)
    _write(
        tmp_path / "generators" / "generators.csv",
        "generator_id,generator_name,bus_id,enabled_flag,effective_pmax_mw,effective_pmin_mw,cvp,effective_cvp,technology_group",
        ["G1,GEN UNO,A,1,200.0,50.0,30.0,30.0,1"],
    )
    # MODOM: G1 encendida en h_01 (100 MW), apagada en h_02 (0)
    _write(
        tmp_path / "modom_results" / "modom_generator_dispatch.csv",
        ",G1",
        ["h_01,100.0", "h_02,0.0"],
    )
    n = build_network(data_dir=tmp_path, use_modom_commitment=True)
    assert n.meta["counts"]["committed_from_modom"] == 1
    assert n.generators_t.p_max_pu.at["h_02", "G1"] == 0.0   # apagada
    assert n.generators_t.p_max_pu.at["h_01", "G1"] == pytest.approx(1.0)
    assert n.generators_t.p_min_pu.at["h_01", "G1"] == pytest.approx(0.25)  # >= Pmin
    assert n.generators_t.p_min_pu.at["h_02", "G1"] == 0.0
    assert (n.generators.carrier == "dump").sum() >= 1  # holgura de sobre-generación


def test_solve_serves_load(tmp_path: Path) -> None:
    _build_canonical(tmp_path)
    n = build_network(data_dir=tmp_path)
    solve_network(n, solver_name="highs")
    summary = export_results(n, outdir=tmp_path / "out")
    assert summary["total_load_mwh"] == pytest.approx(180.0)
    assert summary["served_mwh"] == pytest.approx(180.0)
    assert summary["unserved_mwh"] == pytest.approx(0.0, abs=1e-6)
    assert (tmp_path / "out" / "pypsa_basecase_summary.json").exists()

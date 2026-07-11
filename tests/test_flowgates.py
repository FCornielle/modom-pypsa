from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = REPO_ROOT / "data" / "raw" / "MODOM_DIARIO_dd-mm-yyyy_V449.xlsm"
BRANCH_DIR = REPO_ROOT / "data" / "processed" / "pypsa_branch_components"


# --------------------------------------------------------------- parser (e_fgate)
def test_parse_e_fgate_from_workbook(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    if not WORKBOOK.exists() or not (BRANCH_DIR / "lines_v1.csv").exists():
        pytest.skip("falta el workbook MODOM o las ramas canónicas")
    from modom_pypsa.flowgates import export_flowgates

    payload = export_flowgates(WORKBOOK, tmp_path, BRANCH_DIR)
    assert payload["flowgates"] == ["fg1", "fg2"]      # fg3 se descarta (vacío)
    assert payload["counts"] == {"fg1": 7, "fg2": 3}
    assert payload["limits_mw"]["fg1"] == [200.0]
    assert payload["limits_mw"]["fg2"] == [670.0]
    assert payload["missing_branches"] == []           # todas las ramas existen

    import pandas as pd
    limits = pd.read_csv(tmp_path / "flowgate_limits.csv")
    assert set(limits["snapshot_id"]) == {f"h_{p:02d}" for p in range(1, 25)}


# --------------------------------------------------------- restricción dura en el LP
def _write(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def test_flowgate_caps_branch_flow(tmp_path: Path) -> None:
    """Un flowgate con límite por debajo de la demanda debe acotar el flujo de la rama
    y forzar holgura (energía no suministrada) en la barra de carga."""
    pytest.importorskip("pypsa")
    from modom_pypsa.pypsa_network import (build_network, flowgate_utilization,
                                           solve_network)

    _write(tmp_path / "snapshots" / "snapshots.csv",
           "snapshot_id,snapshot_order", ["h_01,1"])
    _write(tmp_path / "buses" / "buses.csv",
           "bus_id_modom,bus_name,v_nom_kv,bus_role",
           ["A,BARRA A,138.0,network", "B,BARRA B,138.0,network"])
    _write(tmp_path / "pypsa_branch_components" / "lines_v1.csv",
           "name,bus0,bus1,r_pu_hint,x_pu_hint,s_nom_mva_hint",
           ["A__B__L1,A,B,0.001,0.01,500.0"])
    _write(tmp_path / "pypsa_branch_components" / "transformers_v1.csv",
           "name,bus0,bus1,r_pu_hint,x_pu_hint,s_nom_mva_hint,tap_ratio_hint", [])
    _write(tmp_path / "generators" / "generators.csv",
           "generator_id,generator_name,bus_id,enabled_flag,effective_pmax_mw,effective_pmin_mw,cvp,effective_cvp,technology_group",
           ["G1,GEN UNO,A,1,200.0,0.0,30.0,30.0,1"])
    _write(tmp_path / "generator_availability" / "generator_availability.csv",
           "generator_id,snapshot_id,available_mw", ["G1,h_01,200.0"])
    _write(tmp_path / "loads_time_series" / "loads_time_series.csv",
           "load_id,snapshot_id,p_set_mw", ["B,h_01,100.0"])
    # Flowgate fg1 = {A__B__L1 con coef 1}, límite 50 MW (< demanda 100)
    _write(tmp_path / "flowgates" / "flowgate_members.csv",
           "flowgate_id,branch_name,ni,nf,cc,coefficient,orient,branch_exists,branch_kind",
           ["fg1,A__B__L1,A,B,L1,1.0,1,1,line"])
    _write(tmp_path / "flowgates" / "flowgate_limits.csv",
           "flowgate_id,snapshot_id,fmax_mw", ["fg1,h_01,50.0"])

    n = build_network(data_dir=tmp_path)
    assert n.meta["counts"]["flowgates"] == 1
    solve_network(n, solver_name="highs")

    # El flujo de la única rama no puede exceder el límite del flowgate.
    assert abs(float(n.lines_t.p0.at["h_01", "A__B__L1"])) <= 50.0 + 1e-3
    util = flowgate_utilization(n)
    assert float(util["util_pct"].iloc[0]) <= 100.0 + 1e-3
    # Como el flowgate limita el aporte por la rama, la barra B usa holgura (no suministrada).
    unserved = n.generators.index[n.generators.carrier == "unserved"]
    assert float(n.generators_t.p[unserved].sum().sum()) > 1.0

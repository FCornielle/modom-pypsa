from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("pandas")

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = REPO_ROOT / "data" / "raw" / "MODOM_DIARIO_dd-mm-yyyy_V449.xlsm"
PROCESSED = REPO_ROOT / "data" / "processed"


# ------------------------------------------------------ ingesta de parámetros MILP
def test_parse_datgen_and_opcn(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    if not WORKBOOK.exists():
        pytest.skip("falta el workbook MODOM")
    from modom_pypsa import modom_params as mp

    datgen = mp.parse_datgen(WORKBOOK)
    assert len(datgen) > 100
    for col in ("PMX", "PMN", "TARR", "TPAR", "MRPF", "MRSF", "SSAA", "NAMX"):
        assert col in datgen.columns

    opts = mp.parse_opcn(WORKBOOK)
    assert opts["CENS"] == 2_000_000.0          # costo de ENS
    assert opts["PORS"] == pytest.approx(0.03)  # fracción de reserva RRPF/RRSF
    assert opts["SBASE"] == 100.0


def test_parse_hidro(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    if not WORKBOOK.exists():
        pytest.skip("falta el workbook MODOM")
    from modom_pypsa import modom_params as mp

    hydro = mp.parse_hidro(WORKBOOK)
    assert len(hydro["reservoirs"]) == 17
    assert len(hydro["gen_reservoir"]) == 17            # 17 unidades hidro mapeadas
    assert {"generator_id", "reservoir_id"} <= set(hydro["gen_reservoir"].columns)


# ------------------------------------------------------ construcción del MILP
def test_build_milp_network_committable() -> None:
    pytest.importorskip("pypsa")
    if not (PROCESSED / "commitment" / "gen_params.csv").exists():
        pytest.skip("faltan los parámetros de commitment (build_modom_params)")
    from modom_pypsa import pypsa_milp as milp

    n = milp.build_milp_network(with_reserves=True)
    assert n.meta["model"] == "milp_modom_full"
    # hay unidades térmicas committable y márgenes de reserva declarados
    assert int(n.generators.committable.sum()) > 30
    assert n.meta["counts"]["reserve_rpf_units"] > 0
    # p_min_pu por snapshot capado a disponibilidad (0 cuando no hay disponibilidad)
    assert (n.generators_t.p_min_pu.fillna(0.0).values >= -1e-9).all()


# ------------------------------------------------------ Scenario Studio: overrides
def test_overrides_applied() -> None:
    pytest.importorskip("pypsa")
    if not (PROCESSED / "commitment" / "gen_params.csv").exists():
        pytest.skip("faltan los parámetros de commitment")
    from modom_pypsa import pypsa_milp as milp

    n0 = milp.build_milp_network()
    gid = next(g for g in n0.generators.index if str(g).startswith("G")
               and float(n0.generators.at[g, "p_nom"]) > 0)
    base_cvp = float(n0.generators.at[gid, "marginal_cost"])
    base_dem = float(n0.loads_t.p_set.sum().sum())
    off = next(g for g in n0.generators.index[n0.generators.committable] if g != gid)

    ov = {"generators": {gid: {"cvp": base_cvp * 2 + 1, "availability_pct": 50},
                         off: {"enabled": False}},
          "global": {"demand_pct": 110, "flowgate_derate_pct": 80}}
    n1 = milp.build_milp_network(overrides=ov)
    assert float(n1.generators.at[gid, "marginal_cost"]) == pytest.approx(base_cvp * 2 + 1)
    assert float(n1.generators.at[off, "p_nom"]) == 0.0
    assert float(n1.loads_t.p_set.sum().sum()) == pytest.approx(base_dem * 1.1, rel=1e-6)
    ap = n1.meta["overrides_applied"]
    assert ap["generators"] == 2 and ap["global"]["demand_pct"] == 110.0
    if n1.meta.get("flowgates"):
        lim0 = next(iter(n0.meta["flowgates"][0]["limit"].values()))
        lim1 = next(iter(n1.meta["flowgates"][0]["limit"].values()))
        assert lim1 == pytest.approx(lim0 * 0.8)


# ------------------------------------------------------ solve (lento; opt-in)
@pytest.mark.skipif(not os.environ.get("RUN_MILP"), reason="solve lento; set RUN_MILP=1")
def test_solve_milp_optimal() -> None:
    pytest.importorskip("pypsa")
    from modom_pypsa import pypsa_milp as milp

    n = milp.build_milp_network(with_reserves=True)
    milp.solve_milp(n, mip_rel_gap=0.05, time_limit=300)
    assert n.objective is not None and n.objective > 0
    s = milp.summarize(n)
    assert s["commitment"]["total_startups"] >= 0

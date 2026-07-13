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

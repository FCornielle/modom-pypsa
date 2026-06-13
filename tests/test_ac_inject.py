"""Test de la capa AC con despacho MODOM inyectado sobre el export DIgSILENT.

Se salta si no está el export (datos externos, no versionados completos).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXPORT = ROOT / "data/external/salida_PDD_30_09_2025_20260613_022117"

pytest.importorskip("pandapower")
pytestmark = pytest.mark.skipif(
    not EXPORT.exists(), reason="export DIgSILENT no disponible")


def test_inject_and_aggregate_converges():
    from modom_pypsa.ac_inject import run_ac_modom

    net, ctx, bus_res, br_res, s = run_ac_modom(EXPORT, hour="h_19", root=str(ROOT))

    assert s["converged"], "el flujo AC debe converger con el despacho MODOM"
    # cruce por for_name razonable (no perfecto: divergencias de convención de W-codes)
    assert s["gen_coverage"] > 0.6
    assert s["load_coverage"] > 0.6
    # resultados agregados a las 717 barras MODOM, con una porción cruzada
    assert len(bus_res) == s["modom_buses_total"] == 717
    assert s["modom_buses_with_v"] > 400
    # tensiones físicas y ramas con W-codes en ambos extremos
    assert 0.7 < s["v_min"] < 1.05 and 0.95 < s["v_max"] < 1.25
    assert {"from_w", "to_w", "loading_percent"} <= set(br_res.columns)
    assert (bus_res.loc[bus_res.matched, "vm_pu"].notna()).any()

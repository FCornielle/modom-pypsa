"""Tests del lazo iterativo DC↔AC→MODOM y de los factores de pérdidas.

Se saltan si no está el export DIgSILENT (datos externos).
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
pytest.importorskip("pypsa")
pytestmark = pytest.mark.skipif(
    not EXPORT.exists(), reason="export DIgSILENT no disponible")


def test_loss_factors_basic():
    import pandas as pd
    from modom_pypsa import loss_factors as lf
    from modom_pypsa.ac_inject import run_ac_modom

    net, ctx, _, _, s = run_ac_modom(EXPORT, hour="h_19", root=str(ROOT))
    frac = lf.system_loss_fraction(net)
    assert 0.0 < frac < 0.2  # pérdidas razonables (<20% de la demanda)

    base_h = pd.Series(1.0, index=list(ctx["forname_to_bus"].keys()))
    seed = pd.Series(1.05, index=base_h.index)
    new = lf.update_loss_factors(seed, net, ctx, base_h)
    assert (new >= 1.0).all() and new.notna().all()
    assert lf.factor_delta(seed, new) >= 0.0


def test_iterative_converges_and_records():
    from modom_pypsa.iterative import run_iterative

    m = run_iterative(hour="h_19", max_iter=4, export_dir=EXPORT,
                      root=str(ROOT), write=False)
    its = m["iterations"]
    assert len(its) >= 2
    # Δfactor decreciente hacia el final (el lazo se estabiliza)
    assert its[-1]["loss_factor_delta"] <= its[0]["loss_factor_delta"] + 1e-9
    # registra violaciones y pérdidas para auditar
    assert "n_v_below_090" in its[-1] and "losses_mw" in its[-1]
    assert m["summary"]["converged"]  # la AC final converge
    assert m["type"] == "iterative"

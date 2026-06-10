"""Tests de las metricas de fidelidad (validation.py), con datos sinteticos."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from modom_pypsa import validation as val


def _frame(values, cols, idx=("h_01", "h_02", "h_03")):
    return pd.DataFrame(values, index=list(idx), columns=list(cols))


def test_metrics_identical_series_are_perfect():
    s = pd.Series([10.0, 20.0, 30.0])
    m = val._metrics(s, s.copy())
    assert m["mae"] == 0 and m["rmse"] == 0 and m["r2"] == 1.0
    assert m["rel_err_pct"] == 0


def test_metrics_constant_offset():
    ours = pd.Series([12.0, 22.0, 32.0])
    modom = pd.Series([10.0, 20.0, 30.0])
    m = val._metrics(ours, modom)
    assert m["mae"] == 2.0 and m["bias"] == 2.0


def test_branch_norm_key_ignores_order_and_circuit_label():
    k1 = val._branch_norm_key("WAANDE", "WENADE", "L1")
    k2 = val._branch_norm_key("WENADE", "WAANDE", "c1")  # orden invertido, etiqueta distinta
    assert k1 == k2


def test_compare_generator_dispatch_drops_unserved_and_matches():
    ours = _frame([[10, 5, 99], [10, 5, 99], [10, 5, 99]],
                  ["G1", "G2", "unserved_WX"])
    modom = _frame([[10, 5], [10, 5], [10, 5]], ["G1", "G2"])
    out = val.compare_generator_dispatch(ours, modom)
    assert out["common_generators"] == 2
    assert out["per_unit_hourly"]["r2"] == 1.0  # identicos en G1,G2


def test_compare_branch_flows_matches_by_normalized_key():
    ours = _frame([[100.0], [100.0], [100.0]], ["WA__WB__L1"])
    modom = _frame([[-100.0], [-100.0], [-100.0]], ["WB|WA|c1"])  # signo y etiqueta distintos
    out = val.compare_branch_flows(ours, modom)
    assert out["matched_branches"] == 1
    assert out["abs_flow"]["mae"] == 0  # |flujo| coincide


def test_fidelity_score_in_range():
    report = {
        "generator_dispatch": {"per_unit_hourly": {"r2": 0.8},
                               "system_total_hourly": {"rel_err_pct": 10.0}},
        "branch_flows": {"abs_flow": {"rel_err_pct": 20.0}},
    }
    score = val._fidelity_score(report)
    assert 0 <= score <= 100

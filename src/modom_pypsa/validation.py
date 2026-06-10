"""Compara el despacho de PyPSA contra la verdad de referencia del MODOM.

Mide fidelidad de forma objetiva: que tan cerca queda nuestro despacho/flujos/ENS
de lo que el OC realmente publico (ver `modom_results`). Produce un reporte con
metricas por generador, por rama y de ENS, mas un score agregado que seguimos a
medida que subimos la fidelidad (Fases 1, 2, 3...).

No asume bases ni unidades nuevas: solo alinea por `generator_id`, por par de
barras+circuito (normalizado) y por barra, en el eje de 24 snapshots.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = REPO_ROOT / "results" / "pypsa_basecase"
DEFAULT_MODOM_DIR = REPO_ROOT / "data" / "processed" / "modom_results"


def _circuit_digits(text: str) -> str:
    return "".join(ch for ch in str(text) if ch.isdigit()) or "1"


def _branch_norm_key(bus0: str, bus1: str, circuit: str) -> tuple[frozenset[str], str]:
    return (frozenset({bus0.strip(), bus1.strip()}), _circuit_digits(circuit))


def _metrics(ours: pd.Series, modom: pd.Series) -> dict[str, float]:
    """MAE, RMSE, sesgo, R^2 y error relativo entre dos series alineadas."""
    df = pd.concat([ours.rename("o"), modom.rename("m")], axis=1).dropna()
    if df.empty:
        return {"n": 0}
    err = df["o"] - df["m"]
    ss_res = float((err ** 2).sum())
    ss_tot = float(((df["m"] - df["m"].mean()) ** 2).sum())
    denom = float(df["m"].abs().sum())
    return {
        "n": int(len(df)),
        "mae": round(float(err.abs().mean()), 3),
        "rmse": round(float((err ** 2).mean() ** 0.5), 3),
        "bias": round(float(err.mean()), 3),
        "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
        "rel_err_pct": round(100 * float(err.abs().sum()) / denom, 2) if denom else None,
    }


def compare_generator_dispatch(
    gen_ours: pd.DataFrame, gen_modom: pd.DataFrame
) -> dict[str, object]:
    """Compara despacho por generador. `gen_ours` puede traer columnas `unserved_*`."""
    real = [c for c in gen_ours.columns if not str(c).startswith("unserved")]
    ours = gen_ours[real]
    common = [g for g in gen_modom.columns if g in set(ours.columns)]
    n = min(len(ours.index), len(gen_modom.index))
    o = ours.iloc[:n][common].reset_index(drop=True)
    m = gen_modom.iloc[:n][common].reset_index(drop=True)

    # serie aplanada (todas las horas x generadores comunes)
    flat = _metrics(o.stack(), m.stack())
    # total del sistema por hora
    sys_m = _metrics(o.sum(axis=1), m.sum(axis=1))
    # energia del dia por generador -> divergencias
    e_ours, e_modom = o.sum() * 1.0, m.sum() * 1.0
    diff = (e_ours - e_modom).abs().sort_values(ascending=False)
    top = [{"gen": g, "ours_mwh": round(float(e_ours[g]), 1),
            "modom_mwh": round(float(e_modom[g]), 1),
            "abs_diff_mwh": round(float(diff[g]), 1)} for g in diff.index[:12]]
    return {
        "common_generators": len(common),
        "modom_only": sorted(set(gen_modom.columns) - set(ours.columns))[:10],
        "per_unit_hourly": flat,
        "system_total_hourly": sys_m,
        "top_divergent_units": top,
    }


def compare_branch_flows(
    flow_ours: pd.DataFrame, flow_modom: pd.DataFrame
) -> dict[str, object]:
    """Compara flujos de rama por |flujo| (las convenciones de signo difieren)."""
    # mapa de clave normalizada -> columna nuestra
    ours_map: dict[tuple, str] = {}
    for col in flow_ours.columns:
        parts = str(col).split("__")
        if len(parts) >= 2:
            circ = parts[2] if len(parts) > 2 else ""
            ours_map[_branch_norm_key(parts[0], parts[1], circ)] = col
    n = min(len(flow_ours.index), len(flow_modom.index))
    pairs_o, pairs_m, matched = [], [], 0
    for col in flow_modom.columns:
        b0, b1, cto = (str(col).split("|") + ["", "", ""])[:3]
        k = _branch_norm_key(b0, b1, cto)
        if k in ours_map:
            matched += 1
            pairs_o.append(flow_ours.iloc[:n][ours_map[k]].abs().reset_index(drop=True))
            pairs_m.append(flow_modom.iloc[:n][col].abs().reset_index(drop=True))
    if not pairs_o:
        return {"matched_branches": 0}
    o = pd.concat(pairs_o, ignore_index=True)
    m = pd.concat(pairs_m, ignore_index=True)
    return {
        "matched_branches": matched,
        "modom_branches": int(flow_modom.shape[1]),
        "ours_branches": int(flow_ours.shape[1]),
        "abs_flow": _metrics(o, m),
    }


def compare_ens(unserved_ours: pd.Series, ens_modom: pd.DataFrame) -> dict[str, object]:
    n = min(len(unserved_ours.index), len(ens_modom.index))
    o_tot = float(unserved_ours.iloc[:n].sum())
    m_tot = float(ens_modom.iloc[:n].to_numpy(dtype=float).sum())
    return {
        "ours_ens_mwh": round(o_tot, 1),
        "modom_ens_mwh": round(m_tot, 1),
        "abs_diff_mwh": round(abs(o_tot - m_tot), 1),
    }


def _fidelity_score(report: dict) -> float:
    """Score 0-100 agregado (mayor = mas fiel). Combina R^2 de despacho por unidad,
    error relativo del total del sistema y error relativo de flujos."""
    gd = report.get("generator_dispatch", {})
    bf = report.get("branch_flows", {})
    r2 = (gd.get("per_unit_hourly", {}) or {}).get("r2")
    sys_rel = (gd.get("system_total_hourly", {}) or {}).get("rel_err_pct")
    flow_rel = (bf.get("abs_flow", {}) or {}).get("rel_err_pct")
    parts = []
    if r2 is not None:
        parts.append(max(0.0, r2) * 100)
    if sys_rel is not None:
        parts.append(max(0.0, 100 - sys_rel))
    if flow_rel is not None:
        parts.append(max(0.0, 100 - flow_rel))
    return round(sum(parts) / len(parts), 1) if parts else 0.0


def build_report(
    results_dir: Path = DEFAULT_RESULTS_DIR, modom_dir: Path = DEFAULT_MODOM_DIR
) -> dict[str, object]:
    gen_ours = pd.read_csv(results_dir / "generation_by_snapshot.csv", index_col=0)
    flow_ours = pd.read_csv(results_dir / "line_flows_by_snapshot.csv", index_col=0)
    gen_modom = pd.read_csv(modom_dir / "modom_generator_dispatch.csv", index_col=0)
    flow_modom = pd.read_csv(modom_dir / "modom_branch_flows.csv", index_col=0)
    ens_modom = pd.read_csv(modom_dir / "modom_bus_ens.csv", index_col=0)

    unserved_cols = [c for c in gen_ours.columns if str(c).startswith("unserved")]
    unserved_ours = gen_ours[unserved_cols].sum(axis=1)

    report: dict[str, object] = {
        "generator_dispatch": compare_generator_dispatch(gen_ours, gen_modom),
        "branch_flows": compare_branch_flows(flow_ours, flow_modom),
        "ens": compare_ens(unserved_ours, ens_modom),
    }
    report["fidelity_score"] = _fidelity_score(report)
    return report

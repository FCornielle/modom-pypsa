"""Lazo iterativo DC↔AC→MODOM (Fase 3.4).

Reproduce la metodología GAMS↔PowerFactory del OC: el despacho DC (PyPSA) se verifica
con el flujo AC (pandapower sobre la red real DIgSILENT); de la AC se re-estiman los
factores de nodo (pérdidas) y se re-despacha, hasta que los factores se estabilizan.
El resultado es el "despacho con valores MODOM tras considerar la capa AC".

Cada iteración queda registrada (Δfactor, violaciones, pérdidas) para auditarla en la
plataforma. La corrida se persiste en `results/runs/<run_id>/` (modelo de artefactos que
lee la webapp).

Reusa: `pypsa_network.build_network/solve_network`, `ac_inject.run_ac_modom`
(con `gen_disp` = nuestro despacho PyPSA), `loss_factors.update_loss_factors`.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import loss_factors as lf

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT = REPO_ROOT / "data/external/salida_PDD_30_09_2025_20260613_022117"
RUNS_DIR = REPO_ROOT / "results" / "runs"
LOADS_CSV = REPO_ROOT / "data/processed/loads_time_series/loads_time_series.csv"
NODAL_FACTORS_CSV = REPO_ROOT / "data/processed/modom_results/nodal_factors.csv"


def _base_load_by_hour(root: Path) -> pd.DataFrame:
    """Demanda base (sin factor) pivote snapshot × W desde loads_time_series."""
    loads = pd.read_csv(root / "data/processed/loads_time_series/loads_time_series.csv")
    return loads.pivot_table(index="snapshot_id", columns="load_id",
                             values="p_set_mw", aggfunc="sum").fillna(0.0)


def _seed_factors(root: Path) -> pd.Series:
    """Factores de nodo del MODOM (factor_retiro) como semilla espacial del lazo."""
    p = root / "data/processed/modom_results/nodal_factors.csv"
    if not p.exists():
        return pd.Series(dtype=float)
    nf = pd.read_csv(p).set_index("bus_id_modom")
    if "factor_retiro" not in nf.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(nf["factor_retiro"], errors="coerce").dropna()


def _apply_factors(n, base_load: pd.DataFrame, factors: pd.Series) -> None:
    """Fija n.loads_t.p_set = demanda base × factor por barra (W) para todas las horas."""
    p_set = n.loads_t.p_set.copy()
    bus_of = dict(zip(n.loads.index, n.loads.bus))  # load_name -> W
    for name in p_set.columns:
        w = bus_of.get(name)
        if w is None or w not in base_load.columns:
            continue
        f = float(factors.get(w, 1.0))
        p_set[name] = base_load[w].reindex(p_set.index).fillna(0.0) * f
    n.loads_t.p_set = p_set


def _count_overloads(net, thr: float = 100.0) -> int:
    n = 0
    if len(net.res_line):
        n += int((net.res_line.loading_percent > thr).sum())
    if len(net.res_trafo):
        n += int((net.res_trafo.loading_percent > thr).sum())
    return n


def run_iterative(hour: str = "h_19", max_iter: int = 8, tol: float = 1e-3,
                  damping: float = 0.5, export_dir: Path | str = DEFAULT_EXPORT,
                  root: Path | str = REPO_ROOT, project_id: str | None = None,
                  write: bool = True) -> dict:
    """Corre el lazo DC↔AC para una hora. Devuelve el manifest de la corrida."""
    from .pypsa_network import build_network, solve_network
    from .ac_inject import run_ac_modom

    root = Path(root)
    export_dir = Path(export_dir)
    started = datetime.now(timezone.utc)
    t0 = time.time()

    n = build_network(use_modom_commitment=True)        # topología + commitment MODOM
    base_load = _base_load_by_hour(root)                 # demanda sin factor
    base_h = base_load.loc[hour] if hour in base_load.index else pd.Series(dtype=float)

    factors = _seed_factors(root)                        # semilla = factores MODOM
    if factors.empty:
        factors = pd.Series(1.0, index=base_load.columns)

    iterations: list[dict] = []
    prev = None
    last = {"net": None, "ctx": None, "bus_res": pd.DataFrame(),
            "br_res": pd.DataFrame(), "summary": {}}
    for it in range(1, max_iter + 1):
        _apply_factors(n, base_load, factors)
        solve_network(n)
        dispatch = n.generators_t.p                      # snapshot × generator_id (G3)

        net, ctx, bus_res, br_res, ac = run_ac_modom(
            export_dir, hour=hour, root=str(root), gen_disp=dispatch)
        last.update(net=net, ctx=ctx, bus_res=bus_res, br_res=br_res, summary=ac)

        new_factors = lf.update_loss_factors(factors, net, ctx, base_h, damping=damping)
        delta = lf.factor_delta(prev if prev is not None else factors, new_factors)

        iterations.append({
            "iter": it,
            "loss_factor_delta": round(delta, 6),
            "losses_mw": round(ac.get("losses_mw", float("nan")), 2),
            "slack_mw": round(ac.get("slack_mw", float("nan")), 2),
            "demand_mw": round(ac.get("demand_mw", float("nan")), 2),
            "n_v_below_090": ac.get("n_v_below_090", 0),
            "n_v_above_110": ac.get("n_v_above_110", 0),
            "n_overload": _count_overloads(net),
            "ac_converged": ac.get("converged", False),
            "mean_factor": round(float(new_factors.mean()), 5),
        })
        prev, factors = factors, new_factors
        if delta < tol:
            break

    duration = round(time.time() - t0, 1)
    converged = bool(iterations and iterations[-1]["loss_factor_delta"] < tol)
    run_id = f"iter_{hour}_{started.strftime('%Y%m%d_%H%M%S')}"
    last_it = iterations[-1] if iterations else {}
    manifest = {
        "run_id": run_id, "project_id": project_id, "type": "iterative",
        "label": f"Iterativo DC↔AC · {hour}",
        "status": "completed" if (converged and last["summary"].get("converged")) else "warning",
        "started": started.isoformat(), "duration_s": duration,
        "params": {"hour": hour, "max_iter": max_iter, "tol": tol, "damping": damping,
                   "export_dir": export_dir.name},
        "summary": {
            "hour": hour, "n_iterations": len(iterations),
            "loss_factor_converged": converged,
            **{k: last["summary"].get(k) for k in (
                "converged", "demand_mw", "gen_mw", "slack_mw", "losses_mw",
                "v_min", "v_max", "n_v_below_090", "n_v_above_110",
                "modom_buses_with_v", "modom_buses_total")},
            "final_overloads": last_it.get("n_overload", 0),
            "final_delta": last_it.get("loss_factor_delta"),
        },
        "coverage": {k: last["summary"].get(k) for k in (
            "gen_coverage", "load_coverage", "gen_matched_mw", "load_matched_mw")},
    }

    if write:
        out = Path(root) / "results" / "runs" / run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "iterations.json").write_text(
            json.dumps(iterations, indent=2, ensure_ascii=False), encoding="utf-8")
        last["bus_res"].to_csv(out / "ac_bus_voltages.csv", index=False)
        last["br_res"].to_csv(out / "ac_branch_loading.csv", index=False)
        # despacho final de la hora (W de la barra de conexión, MW)
        n.generators_t.p.loc[[hour]].T.rename(columns={hour: "p_mw"}).to_csv(
            out / "dispatch.csv")
        factors.rename("factor_retiro").to_csv(out / "loss_factors_final.csv")
        manifest["_run_dir"] = str(out)
    manifest["iterations"] = iterations
    return manifest

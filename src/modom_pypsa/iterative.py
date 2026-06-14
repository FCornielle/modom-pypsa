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


def _apply_factors_hour(n, base_load: pd.DataFrame, factors: pd.Series, hour: str) -> None:
    """Fija n.loads_t.p_set de UNA hora = demanda base × factor por barra (W)."""
    bus_of = dict(zip(n.loads.index, n.loads.bus))
    for name in n.loads_t.p_set.columns:
        w = bus_of.get(name)
        if w is None or w not in base_load.columns:
            continue
        n.loads_t.p_set.at[hour, name] = float(base_load.at[hour, w]) * float(factors.get(w, 1.0))


def _count_overloads(net, thr: float = 100.0) -> int:
    n = 0
    if len(net.res_line):
        n += int((net.res_line.loading_percent > thr).sum())
    if len(net.res_trafo):
        n += int((net.res_trafo.loading_percent > thr).sum())
    return n


ALL_HOURS = [f"h_{i:02d}" for i in range(1, 25)]


def run_iterative(hour: str | None = None, hours: list[str] | None = None,
                  max_iter: int = 6, tol: float = 1e-3, damping: float = 0.5,
                  export_dir: Path | str = DEFAULT_EXPORT,
                  root: Path | str = REPO_ROOT, project_id: str | None = None,
                  write: bool = True) -> dict:
    """Corre el lazo DC↔AC→MODOM para 24 h (o un subconjunto). Una corrida = N horas.

    Lazo externo de factores (matriz hora×barra): aplica factores a la demanda, resuelve
    PyPSA una vez (24 h), verifica AC por hora, re-estima factores y repite hasta que
    el máximo Δfactor entre todas las horas < tol. Guarda resultados AC por hora.
    """
    from .pypsa_network import build_network, solve_network
    from .ac_inject import run_ac_modom

    root = Path(root)
    export_dir = Path(export_dir)
    hours = hours or ([hour] if hour else ALL_HOURS)
    started = datetime.now(timezone.utc)
    t0 = time.time()

    n = build_network(use_modom_commitment=True)
    base_load = _base_load_by_hour(root)
    seed = _seed_factors(root)
    if seed.empty:
        seed = pd.Series(1.0, index=base_load.columns)
    # matriz de factores hora×barra (misma semilla por hora)
    factors = {h: seed.copy() for h in hours}

    iterations: list[dict] = []
    last_bus, last_br, last_summ = {}, {}, {}
    for it in range(1, max_iter + 1):
        for h in hours:                                  # aplica factor de cada hora
            if h in base_load.index:
                _apply_factors_hour(n, base_load, factors[h], h)
        solve_network(n)
        dispatch = n.generators_t.p

        deltas, losses, viol, ovl = [], [], 0, 0
        for h in hours:
            net, ctx, bus_res, br_res, ac = run_ac_modom(
                export_dir, hour=h, root=str(root), gen_disp=dispatch)
            base_h = base_load.loc[h] if h in base_load.index else pd.Series(dtype=float)
            new_f = lf.update_loss_factors(factors[h], net, ctx, base_h, damping=damping)
            deltas.append(lf.factor_delta(factors[h], new_f))
            factors[h] = new_f
            losses.append(ac.get("losses_mw", float("nan")))
            viol += ac.get("n_v_below_090", 0) + ac.get("n_v_above_110", 0)
            ovl += _count_overloads(net)
            last_bus[h], last_br[h], last_summ[h] = bus_res, br_res, ac
        max_delta = max(deltas) if deltas else 0.0
        iterations.append({
            "iter": it, "loss_factor_delta": round(max_delta, 6),
            "losses_mw": round(float(pd.Series(losses).mean()), 2),
            "n_violations": int(viol), "n_overload": int(ovl),
        })
        if max_delta < tol:
            break

    duration = round(time.time() - t0, 1)
    converged = bool(iterations and iterations[-1]["loss_factor_delta"] < tol)
    # hora pico (mayor demanda) como resumen representativo
    peak_h = max(last_summ, key=lambda h: last_summ[h].get("demand_mw", 0) or 0)
    peak = last_summ[peak_h]
    tag = hours[0] if len(hours) == 1 else "24h"
    run_id = f"iter_{tag}_{started.strftime('%Y%m%d_%H%M%S')}"
    manifest = {
        "run_id": run_id, "project_id": project_id, "type": "iterative",
        "label": f"Iterativo DC↔AC · {'24 h' if len(hours)>1 else hours[0]}",
        "status": "completed" if (converged and peak.get("converged")) else "warning",
        "started": started.isoformat(), "duration_s": duration,
        "params": {"hours": hours, "max_iter": max_iter, "tol": tol, "damping": damping,
                   "export_dir": export_dir.name},
        "summary": {
            "hour": peak_h, "n_hours": len(hours), "n_iterations": len(iterations),
            "loss_factor_converged": converged,
            **{k: peak.get(k) for k in (
                "converged", "demand_mw", "gen_mw", "slack_mw", "losses_mw",
                "v_min", "v_max", "n_v_below_090", "n_v_above_110",
                "modom_buses_with_v", "modom_buses_total")},
            "final_overloads": iterations[-1].get("n_overload", 0) if iterations else 0,
            "final_delta": iterations[-1].get("loss_factor_delta") if iterations else None,
        },
        "coverage": {k: peak.get(k) for k in (
            "gen_coverage", "load_coverage", "gen_matched_mw", "load_matched_mw")},
    }

    if write:
        out = Path(root) / "results" / "runs" / run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "iterations.json").write_text(
            json.dumps(iterations, indent=2, ensure_ascii=False), encoding="utf-8")
        # AC por hora (tensiones y cargabilidad) con columna `hour`
        _concat_hourly(last_bus).to_csv(out / "ac_bus_voltages.csv", index=False)
        _concat_hourly(last_br).to_csv(out / "ac_branch_loading.csv", index=False)
        # despacho 24h DC (PyPSA) por generador → para comparación DC vs AC
        n.generators_t.p.loc[hours].to_csv(out / "dispatch_dc.csv")
        # precio nodal por hora (dual del balance) → métrica "costo marginal por barra"
        try:
            n.buses_t.marginal_price.loc[hours].round(2).to_csv(out / "nodal_prices.csv")
        except Exception:  # noqa: BLE001
            pass
        # resumen por hora
        pd.DataFrame([{"hour": h, **last_summ[h]} for h in hours]).to_csv(
            out / "summary_by_hour.csv", index=False)
        manifest["_run_dir"] = str(out)
    manifest["iterations"] = iterations
    return manifest


def _concat_hourly(by_hour: dict) -> pd.DataFrame:
    frames = []
    for h, df in by_hour.items():
        if df is not None and len(df):
            d = df.copy()
            d.insert(0, "hour", h)
            frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

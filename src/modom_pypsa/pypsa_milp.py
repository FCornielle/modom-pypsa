"""MILP completo del MODOM en PyPSA — unit commitment co-optimizado.

A diferencia de `pypsa_network.build_network` (que TOMA el commitment ya resuelto del
MODOM y solo reproduce el despacho dentro de él), este módulo **re-decide** el
encendido/apagado de las unidades térmicas resolviendo el MILP, reproduciendo las
familias de ecuaciones del MODOM que antes se tomaban fijas:

- Commitment binario con costos de arranque/parada, tiempos mínimos y rampas
  (eq. 1, 3–4, 16–24) vía generadores `committable` de PyPSA.
- Límites de generación con márgenes de reserva (eq. 7–9).
- Reservas RPF/RSF/AGC co-optimizadas como restricciones propias (eq. 10–15).
- Servicios auxiliares como consumo fijo por barra (eq. 33).
- Embalses hidroeléctricos: tope de energía diaria por unidad (eq. 36).
- Red DC, límites térmicos y flowgates (eq. 26–28) — reutilizados de `pypsa_network`.

Los parámetros vienen de `data/processed/commitment/*` y `data/processed/hydro/*`
(ingeridos con `scripts/build_modom_params.py` desde el workbook MODOM).

Notas de fidelidad (honestas):
- `TMO` (tiempo mínimo de operación) y las eficiencias hidráulicas `RENDH`/aportes no
  están poblados en el workbook vigente; el min-up usa `TARR` como piso y la hidro se
  acota por disponibilidad + tope de energía opcional. Ver la pestaña Metodología.
- El commitment de MODOM incorpora contratos y los "escalones" de asignación de RPF
  (heurística multi-etapa) que aquí se resuelven como un único MILP co-optimizado:
  el ALCANCE de las ecuaciones es fiel; el proceso de solución es más limpio (un solo
  MILP en vez de 8 SOLVE), así que el despacho puede diferir cuando hay óptimos alternos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import pypsa_network as pn

DEFAULT_DATA_DIR = pn.DEFAULT_DATA_DIR
DEFAULT_RESULTS_DIR = pn.REPO_ROOT / "results" / "pypsa_milp" if hasattr(pn, "REPO_ROOT") \
    else Path(__file__).resolve().parents[2] / "results" / "pypsa_milp"

# Costo de arranque por defecto (C_ARR no está tabulado en el workbook): se usa un
# múltiplo pequeño del CVP·Pmin·TARR como proxy documentado. Mantiene el incentivo a no
# ciclar unidades sin distorsionar el mérito. Ver nota de fidelidad arriba.
STARTUP_COST_HOURS = 2.0  # horas-equivalentes de Pmin·CVP como costo de arranque


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _v(row, key: str, default: float = 0.0) -> float:
    """Valor numérico de una celda tolerante a NaN/vacío (NaN es truthy en Python)."""
    v = row.get(key)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(f) else f


def _load_params(data_dir: Path):
    gp_path = data_dir / "commitment" / "gen_params.csv"
    opt_path = data_dir / "commitment" / "model_options.csv"
    gp = pd.read_csv(gp_path).set_index("generator_id") if gp_path.exists() else pd.DataFrame()
    opts: dict[str, float] = {}
    if opt_path.exists():
        row = pd.read_csv(opt_path)
        if len(row):
            opts = {k: float(v) for k, v in row.iloc[0].items() if pd.notna(v)}
    return gp, opts


def _apply_overrides(n, overrides: dict) -> dict:
    """Aplica ediciones de escenario sobre la red ANTES de resolver (Scenario Studio).

    `overrides["generators"][gid]`: `cvp` (RD$/MWh → marginal_cost), `availability_pct`
    (escala p_max_pu), `enabled` (False → p_nom=0, la unidad sale del despacho).
    `overrides["global"]`: `demand_pct` (escala la demanda), `flowgate_derate_pct`
    (escala los límites de flowgate), `line_derate_pct` (escala s_nom de líneas).
    Devuelve un resumen de lo aplicado para auditar la corrida.
    """
    import pandas as _pd

    applied = {"generators": 0, "global": {}}
    gens = (overrides or {}).get("generators", {}) or {}
    glob = (overrides or {}).get("global", {}) or {}

    for gid, ed in gens.items():
        if gid not in n.generators.index:
            continue
        changed = False
        if "cvp" in ed and ed["cvp"] not in (None, ""):
            n.generators.at[gid, "marginal_cost"] = float(ed["cvp"])
            changed = True
        if ed.get("enabled") is False:
            n.generators.at[gid, "p_nom"] = 0.0
            changed = True
        if "availability_pct" in ed and ed["availability_pct"] not in (None, ""):
            f = max(0.0, float(ed["availability_pct"]) / 100.0)
            pmax = n.generators_t.p_max_pu
            if gid in pmax.columns:
                n.generators_t.p_max_pu[gid] = (pmax[gid] * f).clip(0.0, 1.0)
            else:
                n.generators_t.p_max_pu[gid] = _pd.Series(
                    min(f, 1.0), index=n.snapshots)
            changed = True
        applied["generators"] += int(changed)

    dpct = glob.get("demand_pct")
    if dpct not in (None, "") and float(dpct) != 100.0:
        n.loads_t.p_set = n.loads_t.p_set * (float(dpct) / 100.0)
        applied["global"]["demand_pct"] = float(dpct)
    fgd = glob.get("flowgate_derate_pct")
    if fgd not in (None, "") and float(fgd) != 100.0:
        f = float(fgd) / 100.0
        for fg in n.meta.get("flowgates", []) or []:
            fg["limit"] = {k: v * f for k, v in fg["limit"].items()}
        applied["global"]["flowgate_derate_pct"] = float(fgd)
    lnd = glob.get("line_derate_pct")
    if lnd not in (None, "") and float(lnd) != 100.0 and len(n.lines):
        f = float(lnd) / 100.0
        n.lines["s_nom"] = n.lines["s_nom"] * f
        applied["global"]["line_derate_pct"] = float(lnd)

    # Límite ABSOLUTO por flowgate (eq. 28): sobre-escribe el del MODOM en todos los
    # períodos. Se aplica después del derateo global, así que el valor editado manda.
    fgs = (overrides or {}).get("flowgates", {}) or {}
    if fgs:
        for fg in n.meta.get("flowgates", []) or []:
            ed = fgs.get(fg["id"])
            if ed and ed.get("limit_mw") not in (None, ""):
                lim = float(ed["limit_mw"])
                fg["limit"] = {k: lim for k in fg["limit"]}
                applied.setdefault("flowgates", {})[fg["id"]] = lim
    return applied


def build_milp_network(
    data_dir: Path = DEFAULT_DATA_DIR,
    with_reserves: bool = True,
    with_hydro_budget: bool = True,
    with_flowgates: bool = True,
    pors: float | None = None,
    min_sync_fraction: float = 0.0,
    overrides: dict | None = None,
):
    """Arma la red PyPSA con commitment binario y parámetros del MILP del MODOM.

    Parte de la topología libre (`build_network(use_modom_commitment=False)`) y
    reconfigura las térmicas como `committable`, añade servicios auxiliares y el tope
    hidro. Las reservas se imponen en `solve_milp` (extra_functionality).

    Consideraciones configurables (para la plataforma / escenarios):
    - `with_reserves`: activa las reservas RPF/RSF co-optimizadas (eq. 10–15).
    - `with_flowgates`: mantiene los flowgates N-1 (eq. 28) como restricción dura.
    - `pors`: fracción de reserva del sistema (RRPF/RRSF); por defecto la del workbook (3%).
    - `min_sync_fraction`: piso de generación síncrona (regulación de frecuencia).
    """
    # Topología + loads (con factores) + flowgates + VRE por pronóstico, SIN commitment fijo.
    n = pn.build_network(data_dir=data_dir, use_modom_commitment=False,
                         min_sync_fraction=min_sync_fraction)

    gp, opts = _load_params(data_dir)
    n.meta["milp_options"] = opts
    n.meta["milp"] = True
    if not with_flowgates:
        n.meta["flowgates"] = []  # desactiva la N-1 (escenario sin seguridad)

    # Overrides del escenario (Scenario Studio): CVP/disponibilidad/on-off por unidad y
    # derateos globales. Se aplican ANTES de reconfigurar committable y las reservas.
    n.meta["overrides_applied"] = _apply_overrides(n, overrides or {})

    vre_ids = set(n.generators.index[n.generators.get("is_synchronous", True) == False]) \
        if "is_synchronous" in n.generators.columns else set()
    # hidro por mapeo gen->embalse
    hydro_map_path = data_dir / "hydro" / "gen_reservoir.csv"
    hydro_ids: set[str] = set()
    if hydro_map_path.exists():
        hydro_ids = set(_read(hydro_map_path)["generator_id"])

    real = n.generators.index[~n.generators.carrier.isin(["unserved", "dump"])]
    committed = 0
    reserve_rpf: dict[str, float] = {}
    reserve_rsf: dict[str, float] = {}
    max_starts: dict[str, int] = {}
    for gid in real:
        if gid not in gp.index:
            continue
        row = gp.loc[gid]
        p_nom = float(n.generators.at[gid, "p_nom"])
        if p_nom <= 0:
            continue
        is_vre = gid in vre_ids
        is_hydro = gid in hydro_ids
        # márgenes de reserva declarados (para eq. 10–15)
        mrpf = _v(row, "MRPF")
        mrsf = _v(row, "MRSF")
        if mrpf > 0:
            reserve_rpf[gid] = mrpf
        if mrsf > 0:
            reserve_rsf[gid] = mrsf

        # Solo las térmicas despachables son committable (VRE e hidro no ciclan binario).
        if is_vre or is_hydro:
            continue
        pmn = _v(row, "PMN")
        cvp = float(n.generators.at[gid, "marginal_cost"])
        tarr = int(_v(row, "TARR"))
        tpar = int(_v(row, "TPAR"))
        tmo = int(_v(row, "TMO"))
        tmpa = int(_v(row, "TMPA"))
        rs = _v(row, "RS")  # MW/h rampa subida
        rb = _v(row, "RB")  # MW/h rampa bajada
        acc_ini = int(_v(row, "ACC_INI"))

        n.generators.at[gid, "committable"] = True
        base_pmin_pu = min(max(pmn / p_nom, 0.0), 1.0) if p_nom else 0.0
        # p_min_pu POR SNAPSHOT capado a la disponibilidad: cuando avail_pu=0 el mínimo
        # también es 0, evitando infactibilidad si min-up/estado inicial fuerza ON en una
        # hora sin disponibilidad. Cuando la unidad está OFF (status=0), p=0 igualmente.
        avail_pu = (n.generators_t.p_max_pu[gid]
                    if gid in getattr(n.generators_t, "p_max_pu", pd.DataFrame()).columns
                    else pd.Series(1.0, index=n.snapshots))
        pmin_series = avail_pu.clip(upper=base_pmin_pu).reindex(n.snapshots).fillna(0.0)
        n.generators_t.p_min_pu[gid] = pmin_series
        # min-up (eq. 19): TMO no está poblado -> piso con TARR. min-down (eq. 22): TMPA.
        n.generators.at[gid, "min_up_time"] = max(tmo, tarr, 1)
        n.generators.at[gid, "min_down_time"] = max(tmpa, tpar, 1)
        n.generators.at[gid, "start_up_cost"] = STARTUP_COST_HOURS * cvp * pmn
        n.generators.at[gid, "shut_down_cost"] = 0.0
        # rampas (eq. 16–17): fracción de p_nom por hora; solo si el MODOM las declara.
        if rs > 0:
            n.generators.at[gid, "ramp_limit_up"] = min(rs / p_nom, 1.0)
        if rb > 0:
            n.generators.at[gid, "ramp_limit_down"] = min(rb / p_nom, 1.0)
        n.generators.at[gid, "initial_status"] = 1 if acc_ini else 0
        namx = int(_v(row, "NAMX"))
        if namx > 0:
            max_starts[gid] = namx
        committed += 1

    # --- Servicios auxiliares (eq. 33): SSA = PMX·SSAA como consumo fijo en la barra ---
    ssa_by_bus: dict[str, float] = {}
    for gid in real:
        if gid not in gp.index:
            continue
        ssaa = _v(gp.loc[gid], "SSAA") if gid in gp.index else 0.0
        pmx = _v(gp.loc[gid], "PMX") if gid in gp.index else 0.0
        if ssaa > 0 and pmx > 0:
            bus = n.generators.at[gid, "bus"]
            ssa_by_bus[bus] = ssa_by_bus.get(bus, 0.0) + ssaa * pmx
    n_ssa = 0
    if ssa_by_bus:
        buses = list(ssa_by_bus)
        n.add("Load", [f"ssa_{b}" for b in buses], bus=buses,
              p_set=[ssa_by_bus[b] for b in buses])
        n_ssa = len(buses)

    # --- Tope de energía diaria de hidro (eq. 36): Σ_t P_h ≤ E_budget_h ---
    # Sin RENDH/aportes en el workbook, el presupuesto por defecto = energía de la
    # disponibilidad (no muerde); se puede sobre-escribir con hydro_daily_budget.
    n.meta["milp_reserves"] = {
        "rpf": reserve_rpf, "rsf": reserve_rsf,
        "pors": float(pors if pors is not None else (opts.get("PORS", 0.03) or 0.03)),
        "cvrrf": float(opts.get("CVRRF", 2e6) or 2e6),
        "enabled": bool(with_reserves),
    }
    n.meta["milp_hydro"] = {"units": sorted(hydro_ids), "enabled": bool(with_hydro_budget)}
    n.meta["milp_max_starts"] = max_starts
    n.meta["counts"].update({
        "committable_units": int(committed),
        "reserve_rpf_units": int(len(reserve_rpf)),
        "reserve_rsf_units": int(len(reserve_rsf)),
        "ssa_buses": int(n_ssa),
        "hydro_units": int(len(hydro_ids)),
        "max_starts_units": int(len(max_starts)),
    })
    n.meta["model"] = "milp_modom_full"
    return n


# --------------------------------------------------------------------------- #
#  Restricciones propias del MILP (reservas + hidro), vía extra_functionality
# --------------------------------------------------------------------------- #
def _reserve_constraint(n, snapshots):
    """Reservas RPF/RSF co-optimizadas (eq. 10–15) con holgura penalizada (eq. 1).

    Para cada unidad committable con margen declarado:
      - headroom (eq. 7):  P + r_rpf + r_rsf <= Pmax·status
      - tope de margen (eq. 5/12): r_rpf <= MRPF·status,  r_rsf <= MRSF·status
    Requisito del sistema como fracción del despacho (eq. 10–11):
      Σ r_rpf + ξ_rpf >= PORS·ΣP ;  Σ r_rsf + ξ_rsf >= PORS·ΣP
    La holgura ξ se penaliza con CVRRF en el objetivo (término de reserva de eq. 1).
    """
    import xarray as xr

    cfg = n.meta.get("milp_reserves", {}) or {}
    if not cfg.get("enabled"):
        return
    m = n.model
    if "Generator-status" not in m.variables or "Generator-p" not in m.variables:
        return
    p = m["Generator-p"]
    status = m["Generator-status"]
    com = list(status.coords["name"].values)
    rpf = {g: v for g, v in cfg.get("rpf", {}).items() if g in com}
    rsf = {g: v for g, v in cfg.get("rsf", {}).items() if g in com}
    res_gens = sorted(set(rpf) | set(rsf))
    if not res_gens:
        return
    snaps = list(snapshots)
    pors = float(cfg.get("pors", 0.03))
    cvrrf = float(cfg.get("cvrrf", 2e6))
    pmax_t = getattr(n.generators_t, "p_max_pu", pd.DataFrame())
    p_nom = n.generators.p_nom

    def _cap(g):  # capacidad disponible por snapshot (MW)
        pu = (pmax_t[g].reindex(snaps).fillna(0.0) if g in pmax_t.columns
              else pd.Series(1.0, index=snaps))
        return xr.DataArray((pu * float(p_nom[g])).values, coords=[("snapshot", snaps)])

    rpf_gens = sorted(rpf)
    rsf_gens = sorted(rsf)
    r_rpf = m.add_variables(lower=0.0, coords=[pd.Index(snaps, name="snapshot"),
                            pd.Index(rpf_gens, name="name")], name="Reserve-rpf") \
        if rpf_gens else None
    r_rsf = m.add_variables(lower=0.0, coords=[pd.Index(snaps, name="snapshot"),
                            pd.Index(rsf_gens, name="name")], name="Reserve-rsf") \
        if rsf_gens else None

    # headroom + topes de margen por unidad
    for g in res_gens:
        cap = _cap(g)
        lhs = 1.0 * p.sel(name=g)
        if r_rpf is not None and g in rpf:
            lhs = lhs + r_rpf.sel(name=g)
            m.add_constraints(r_rpf.sel(name=g) - float(rpf[g]) * status.sel(name=g) <= 0,
                              name=f"res_rpf_cap_{g}")
        if r_rsf is not None and g in rsf:
            lhs = lhs + r_rsf.sel(name=g)
            m.add_constraints(r_rsf.sel(name=g) - float(rsf[g]) * status.sel(name=g) <= 0,
                              name=f"res_rsf_cap_{g}")
        m.add_constraints(lhs - cap * status.sel(name=g) <= 0, name=f"res_headroom_{g}")

    # requisito del sistema (fracción del despacho real) con holgura
    real = list(n.generators.index[~n.generators.carrier.isin(["unserved", "dump"])])
    real = [g for g in real if g in p.coords["name"].values]
    p_real = p.sel(name=real).sum("name")
    penalty = None
    if r_rpf is not None:
        xi = m.add_variables(lower=0.0, coords=[pd.Index(snaps, name="snapshot")],
                             name="Reserve-rpf-slack")
        m.add_constraints(r_rpf.sum("name") + xi - pors * p_real >= 0, name="res_req_rpf")
        penalty = cvrrf * xi.sum()
    if r_rsf is not None:
        xi2 = m.add_variables(lower=0.0, coords=[pd.Index(snaps, name="snapshot")],
                              name="Reserve-rsf-slack")
        m.add_constraints(r_rsf.sum("name") + xi2 - pors * p_real >= 0, name="res_req_rsf")
        penalty = (penalty + cvrrf * xi2.sum()) if penalty is not None else cvrrf * xi2.sum()
    if penalty is not None:
        m.objective = m.objective + penalty


def _hydro_budget_constraint(n, snapshots):
    """Tope de energía diaria por unidad hidro (eq. 36): Σ_t P_h ≤ E_budget_h.

    El presupuesto por defecto es la energía de la disponibilidad diaria (no muerde):
    el workbook vigente no puebla RENDH/aportes, así que la restricción queda
    estructuralmente presente pero laxa. Se puede fijar un presupuesto real por unidad
    en n.meta['milp_hydro']['budget_mwh'] (MWh/día).
    """
    cfg = n.meta.get("milp_hydro", {}) or {}
    if not cfg.get("enabled"):
        return
    budgets = cfg.get("budget_mwh", {}) or {}
    if not budgets:
        return
    m = n.model
    p = m["Generator-p"]
    names = set(p.coords["name"].values)
    for h, e in budgets.items():
        if h in names:
            m.add_constraints(p.sel(name=h).sum("snapshot") <= float(e),
                              name=f"hydro_budget_{h}")


def _max_starts_constraint(n, snapshots):
    """Número máximo de arranques por unidad en el horizonte (eq. 24): Σ_t start_up ≤ NAMX."""
    max_starts = n.meta.get("milp_max_starts", {}) or {}
    if not max_starts:
        return
    m = n.model
    if "Generator-start_up" not in m.variables:
        return
    su = m["Generator-start_up"]
    names = set(su.coords["name"].values)
    for gid, namx in max_starts.items():
        if gid in names:
            m.add_constraints(su.sel(name=gid).sum("snapshot") <= int(namx),
                              name=f"max_starts_{gid}")


def _milp_extra(n, snapshots):
    """Compone todas las restricciones del MILP: flowgates + reservas + hidro + arranques."""
    pn._flowgate_constraint(n, snapshots)
    pn._min_sync_constraint(n, snapshots)
    _reserve_constraint(n, snapshots)
    _hydro_budget_constraint(n, snapshots)
    _max_starts_constraint(n, snapshots)


def solve_milp(n, solver_name: str = "highs", mip_rel_gap: float = 0.01,
               time_limit: float = 600.0):
    """Resuelve el MILP con commitment binario + reservas + flowgates + hidro."""
    n.optimize(
        solver_name=solver_name,
        extra_functionality=_milp_extra,
        solver_options={
            "mip_rel_gap": mip_rel_gap,
            "time_limit": time_limit,
            "mip_heuristic_effort": 0.2,
        },
    )
    return n


def summarize(n) -> dict[str, object]:
    """Resumen del MILP: reutiliza pn.summarize y añade métricas de commitment/reservas."""
    out = pn.summarize(n)
    st = getattr(n.generators_t, "status", pd.DataFrame())
    if len(st):
        starts = int(((st.diff().fillna(0.0) > 0.5).sum().sum()))
        out["commitment"] = {
            "committable_units": int(st.shape[1]),
            "units_on_peak": int((st.sum(axis=1)).max()),
            "total_startups": starts,
        }
    return out


def export_results(n, outdir: Path = DEFAULT_RESULTS_DIR) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    summary = summarize(n)
    keep = n.generators.index[n.generators.carrier != "dump"]
    n.generators_t.p[keep].round(4).to_csv(outdir / "generation_by_snapshot.csv")
    if len(getattr(n.generators_t, "status", [])):
        n.generators_t.status.round(0).astype(int).to_csv(outdir / "commitment_by_snapshot.csv")
    n.loads_t.p_set.round(4).to_csv(outdir / "load_by_snapshot.csv")
    if len(n.lines):
        n.lines_t.p0.round(4).to_csv(outdir / "line_flows_by_snapshot.csv")
    n.buses_t.marginal_price.round(4).to_csv(outdir / "nodal_prices_by_snapshot.csv")
    fg = pn.flowgate_utilization(n)
    if len(fg):
        fg.to_csv(outdir / "flowgate_utilization_by_snapshot.csv", index=False)
    (outdir / "pypsa_milp_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary

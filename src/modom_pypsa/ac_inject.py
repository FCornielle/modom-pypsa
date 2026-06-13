"""Inyecta NUESTRO despacho PyPSA/MODOM sobre la red AC de DIgSILENT y agrega los
resultados a las 717 barras MODOM (regla de coherencia, opción A).

Flujo:
1. `build_from_digsilent` arma la red física (R/X/B, trafos, shunts, topología) con
   el W-code (`for_name`) en cada barra → la llave de cruce con MODOM.
2. `inject_modom_dispatch` reemplaza el despacho del export por el nuestro, cruzando
   por W-code: generación por barra (gen `bus_id`/`centrales_terminal_bus_id`),
   carga por barra (`load_id`). Conserva las consignas de tensión (control de V) de
   las máquinas DIgSILENT; sólo cambia P (y Q de carga por factor de potencia).
3. `run_ac_modom` poda islas, corre el flujo AC y agrega V/ángulo y cargabilidad de
   ramas de vuelta a las 717 barras MODOM por `for_name`.

La cobertura es parcial (~70-80% de barras/gens/cargas) por divergencias de
convención de W-codes entre MODOM y DIgSILENT; se reporta explícitamente.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .ac_digsilent import build_from_digsilent

DISPATCH_CSV = "data/processed/modom_results/modom_generator_dispatch.csv"
GENERATORS_CSV = "data/processed/generators/generators.csv"
LOADS_CSV = "data/processed/loads_time_series/loads_time_series.csv"
BUSES_CSV = "data/processed/buses/buses.csv"


def _first_bus(forname_to_bus: dict, w) -> int | None:
    bs = forname_to_bus.get(str(w))
    return bs[0] if bs else None


def inject_modom_dispatch(net, ctx, hour, gen_disp, gens, loads):
    """Sobrescribe generación y carga del net con NUESTRO despacho MODOM (hora `hour`).

    Devuelve un dict de cobertura (MW cruzados vs MW sin barra en el export).
    """
    f2b = ctx["forname_to_bus"]

    # ---- objetivo de generación por barra pandapower (cruce por W-code) ----
    row = gen_disp.loc[hour]
    bus_of = dict(zip(gens.generator_id, gens.bus_id.astype(str)))
    term_of = dict(zip(gens.generator_id, gens.centrales_terminal_bus_id.astype(str)))
    gen_by_bus: dict[int, float] = {}
    g_ok = g_miss = 0.0
    for g, mw in row.items():
        mw = float(mw)
        if mw == 0:
            continue
        b = _first_bus(f2b, bus_of.get(g, "")) or _first_bus(f2b, term_of.get(g, ""))
        if b is None:
            g_miss += mw
            continue
        gen_by_bus[b] = gen_by_bus.get(b, 0.0) + mw
        g_ok += mw

    # ---- objetivo de carga por barra pandapower ----
    lh = loads[loads.snapshot_id == hour]
    load_w = lh.groupby("load_id").p_set_mw.sum()
    load_by_bus: dict[int, float] = {}
    l_ok = l_miss = 0.0
    for w, p in load_w.items():
        p = float(p)
        b = _first_bus(f2b, w)
        if b is None:
            l_miss += p
            continue
        load_by_bus[b] = load_by_bus.get(b, 0.0) + p
        l_ok += p

    slack_buses = set(net.ext_grid.bus.tolist())

    # ---- aplicar generación: conserva consignas de V; reescribe P ----
    # VRE del export (sgen) se anula: nuestro gen_by_bus ya incluye toda la generación.
    net.sgen.loc[:, "p_mw"] = 0.0
    net.sgen.loc[:, "q_mvar"] = 0.0
    handled = set()
    for i in net.gen.index:
        b = int(net.gen.at[i, "bus"])
        net.gen.at[i, "p_mw"] = gen_by_bus.get(b, 0.0)
        handled.add(b)
    # generación nuestra en barras sin máquina síncrona modelada -> sgen PQ (inyección).
    # En la barra slack NO se crea nada: el ext_grid (Punta Catalina) ya aporta su P.
    import pandapower as pp
    for b, p in gen_by_bus.items():
        if b in handled or b in slack_buses:
            continue
        pp.create_sgen(net, b, p_mw=p, q_mvar=0.0, name="modom_inj")

    # ---- aplicar carga: escala las cargas del export al objetivo, conserva fp ----
    load_groups: dict[int, list] = {}
    for i in net.load.index:
        load_groups.setdefault(int(net.load.at[i, "bus"]), []).append(i)
    # Carga MODOM no cruzada (W-code sin barra en el export): no se puede ubicar, pero
    # MODOM SÍ la tiene. La representamos escalando la carga del export en las barras
    # SIN match al total no cruzado -> la demanda total = demanda MODOM real (fiel) y
    # con la distribución espacial del export. Equilibra el slack.
    unmatched_buses = [b for b in load_groups if b not in load_by_bus]
    export_at_unmatched = sum(
        float(net.load.at[i, "p_mw"]) for b in unmatched_buses for i in load_groups[b])
    fill_k = (l_miss / export_at_unmatched) if export_at_unmatched > 1e-6 else 0.0
    kept_export_mw = 0.0
    for b, idxs in load_groups.items():
        target = load_by_bus.get(b)
        if target is None:
            for i in idxs:
                net.load.at[i, "p_mw"] *= fill_k
                net.load.at[i, "q_mvar"] *= fill_k
            kept_export_mw += sum(float(net.load.at[i, "p_mw"]) for i in idxs)
            continue
        cur = sum(float(net.load.at[i, "p_mw"]) for i in idxs)
        if cur > 1e-6:
            k = target / cur
            for i in idxs:                       # escala P y Q (conserva fp por elemento)
                net.load.at[i, "p_mw"] *= k
                net.load.at[i, "q_mvar"] *= k
        else:                                    # sin P previo: reparte con fp 0.95
            per = target / len(idxs)
            for i in idxs:
                net.load.at[i, "p_mw"] = per
                net.load.at[i, "q_mvar"] = per * math.tan(math.acos(0.95))
    # carga nuestra en barras sin carga en el export -> crear (fp 0.95)
    import pandapower as pp
    for b, p in load_by_bus.items():
        if b not in load_groups:
            pp.create_load(net, b, p_mw=p, q_mvar=p * math.tan(math.acos(0.95)),
                           name="modom_inj")

    return {
        "gen_matched_mw": g_ok, "gen_unmatched_mw": g_miss,
        "load_matched_mw": l_ok, "load_unmatched_mw": l_miss,
        "load_kept_export_mw": kept_export_mw,
        "gen_coverage": g_ok / (g_ok + g_miss) if (g_ok + g_miss) else 0.0,
        "load_coverage": l_ok / (l_ok + l_miss) if (l_ok + l_miss) else 0.0,
    }


def aggregate_to_modom_buses(net, ctx, modom_bus_ids) -> pd.DataFrame:
    """Lleva las tensiones del flujo AC a las 717 barras MODOM por `for_name`."""
    f2b = ctx["forname_to_bus"]
    rows = []
    for w in modom_bus_ids:
        b = _first_bus(f2b, w)
        vm = va = vn = float("nan")
        matched = b is not None
        if matched and b in net.res_bus.index and net.bus.at[b, "in_service"]:
            vm = float(net.res_bus.at[b, "vm_pu"])
            va = float(net.res_bus.at[b, "va_degree"])
            vn = float(net.bus.at[b, "vn_kv"])
        rows.append({"bus_id_modom": w, "vm_pu": vm, "va_degree": va,
                     "vn_kv": vn, "matched": matched})
    return pd.DataFrame(rows)


def aggregate_branches(net, ctx) -> pd.DataFrame:
    """Cargabilidad de líneas y trafos, con el W-code MODOM de cada extremo."""
    fb = ctx["for_by_bus"]
    out = []
    for kind, res, tab, cols in [
        ("line", net.res_line, net.line, ("from_bus", "to_bus")),
        ("trafo", net.res_trafo, net.trafo, ("hv_bus", "lv_bus")),
    ]:
        for i in tab.index:
            if i not in res.index:
                continue
            bi, bj = int(tab.at[i, cols[0]]), int(tab.at[i, cols[1]])
            out.append({
                "kind": kind, "name": str(tab.at[i, "name"]),
                "from_w": fb.get(bi, ""), "to_w": fb.get(bj, ""),
                "loading_percent": float(res.at[i, "loading_percent"]),
                "p_from_mw": float(res.at[i, res.columns[0]]),
            })
    return pd.DataFrame(out)


def run_ac_modom(export_dir, hour="h_19", root="."):
    """Orquesta: build → inyecta despacho MODOM → poda islas → flujo AC → agrega.

    Devuelve (net, ctx, bus_results, branch_results, summary).
    """
    import pandapower as pp
    import pandapower.topology as top

    root = Path(root)
    gen_disp = pd.read_csv(root / DISPATCH_CSV, index_col=0)
    gens = pd.read_csv(root / GENERATORS_CSV)
    loads = pd.read_csv(root / LOADS_CSV)
    modom_bus_ids = pd.read_csv(root / BUSES_CSV).bus_id_modom.tolist()

    net, ctx = build_from_digsilent(Path(export_dir))
    cov = inject_modom_dispatch(net, ctx, hour, gen_disp, gens, loads)

    # podar barras sin suministro (islas) para que el flujo no diverja
    for b in top.unsupplied_buses(net):
        for t in ("load", "gen", "sgen"):
            getattr(net, t).loc[getattr(net, t).bus == b, "in_service"] = False
        net.bus.at[b, "in_service"] = False

    conv = False
    try:
        pp.runpp(net, init="dc", max_iteration=50, numba=False)
        conv = bool(net.converged)
    except Exception as e:  # noqa: BLE001
        cov["error"] = f"{type(e).__name__}: {str(e)[:160]}"

    bus_res = aggregate_to_modom_buses(net, ctx, modom_bus_ids)
    br_res = aggregate_branches(net, ctx) if conv else pd.DataFrame()

    v = net.res_bus.vm_pu.dropna() if conv else pd.Series(dtype=float)
    summary = {
        "hour": hour, "converged": conv, **cov,
        "n_bus": ctx["n_bus"], "n_lines": ctx["n_lines"], "n_traf": ctx["n_traf"],
        "demand_mw": float(net.res_load.p_mw.sum()) if conv else float("nan"),
        "gen_mw": float(net.res_gen.p_mw.sum() + net.res_sgen.p_mw.sum()) if conv else float("nan"),
        "slack_mw": float(net.res_ext_grid.p_mw.sum()) if conv else float("nan"),
        "losses_mw": float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()) if conv else float("nan"),
        "v_min": float(v.min()) if len(v) else float("nan"),
        "v_max": float(v.max()) if len(v) else float("nan"),
        "n_v_below_090": int((v < 0.9).sum()) if len(v) else 0,
        "n_v_above_110": int((v > 1.1).sum()) if len(v) else 0,
        "modom_buses_with_v": int(bus_res.vm_pu.notna().sum()),
        "modom_buses_total": len(modom_bus_ids),
    }
    return net, ctx, bus_res, br_res, summary

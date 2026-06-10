"""Capa de verificación AC con pandapower (Fase 3).

Construye una red pandapower desde la capa canónica + los insumos reactivos del
MODOM y corre flujo de potencia AC (`runpp`). El objetivo de la Parte 2 es
VERIFICAR la red: alimentamos el flujo con el punto de operación del propio MODOM
(P del despacho, Q de cargas, consignas de tensión, shunts) y comparamos las
tensiones/flujos resultantes contra los del MODOM (`VOLTAJE`, `FLUJO_REACTIVA`).
Si coinciden, la representación de la red (topología + impedancias) es fiel.

Modelo:
- Barras con `vn_kv` real (rellenando faltantes desde las tensiones de las ramas).
- Líneas y transformadores como elemento `impedance` en pu (r,x de e_datred sobre
  base de 100 MVA); replica el tratamiento por-unidad del modelo PyPSA.
- Cargas con P (demanda canónica) + Q (MODOM). Shunts (capacitores) del MODOM.
- Generadores agregados por barra como PV con consigna de tensión del MODOM; la
  barra con mayor generación es el slack (`ext_grid`).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "processed"
DEFAULT_RESULTS_DIR = REPO_ROOT / "results" / "ac_basecase"
S_BASE_MVA = 100.0
EPS_X = 1e-4
DEFAULT_VN_KV = 138.0


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def bus_vn_kv_map(buses: pd.DataFrame, lines: pd.DataFrame,
                  trafos: pd.DataFrame) -> dict[str, float]:
    """Tensión nominal (kV) por barra: de buses.csv, con respaldo en las ramas."""
    vn = {str(r.bus_id_modom): float(r.v_nom_kv)
          for r in buses.itertuples()
          if pd.notna(_num(pd.Series([r.v_nom_kv]))[0]) and float(r.v_nom_kv) > 0}
    # respaldo: tensión declarada en los extremos de las ramas
    for df in (lines, trafos):
        for r in df.itertuples():
            for bus, col in ((r.bus0, "v_nom_bus0_kv"), (r.bus1, "v_nom_bus1_kv")):
                b = str(bus)
                if b in vn:
                    continue
                v = _num(pd.Series([getattr(r, col, None)]))[0]
                if pd.notna(v) and v > 0:
                    vn[b] = float(v)
    return vn


def load_ac_inputs(data_dir: Path, results_dir: Path) -> dict[str, object]:
    p = data_dir
    m = data_dir / "modom_results"
    buses = pd.read_csv(p / "buses" / "buses.csv")
    lines = pd.read_csv(p / "pypsa_branch_components" / "lines_v1.csv")
    trafos = pd.read_csv(p / "pypsa_branch_components" / "transformers_v1.csv")
    loads = pd.read_csv(p / "loads_time_series" / "loads_time_series.csv")
    load_pivot = (loads.assign(p=_num(loads["p_set_mw"]).fillna(0.0))
                  .pivot_table(index="snapshot_id", columns="load_id", values="p", aggfunc="sum")
                  .fillna(0.0))

    def _csv(name):
        f = m / name
        return pd.read_csv(f, index_col=0) if f.exists() else pd.DataFrame()

    return {
        "buses": buses,
        "lines": lines,
        "trafos": trafos,
        "load_pivot": load_pivot,
        "disp": _csv("modom_generator_dispatch.csv"),
        "qgen": _csv("modom_reactive_gen.csv"),
        "qload": _csv("modom_reactive_load.csv"),
        "vbus": _csv("modom_bus_voltage.csv"),
        "shunt": _csv("modom_shunt_capacitors.csv"),
        "vn": bus_vn_kv_map(buses, lines, trafos),
        "gen_bus": {str(r.generator_id).strip(): str(r.bus_id) for r in
                    pd.read_csv(p / "generators" / "generators.csv").itertuples()},
    }


def build_ac_snapshot(inp: dict, snap: str):
    """Construye la red pandapower para un snapshot (hora)."""
    import pandapower as pp

    vn = inp["vn"]
    net = pp.create_empty_network(sn_mva=S_BASE_MVA)
    idx: dict[str, int] = {}
    for b in inp["buses"]["bus_id_modom"].astype(str):
        idx[b] = pp.create_bus(net, vn_kv=vn.get(b, DEFAULT_VN_KV), name=b)

    def _rx(row) -> tuple[float, float]:
        x = _num(pd.Series([row.x_pu_hint]))[0]
        rr = _num(pd.Series([row.r_pu_hint]))[0]
        x = EPS_X if pd.isna(x) or abs(x) < EPS_X else float(abs(x))
        rr = 0.0 if pd.isna(rr) or rr < 0 else float(rr)
        return rr, x

    # líneas: impedancia en pu (base 100 MVA)
    for r in inp["lines"].itertuples():
        b0, b1 = str(r.bus0), str(r.bus1)
        if b0 not in idx or b1 not in idx or b0 == b1:
            continue
        rr, x = _rx(r)
        pp.create_impedance(net, idx[b0], idx[b1], rft_pu=rr, xft_pu=x,
                            sn_mva=S_BASE_MVA, name=str(r.name))

    # transformadores: elemento `trafo` real (vk% derivado de x_pu y sn). Maneja la
    # relación de transformación, que el modelo de impedancia no captura (causa de
    # los colapsos de tensión en bolsones radiales de 69 kV).
    for r in inp["trafos"].itertuples():
        b0, b1 = str(r.bus0), str(r.bus1)
        if b0 not in idx or b1 not in idx or b0 == b1:
            continue
        rr, x = _rx(r)
        v0, v1 = vn.get(b0, DEFAULT_VN_KV), vn.get(b1, DEFAULT_VN_KV)
        vhv, vlv = max(v0, v1), min(v0, v1)
        sn = _num(pd.Series([r.s_nom_mva_hint]))[0]
        sn = 100.0 if pd.isna(sn) or sn <= 0 else float(sn)
        if vhv <= 0 or abs(vhv - vlv) / vhv < 0.01:  # mismo nivel -> impedancia
            pp.create_impedance(net, idx[b0], idx[b1], rft_pu=rr, xft_pu=x,
                                sn_mva=S_BASE_MVA, name=str(r.name))
            continue
        z = (rr ** 2 + x ** 2) ** 0.5
        vk = min(max(z * sn, 1.0), 30.0)           # vk% en base del trafo, acotado
        vkr = min(rr * sn, vk * 0.99)
        hv, lv = (b0, b1) if v0 >= v1 else (b1, b0)
        pp.create_transformer_from_parameters(
            net, hv_bus=idx[hv], lv_bus=idx[lv], sn_mva=sn,
            vn_hv_kv=vhv, vn_lv_kv=vlv, vk_percent=vk, vkr_percent=max(vkr, 0.0),
            pfe_kw=0.0, i0_percent=0.0, name=str(r.name))

    # cargas: P canónica + Q del MODOM
    lp = inp["load_pivot"].loc[snap] if snap in inp["load_pivot"].index else pd.Series(dtype=float)
    ql = inp["qload"].loc[snap] if snap in getattr(inp["qload"], "index", []) else pd.Series(dtype=float)
    for b in lp.index:
        b = str(b)
        if b not in idx:
            continue
        p = float(lp.get(b, 0.0) or 0.0)
        q = float(ql.get(b, 0.0) or 0.0)
        if abs(p) > 1e-9 or abs(q) > 1e-9:
            pp.create_load(net, idx[b], p_mw=p, q_mvar=q)

    # shunts (capacitores): MVAr capacitivo -> q_mvar negativo en pandapower
    sh = inp["shunt"].loc[snap] if snap in getattr(inp["shunt"], "index", []) else pd.Series(dtype=float)
    for b in getattr(sh, "index", []):
        b = str(b)
        if b in idx and abs(float(sh.get(b, 0.0) or 0.0)) > 1e-9:
            pp.create_shunt(net, idx[b], q_mvar=-float(sh[b]), p_mw=0.0)

    # generación agregada por barra: P y Q del MODOM (modelo PQ, estable). La barra
    # con mayor generación es el slack (ext_grid) y fija la tensión de referencia.
    disp = inp["disp"].loc[snap] if snap in getattr(inp["disp"], "index", []) else pd.Series(dtype=float)
    qgen = inp["qgen"].loc[snap] if snap in getattr(inp["qgen"], "index", []) else pd.Series(dtype=float)
    vb = inp["vbus"].loc[snap] if snap in getattr(inp["vbus"], "index", []) else pd.Series(dtype=float)
    p_by_bus: dict[str, float] = {}
    q_by_bus: dict[str, float] = {}
    for gid in getattr(disp, "index", []):
        bus = inp["gen_bus"].get(str(gid))
        p = float(disp.get(gid, 0.0) or 0.0)
        if bus in idx and p > 1e-6:
            p_by_bus[bus] = p_by_bus.get(bus, 0.0) + p
            q_by_bus[bus] = q_by_bus.get(bus, 0.0) + float(qgen.get(gid, 0.0) or 0.0)
    if not p_by_bus:
        raise ValueError(f"Sin generación para el snapshot {snap}")
    slack_bus = max(p_by_bus, key=p_by_bus.get)
    for bus, p in p_by_bus.items():
        vm = float(vb.get(bus, 1.0) or 1.0)
        vm = vm if 0.9 <= vm <= 1.1 else 1.0
        if bus == slack_bus:
            pp.create_ext_grid(net, idx[bus], vm_pu=vm, va_degree=0.0)
        else:
            # PV: el generador fija tensión (estable en red débil); Q sin límite.
            pp.create_gen(net, idx[bus], p_mw=p, vm_pu=vm)
    return net, idx, slack_bus


def run_ac(data_dir: Path = DEFAULT_DATA_DIR,
           results_dir: Path = DEFAULT_RESULTS_DIR) -> dict[str, object]:
    """Corre el flujo AC por hora; escribe tensiones, pérdidas y un reporte de fidelidad."""
    import pandapower as pp

    inp = load_ac_inputs(data_dir, results_dir)
    snaps = [s for s in inp["disp"].index] if len(inp["disp"]) else list(inp["load_pivot"].index)
    vm_rows: dict[str, pd.Series] = {}
    losses, conv = {}, {}
    for snap in snaps:
        net, idx, _ = build_ac_snapshot(inp, snap)
        ok = False
        for init in ("dc", "flat"):  # DC-init es mucho más robusto; flat de respaldo
            try:
                pp.runpp(net, init=init, max_iteration=100, numba=False)
                ok = bool(net.converged)
            except Exception:
                ok = False
            if ok:
                break
        conv[snap] = ok
        if ok:
            inv = {i: b for b, i in idx.items()}
            vm_rows[snap] = pd.Series(
                {inv[i]: float(v) for i, v in net.res_bus.vm_pu.items()})
            li = float(net.res_impedance.pl_mw.sum()) if len(net.res_impedance) else 0.0
            lt = float(net.res_trafo.pl_mw.sum()) if len(net.res_trafo) else 0.0
            losses[snap] = li + lt
    ac_vm = pd.DataFrame(vm_rows).T.reindex(snaps)

    results_dir.mkdir(parents=True, exist_ok=True)
    ac_vm.round(4).to_csv(results_dir / "ac_bus_voltage.csv")

    report = compare_voltage(ac_vm, inp["vbus"])
    report.update({
        "snapshots": len(snaps),
        "converged": int(sum(conv.values())),
        "losses_mw_avg": round(sum(losses.values()) / max(len(losses), 1), 2),
    })
    import json
    (results_dir / "ac_fidelity_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def compare_voltage(ac_vm: pd.DataFrame, modom_vbus: pd.DataFrame) -> dict[str, object]:
    """Compara la tensión AC nuestra vs la del MODOM (barras y horas comunes)."""
    import numpy as np
    if ac_vm.empty or modom_vbus.empty:
        return {"matched_buses": 0}
    cols = [c for c in modom_vbus.columns if c in ac_vm.columns]
    n = min(len(ac_vm.index), len(modom_vbus.index))
    o = ac_vm.iloc[:n][cols].to_numpy(dtype=float)
    m = modom_vbus.iloc[:n][cols].to_numpy(dtype=float)
    mask = np.isfinite(o) & np.isfinite(m)
    err = np.abs(o[mask] - m[mask])
    if err.size == 0:
        return {"matched_buses": 0}
    return {
        "matched_buses": len(cols),
        "n_points": int(err.size),
        "vm_mae_pu": round(float(err.mean()), 4),
        "vm_median_pu": round(float(np.median(err)), 4),
        "vm_p90_pu": round(float(np.percentile(err, 90)), 4),
        "vm_max_pu": round(float(err.max()), 4),
        "within_0p02_pct": round(100 * float((err < 0.02).mean()), 1),
        "within_0p05_pct": round(100 * float((err < 0.05).mean()), 1),
    }

"""Capa AC sobre el modelo DETALLADO de DIgSILENT (opción A).

Construye la red pandapower NATIVAMENTE desde el export de elementos de DIgSILENT
(`salida_PDD_*`), que trae la red real y completa: 4992 terminales, líneas con
R/X/B reales, transformadores con Ucc%, shunts, interruptores (conectividad) y el
despacho del caso. Enlaces:
- barras: clave = `ruta` (path único por terminal); tensión = `U_nom_kV`; `for_name`
  guarda el código MODOM (W) para agregar resultados a nuestras 717 barras.
- líneas / interruptores: por path (`barra_*_id`), cobertura ~100%.
- transformadores: por (subestación, nombre, tensión), porque el export no trae el
  path de sus terminales.
- generadores / cargas / shunts: por `barra_con_id` (path).
- slack: el generador con `ref_slack=1`.

El objetivo de esta primera etapa es VERIFICAR que la red converge con el despacho
propio del export. Los resultados se agregan a las barras MODOM por `for_name`
(regla de coherencia: la vista del proyecto sigue siendo las 717 barras).
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

F_HZ = 60.0


def _rd(d: Path, name: str) -> pd.DataFrame:
    f = d / f"{name}.csv"
    return pd.read_csv(f, sep=",") if f.exists() else pd.DataFrame()


def _num(v, default=float("nan")) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def build_from_digsilent(export_dir: Path):
    """Arma un net de pandapower desde el export DIgSILENT. Devuelve (net, ctx)."""
    import pandapower as pp

    d = Path(export_dir)
    barras = _rd(d, "barras")
    lineas = _rd(d, "lineas")
    elmtr2 = _rd(d / "todos_los_elementos", "ElmTr2") if (d / "todos_los_elementos").exists() else _rd(d, "ElmTr2")
    tipotr2 = _rd(d, "tipos_transformadores2")
    shunts = _rd(d, "shunts")
    gsinc = _rd(d, "generadores_sinc")
    gest = _rd(d, "generadores_est")
    cargas = _rd(d, "cargas")
    inter = _rd(d, "interruptores")

    net = pp.create_empty_network(sn_mva=100.0)

    # --- Fusión de terminales por interruptores CERRADOS (union-find) ---
    # Las 4992 terminales node-breaker se colapsan a nodos eléctricos: evita los
    # lazos de impedancia cero de modelar miles de switches y acerca el modelo al
    # nivel de barra (como nuestras 717).
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in barras.itertuples():
        find(str(r.ruta))
    for r in inter.itertuples():
        if str(getattr(r, "cerrado", "1")).strip() in ("1", "1.0", "True", "true"):
            bi, bj = str(r.barra_i_id), str(r.barra_j_id)
            if bi in parent and bj in parent:
                union(bi, bj)
    # líneas de impedancia ~0 (jumpers/puentes de barra) -> fusionar también, si no
    # crean lazos de impedancia cero que singularizan el Jacobiano del flujo AC.
    for r in lineas.itertuples():
        rr, xx = abs(_num(r.R1_ohm, 9.9)), abs(_num(r.X1_ohm, 9.9))
        if rr < 0.05 and xx < 0.05:
            bi, bj = str(r.barra_i_id), str(r.barra_j_id)
            if bi in parent and bj in parent:
                union(bi, bj)

    # --- Un bus pandapower por nodo eléctrico (raíz) ---
    bus_idx: dict[str, int] = {}     # ruta -> índice de bus pandapower
    root_bus: dict[str, int] = {}    # raíz -> índice
    for_by_bus: dict[int, str] = {}
    by_name: dict[str, list] = {}    # loc_name -> [(ruta, lat, lon, vn)] para trafos
    bus_pos: dict[int, tuple] = {}   # bus -> (lat, lon, vn) para fallback GPS
    for r in barras.itertuples():
        ruta = str(r.ruta)
        vn = _num(r.U_nom_kV, 0.0) or 1.0
        lat, lon = _num(r.GPS_lat), _num(r.GPS_lon)
        root = find(ruta)
        if root not in root_bus:
            root_bus[root] = pp.create_bus(net, vn_kv=vn, name=str(r.loc_name))
            bus_pos[root_bus[root]] = (lat, lon, vn)
        bus_idx[ruta] = root_bus[root]
        fn = str(getattr(r, "for_name", "") or "").strip()
        if fn and fn.lower() != "nan":
            for_by_bus[root_bus[root]] = fn
        by_name.setdefault(str(r.loc_name).strip(), []).append((ruta, lat, lon, vn))

    # for_name -> bus (para enlace fiable de trafos por código MODOM)
    forname_to_bus: dict[str, list] = {}
    for bidx, fn in for_by_bus.items():
        forname_to_bus.setdefault(fn, []).append(bidx)

    def trafo_bus(name: str, fname: str, glat: float, glon: float, kv: float):
        tol = max(2.0, 0.1 * kv) if kv == kv else 1e9
        # 1) por for_name (código MODOM) con match de tensión
        fn = str(fname or "").strip()
        if fn and fn.lower() != "nan":
            cb = [b for b in forname_to_bus.get(fn, [])
                  if kv != kv or abs(float(net.bus.vn_kv[b]) - kv) <= tol]
            if cb:
                return cb[0]
        # 2) por nombre + tensión + GPS más cercano
        cands = [c for c in by_name.get(str(name).strip(), [])
                 if kv != kv or abs(c[3] - kv) <= tol]
        if cands:
            def dg(c):
                _, la, lo, _vn = c
                return ((la - glat) ** 2 + (lo - glon) ** 2) ** 0.5 if (la == la and glat == glat) else 9.9
            return bus_idx.get(min(cands, key=dg)[0])
        # 3) último recurso: barra de esa tensión más cercana por GPS (nombre genérico)
        if glat == glat and kv == kv:
            near = [(b, (p[0] - glat) ** 2 + (p[1] - glon) ** 2)
                    for b, p in bus_pos.items()
                    if p[2] == p[2] and abs(p[2] - kv) <= tol and p[0] == p[0]]
            if near:
                return min(near, key=lambda t: t[1])[0]
        return None

    # --- Líneas (por path) ---
    n_lines = 0
    for r in lineas.itertuples():
        bi, bj = bus_idx.get(str(r.barra_i_id)), bus_idx.get(str(r.barra_j_id))
        if bi is None or bj is None or bi == bj:
            continue
        L = max(_num(r.long_km, 0.0), 1e-3)
        R, X = _num(r.R1_ohm, 0.0), _num(r.X1_ohm, 0.0)
        B = _num(r.B1_uS, 0.0) * 1e-6  # S total
        c_nf_km = (B / (2 * math.pi * F_HZ)) * 1e9 / L if B > 0 else 0.0
        imax = _num(r.I_nom_kA, 1.0) or 1.0
        par = int(_num(r.num_paralelas, 1) or 1)
        if X == 0 and R == 0:
            continue
        pp.create_line_from_parameters(
            net, bi, bj, length_km=L,
            r_ohm_per_km=max(R, 0.0) / L, x_ohm_per_km=abs(X) / L if X else 1e-3 / L,
            c_nf_per_km=max(c_nf_km, 0.0), max_i_ka=imax, parallel=max(par, 1),
            name=str(r.loc_name))
        n_lines += 1

    # --- Transformadores (por subestación+nombre+tensión, tipo por typ_id) ---
    typ_by_path = {str(t["ruta"]): t for t in tipotr2.to_dict("records")} if len(tipotr2) else {}
    typ_by_name = {str(t["loc_name"]): t for t in tipotr2.to_dict("records")} if len(tipotr2) else {}
    n_traf = 0
    for r in elmtr2.to_dict("records"):
        typ = typ_by_path.get(str(r.get("typ_id", "")))
        if typ is None:
            typ = typ_by_name.get(str(r.get("typ_id", "")).split("\\")[-1].replace(".TypTr2", ""))
        if typ is None:
            continue
        uhv, ulv = _num(typ.get("U_AT_kV")), _num(typ.get("U_BT_kV"))
        glat, glon = _num(r.get("GPSlat")), _num(r.get("GPSlon"))
        hv = trafo_bus(r.get("barra(bushv)", ""), r.get("barra(bushv)_for", ""), glat, glon, uhv)
        lv = trafo_bus(r.get("barra(buslv)", ""), r.get("barra(buslv)_for", ""), glat, glon, ulv)
        if hv is None or lv is None or hv == lv:
            continue
        sn = _num(typ.get("S_nom_MVA"), 0.0)
        vk = _num(typ.get("uk_pct"), 0.0)
        if sn <= 0 or vk <= 0:
            continue
        vkr = _num(typ.get("ukr_pct"), 0.0)
        pp.create_transformer_from_parameters(
            net, hv_bus=hv, lv_bus=lv, sn_mva=sn,
            vn_hv_kv=float(net.bus.vn_kv[hv]),   # usa la tensión real de la barra (sin mismatch)
            vn_lv_kv=float(net.bus.vn_kv[lv]), vk_percent=min(max(vk, 0.5), 40),
            vkr_percent=min(max(vkr, 0.0), vk * 0.99), pfe_kw=_num(typ.get("Pfe_kW"), 0.0),
            i0_percent=_num(typ.get("i0_pct"), 0.0), name=str(r.get("loc_name")))
        n_traf += 1

    # (interruptores cerrados ya fusionados arriba; los abiertos quedan como nodos
    # separados naturalmente)
    n_sw = sum(1 for r in inter.itertuples()
               if str(getattr(r, "cerrado", "1")).strip() in ("1", "1.0", "True", "true"))

    # --- Cargas / shunts / generadores ---
    for r in cargas.itertuples():
        b = bus_idx.get(str(getattr(r, "barra_con_id", "")))
        if b is None:
            continue
        pp.create_load(net, b, p_mw=_num(r.P_MW, 0.0), q_mvar=_num(r.Q_Mvar, 0.0), name=str(r.loc_name))

    for r in shunts.itertuples():
        b = bus_idx.get(str(getattr(r, "barra_con_id", "")))
        q = _num(getattr(r, "Q_nom_Mvar", 0.0), 0.0)
        if b is None or abs(q) < 1e-9:
            continue
        # tipo capacitor -> inyecta (q<0 en pandapower); reactor -> q>0
        cap = "capacit" in str(getattr(r, "tipo_shunt", "")).lower() or "C" == str(getattr(r, "tipo_shunt", "")).strip()
        pp.create_shunt(net, b, q_mvar=(-abs(q) if cap or q > 0 else abs(q)), p_mw=0.0, name=str(r.loc_name))

    # Síncronos como PV (controlan tensión). Se AGREGAN por barra (la fusión puede
    # juntar varios en un nodo): se suma P y se usa la consigna del de mayor P; así
    # no hay consignas en conflicto en la misma barra. El slack (ref_slack)=ext_grid.
    agg: dict[int, dict] = {}
    slack_bus = None
    for r in gsinc.itertuples():
        b = bus_idx.get(str(getattr(r, "barra_con_id", "")))
        if b is None:
            continue
        p = _num(getattr(r, "P_desp_MW", 0.0), 0.0)
        vm = _num(getattr(r, "U_consigna_pu", 1.0), 1.0)
        vm = vm if 0.9 <= vm <= 1.1 else 1.0
        a = agg.setdefault(b, {"p": 0.0, "vm": vm, "pmax": -1.0})
        a["p"] += p
        if p > a["pmax"]:
            a["pmax"], a["vm"] = p, vm
        if str(getattr(r, "ref_slack", "0")).strip() in ("1", "1.0", "True"):
            slack_bus = b
    for b, a in agg.items():
        if b == slack_bus:
            pp.create_ext_grid(net, b, vm_pu=a["vm"], va_degree=0.0)
        else:
            pp.create_gen(net, b, p_mw=a["p"], vm_pu=a["vm"])
    slack_done = slack_bus is not None
    # VRE / estáticos como PQ (inyección fija)
    for r in gest.itertuples():
        b = bus_idx.get(str(getattr(r, "barra_con_id", "")))
        if b is None:
            continue
        pp.create_sgen(net, b, p_mw=_num(getattr(r, "P_desp_MW", 0.0), 0.0),
                       q_mvar=_num(getattr(r, "Q_desp_Mvar", 0.0), 0.0), name=str(r.loc_name))
    if not slack_done and len(net.bus):
        # respaldo: slack en la barra de mayor tensión
        pp.create_ext_grid(net, int(net.bus.vn_kv.idxmax()), vm_pu=1.0, va_degree=0.0)

    ctx = {"for_by_bus": for_by_bus, "n_lines": n_lines, "n_traf": n_traf,
           "n_sw": n_sw, "n_bus": len(net.bus), "bus_idx": bus_idx}
    return net, ctx

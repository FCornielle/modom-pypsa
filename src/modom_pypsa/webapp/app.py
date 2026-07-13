"""Plataforma GridLab SENI — FastAPI + Jinja + HTMX.

Páginas v1 (enfocado): Dashboard, Proyectos, Corridas (+ detalle), Verificación AC,
Auditoría por equipo. El resto del menú queda "Próximamente". Lee corridas/proyectos
del modelo de artefactos en disco (`data_access`) y los pinta con `charts`.

Levantar:  uvicorn modom_pypsa.webapp.app:app --reload
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import charts
from . import data_access as da

BASE = Path(__file__).resolve().parent
REPO_ROOT = BASE.parents[2]
HOURS = [f"h_{i:02d}" for i in range(1, 25)]

app = FastAPI(title="GridLab SENI")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


@app.on_event("startup")
def _startup() -> None:
    da.ensure_seed_runs()


def ctx(request: Request, **kw) -> dict:
    kw.setdefault("today", _dt.date.today().isoformat())
    kw["request"] = request
    return kw


def view(name: str, context: dict):
    """Render con la firma nueva de Starlette (request primero)."""
    return templates.TemplateResponse(context["request"], name, context)


def _fmt(v, unit="", dec=0):
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    return f"{v:,.{dec}f}{unit}"


MODOM_V_CSV = REPO_ROOT / "data/processed/modom_results/modom_bus_voltage.csv"
MODOM_FLOWS_CSV = REPO_ROOT / "data/processed/modom_results/modom_branch_flows.csv"
LOADS_CSV = REPO_ROOT / "data/processed/loads_time_series/loads_time_series.csv"
PDD_ROOT = REPO_ROOT / "data/processed/pdd"


def _latest_pdd_dir():
    """Directorio del último PDD ingerido (`data/processed/pdd/<YYYY-MM-DD>`) o None.

    La pestaña MODOM·PDD se alimenta de este caso (sin selector: siempre el más reciente);
    si no hay PDD ingerido, los helpers caen al workbook (`modom_results/`)."""
    if not PDD_ROOT.exists():
        return None
    dirs = sorted(d for d in PDD_ROOT.iterdir()
                  if d.is_dir() and (d / "meta.json").exists())
    return dirs[-1] if dirs else None


def _pdd_date() -> str | None:
    d = _latest_pdd_dir()
    if not d:
        return None
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8")).get("pdd_date")
    except Exception:
        return d.name


def _modom_demand() -> pd.Series:
    pdd = _latest_pdd_dir()
    if pdd and (pdd / "demand.csv").exists():
        df = pd.read_csv(pdd / "demand.csv")
        return df.set_index("snapshot_id").p_set_mw.reindex(HOURS)
    if not LOADS_CSV.exists():
        return pd.Series(dtype=float)
    return pd.read_csv(LOADS_CSV).groupby("snapshot_id").p_set_mw.sum().reindex(HOURS)


def _modom_cost_values() -> dict:
    """Costo por barra MODOM = costo marginal del sistema × factor de nodo. Cubre TODAS
    las barras con coordenada; si no hay factor del MODOM se usa 1.0 (sin pérdidas)."""
    mc, lf = _modom_marginal_cost(), _loss_factor_map()
    buses = list(charts._geometry()["coords"].keys())
    return {h: {b: mc.get(h, 0.0) * float(lf.get(b, 1.0) or 1.0) for b in buses}
            for h in HOURS}


def _cost_bus_options():
    """(value, label) de barras para el selector, por nombre. Default: barra de
    referencia PALAMARA (no la generadora)."""
    g = charts._geometry()
    opts = sorted(((b, f"{g['names'].get(b, b)} ({b})") for b in g["coords"]),
                  key=lambda t: t[1])
    nm = {b: g["names"].get(b, "").upper().strip() for b in g["coords"]}
    default = (next((b for b in g["coords"] if nm[b] == "PALAMARA"), None)
               or next((b for b, _ in opts
                        if "PALAMARA" in nm[b] and "GENERAD" not in nm[b]), None)
               or (opts[0][0] if opts else None))
    return opts, default


def _modom_voltage_values() -> dict:
    # El mapa de tensión usa el resultado eléctrico del MODOM (workbook, ~384 barras
    # geolocalizadas). El PDD solo publica ~28 barras monitoradas en p.u. — demasiado
    # disperso para el mapa —, así que su tensión NO se usa aquí (sí su despacho/costo).
    if not MODOM_V_CSV.exists():
        return {}
    mv = pd.read_csv(MODOM_V_CSV, index_col=0)
    # tensión 0/NaN = barra sin resultado → se omite (no se pinta como 0 p.u.)
    return {h: {b: float(mv.at[h, b]) for b in mv.columns
                if pd.notna(mv.at[h, b]) and float(mv.at[h, b]) > 0}
            for h in mv.index}


# --------------------------------------------------------------- MODOM · PDD
MODOM_METRIC_LABELS = {"tension": "Tensión por barra (p.u.)",
                       "costo": "Costo marginal por barra (RD$/MWh)"}


@app.get("/legacy/modom-pdd", response_class=HTMLResponse)
def modom_pdd(request: Request, cost_bus: str | None = None, metric: str = "costo"):
    metric = metric if metric in MODOM_METRIC_LABELS else "costo"
    pdd = _latest_pdd_dir()
    pdd_date = _pdd_date()
    src_tag = f"PDD {pdd_date}" if pdd_date else "workbook"
    dem = _modom_demand()
    disp = _load_dispatch()
    gen = disp.sum(axis=1).reindex(HOURS) if not disp.empty else pd.Series(dtype=float)
    mc = _modom_marginal_cost()
    peak = dem.idxmax() if len(dem.dropna()) else "h_19"
    kpis = [
        ("Demanda pico", _fmt(dem.max(), " MW"), src_tag),
        ("Energía", _fmt(dem.sum(), " MWh"), "demanda 24 h"),
        ("Costo marginal medio", _fmt(pd.Series(mc).mean(), " RD$/MWh"), "del sistema"),
        ("Generación pico", _fmt(gen.max(), " MW"), "despacho"),
        ("Barras con tensión", str(len(_modom_voltage_values().get(peak, {}))), "resultado MODOM"),
        ("Hora pico", peak.replace("h_", ""), "máxima demanda"),
    ]
    # UN solo mapa, métrica elegible (tensión / costo). Escala = mín/máx del DÍA.
    if metric == "costo":
        vals = _modom_cost_values()
    else:
        vals = _modom_voltage_values()
    allv = [v for h in vals for v in vals[h].values() if v == v]
    vmin, vmax = (min(allv), max(allv)) if allv else (None, None)
    modom_map = charts.network_map_div(vals, None, metric=metric, hours=HOURS,
                                       init_hour=peak, div_id="modommap", cmin=vmin,
                                       cmax=vmax, external_controls=True)
    # curva de costo por BARRA (selector, default barra de referencia Palamara)
    bus_opts, default_bus = _cost_bus_options()
    cost_bus = cost_bus or default_bus
    lf = _loss_factor_map()
    _f = lf.get(cost_bus, 1.0)
    factor = float(_f) if (_f == _f and _f) else 1.0   # NaN/0 -> 1.0 (sin pérdidas)
    mc_curve = charts.series_line_div(
        [(h, mc.get(h, 0.0) * factor) for h in HOURS], ylabel="RD$/MWh",
        color="#b0683c", div_id="mccurve", markers=False, grid=False)
    # cargabilidad por rama: del PDD (% nativo por etiqueta) si existe; si no, del workbook
    if pdd and (pdd / "branch_loading.csv").exists():
        bl = pd.read_csv(pdd / "branch_loading.csv", index_col=0)
        load_by_hour = {h: {c: float(bl.at[h, c]) for c in bl.columns
                            if h in bl.index and pd.notna(bl.at[h, c])} for h in HOURS}
        flows_div = charts.ranked_loading_anim_div(load_by_hour, HOURS, peak, "flowsbar")
    else:
        flows = pd.read_csv(MODOM_FLOWS_CSV, index_col=0) if MODOM_FLOWS_CSV.exists() else pd.DataFrame()
        flows_div = charts.modom_flows_anim_div(flows, HOURS, peak, "flowsbar")
    heading = f"MODOM · PDD del {pdd_date} (24 h)" if pdd_date else "MODOM · PDD del día (24 h)"
    # todos los gráficos siguen la hora del ÚNICO mapa: barras (flowsbar) + curva (mccurve)
    sync = charts.anim_controller("modommap", HOURS, ["flowsbar"], ["mccurve"], peak)
    return view("modom_pdd.html", ctx(
        request, active="modom", heading=heading, kpis=kpis,
        modom_mix=charts.modom_mix_div(pdd / "dispatch.csv" if pdd else None),
        modom_map=modom_map, metric=metric, metric_labels=MODOM_METRIC_LABELS,
        mc_curve=mc_curve, peak=peak, bus_opts=bus_opts, cost_bus=cost_bus,
        flows=flows_div, sync=sync))


# --------------------------------------------------------------- PyPSA · Modelo (DC)
@app.get("/legacy/pypsa", response_class=HTMLResponse)
def pypsa_model(request: Request, cost_bus: str | None = None):
    base = charts.base_figures()
    summ = {}
    sp = REPO_ROOT / "results/pypsa_basecase/pypsa_basecase_summary.json"
    if sp.exists():
        import json
        summ = json.loads(sp.read_text(encoding="utf-8"))
    kpis = [
        ("Demanda pico", _fmt(summ.get("peak_load_mw"), " MW"), "despacho DC"),
        ("Energía servida", _fmt(summ.get("served_mwh"), " MWh"), "PyPSA LOPF"),
        ("No suministrada", _fmt(summ.get("unserved_mwh"), " MWh"), "holgura"),
        ("Líneas ≥90%", str(summ.get("lines_above_90pct_peak", "—")), "pico"),
    ]
    # mapa animado de precio nodal del despacho PyPSA (LP energético), análogo al de MODOM
    pvals = _pypsa_cost_values()
    dem = _modom_demand()
    peak = dem.idxmax() if len(dem.dropna()) else "h_19"
    bus_opts, default_bus = _cost_bus_options()
    cost_bus = cost_bus or default_bus
    cost_map = sync_cost = mc_curve = ""
    cong = _pypsa_line_loading_anim(peak)            # líneas DC más cargadas (animado)
    if pvals:
        import numpy as np
        allv = np.array([v for h in pvals for v in pvals[h].values() if v == v])
        cmax = float(np.percentile(allv, 97)) if allv.size else None  # robusto a 1 barra cara
        cost_map = charts.network_map_div(pvals, None, metric="costo_pypsa", hours=HOURS,
                                          init_hour=peak, div_id="pypsacostmap", cmin=0.0,
                                          cmax=cmax, external_controls=True)
        # curva de precio nodal de la barra seleccionada (sigue la hora del mapa)
        ser = [(h, pvals.get(h, {}).get(cost_bus)) for h in HOURS]
        mc_curve = charts.series_line_div(
            [(h, v) for h, v in ser if v is not None], ylabel="RD$/MWh",
            color="#b0683c", div_id="pypsamccurve", markers=False, grid=False)  # mismo estilo que MODOM·PDD
        sync_cost = charts.anim_controller(
            "pypsacostmap", HOURS, ["pypsacong"] if cong else [],
            ["pypsamccurve"] if mc_curve else [], peak)
    return view("pypsa.html", ctx(
        request, active="pypsa", heading="PyPSA · Modelo de despacho (DC)",
        kpis=kpis, base=base, cost_map=cost_map, sync_cost=sync_cost,
        mc_curve=mc_curve, cong=cong, bus_opts=bus_opts, cost_bus=cost_bus))


# --------------------------------------------------------------- Pandapower · AC
def _ac_run(run_id: str | None):
    if run_id:
        return da.get_run(run_id)
    return da.latest_run("iterative") or da.latest_run("ac_verify") or da.latest_run()
MODOM_DISP_CSV = REPO_ROOT / "data/processed/modom_results/modom_generator_dispatch.csv"
NODAL_FACTORS_CSV = REPO_ROOT / "data/processed/modom_results/nodal_factors.csv"
GENERATORS_CSV2 = REPO_ROOT / "data/processed/generators/generators.csv"
# Mapa AC: solo métricas de la verificación AC. El costo marginal NO va aquí (ya se
# refleja en la pestaña PyPSA·Modelo).
METRIC_LABELS = {"tension": "Tensión (pu)", "delta_v": "Δ tensión vs MODOM (pu)"}
_MODOM_MC = {}


def _modom_marginal_cost() -> dict:
    """Costo marginal del sistema por hora desde el despacho MODOM (CVP de la unidad
    flexible más cara: 0 < despacho < Pmax). Es la base del precio fiel al MODOM."""
    if _MODOM_MC:
        return _MODOM_MC
    disp = _load_dispatch()      # PDD vigente si existe; si no, workbook
    if disp.empty or not GENERATORS_CSV2.exists():
        return {}
    g = pd.read_csv(GENERATORS_CSV2)
    pmax = dict(zip(g.generator_id, pd.to_numeric(g.effective_pmax_mw, errors="coerce")))
    cvp = {}
    for _, r in g.iterrows():
        c = pd.to_numeric(r.get("effective_cvp"), errors="coerce")
        if pd.isna(c):
            c = pd.to_numeric(r.get("cvp"), errors="coerce")
        if pd.notna(c) and 0 < float(c) < 50000:   # excluye costos de respaldo
            cvp[r.generator_id] = float(c)
    for h in disp.index:
        prices = [cvp[gid] for gid in disp.columns
                  if gid in cvp and gid in pmax
                  and 1e-3 < float(disp.at[h, gid]) < float(pmax[gid]) - 1e-3]
        _MODOM_MC[h] = max(prices) if prices else 0.0
    return _MODOM_MC


def _loss_factor_map() -> dict:
    pdd = _latest_pdd_dir()
    src = (pdd / "nodal_factors.csv" if (pdd and (pdd / "nodal_factors.csv").exists())
           else NODAL_FACTORS_CSV)
    if not src.exists():
        return {}
    nf = pd.read_csv(src)
    return dict(zip(nf.bus_id_modom, pd.to_numeric(nf.get("factor_retiro"), errors="coerce")))


PYPSA_NODAL_CSV = REPO_ROOT / "results/pypsa_basecase/nodal_prices_by_snapshot.csv"


def _pypsa_cost_values() -> dict:
    """Precio nodal por barra del despacho DC (LP de PyPSA), por hora, desde el caso base.
    A diferencia del costo fiel al MODOM (mc_sistema × factor de nodo), este es el precio
    SOMBRA del LP energético: cae a ~0 a mediodía (excedente VRE gratis). Enmascara los
    precios-sombra de las holguras (±1e6 = unserved/dump) y se queda con las barras con
    coordenada para poder ubicarlas en el mapa."""
    if not PYPSA_NODAL_CSV.exists():
        return {}
    df = pd.read_csv(PYPSA_NODAL_CSV, index_col=0)
    df = df.mask(df.abs() >= 1e5)   # quita VOLL/dump (±1e6), no es precio de energía
    coords = charts._geometry()["coords"]
    out = {}
    for h in HOURS:
        if h not in df.index:
            continue
        row = df.loc[h]
        out[h] = {b: float(row[b]) for b in row.index
                  if b in coords and pd.notna(row[b])}
    return out


PYPSA_LOADING_CSV = REPO_ROOT / "results/pypsa_basecase/line_loading_by_snapshot.csv"


def _pypsa_line_loading_anim(init_hour: str) -> str:
    """Barras animadas RE-RANKEADAS de las líneas DC más cargadas, hora a hora (caso base
    PyPSA). El CSV viene como hora×línea con la carga en fracción (0-1) → %. Cada hora
    muestra el top de ESA hora, de mayor a menor (las líneas entran/salen)."""
    if not PYPSA_LOADING_CSV.exists():
        return ""
    df = pd.read_csv(PYPSA_LOADING_CSV)
    df = df.rename(columns={df.columns[0]: "hour"}).set_index("hour")
    cols = list(df.columns)

    def pretty(n: str) -> str:
        p = str(n).split("__")
        return f"{charts.bus_name(p[0])} → {charts.bus_name(p[1])}" if len(p) >= 2 else str(n)

    lbl = {c: pretty(c) for c in cols}
    load_by_hour = {}
    for h in HOURS:
        if h not in df.index:
            continue
        row = pd.to_numeric(df.loc[h], errors="coerce")
        load_by_hour[h] = {lbl[c]: float(row[c]) * 100.0 for c in cols if pd.notna(row[c])}
    return charts.ranked_loading_anim_div(load_by_hour, HOURS, init_hour, "pypsacong")


def _metric_values(run_id: str, metric: str):
    """Devuelve (values_by_hour {hora:{barra:valor}}, hours) para la métrica elegida."""
    bus = da.run_csv(run_id, "ac_bus_voltages.csv")
    if bus.empty:
        return {}, []
    hours = sorted(bus["hour"].unique()) if "hour" in bus.columns else \
        [da.get_run(run_id).get("summary", {}).get("hour", "h_19")]
    if "hour" not in bus.columns:
        bus = bus.assign(hour=hours[0])

    if metric == "costo":
        # Costo por barra FIEL AL MODOM = costo marginal del sistema (despacho MODOM)
        # × factor de nodo (pérdidas) de la barra. Es la estructura de precios del MODOM
        # y evita el 0 de mediodía del LP energético (excedente VRE gratis).
        mc = _modom_marginal_cost()
        lf = _loss_factor_map()
        buses = [b for b in bus["bus_id_modom"].unique()]
        vals = {}
        for h in hours:
            base = mc.get(h, 0.0)
            vals[h] = {b: base * float(lf.get(b, 1.0) or 1.0) for b in buses
                       if lf.get(b, 1.0) == lf.get(b, 1.0)}
        return vals, hours
    if metric == "delta_v" and MODOM_V_CSV.exists():
        mv = pd.read_csv(MODOM_V_CSV, index_col=0)
        vals = {}
        for h in hours:
            sub = bus[bus["hour"] == h]
            row = mv.loc[h] if h in mv.index else None
            vals[h] = {b: float(v) - float(row[b])
                       for b, v in zip(sub["bus_id_modom"], sub["vm_pu"])
                       if row is not None and b in row.index and pd.notna(row[b]) and pd.notna(v)}
        return vals, hours
    # tensión (por defecto)
    vals = {h: {b: float(v) for b, v in zip(g["bus_id_modom"], g["vm_pu"]) if pd.notna(v)}
            for h, g in bus.groupby("hour")}
    return vals, hours


def _ac_loading_anim(br: pd.DataFrame, hours: list, init_hour: str) -> str:
    """Cargabilidad AC re-rankeada por hora (mismo estilo que MODOM·PDD / PyPSA)."""
    if br.empty or "hour" not in br.columns:
        return ""
    load_by_hour = {h: dict(zip(g["name"], pd.to_numeric(g["loading_percent"], errors="coerce")))
                    for h, g in br.groupby("hour")}
    return charts.ranked_loading_anim_div(load_by_hour, hours, init_hour, "acloading")


@app.get("/legacy/ac", response_class=HTMLResponse)
def ac_page(request: Request, run: str | None = None, metric: str = "tension"):
    r = _ac_run(run)
    if r is None:
        return view("ac.html", ctx(
            request, active="ac", heading="Pandapower · Modelo AC", run=None))
    rid = r["run_id"]
    summ = r.get("summary", {})
    peak = summ.get("hour", "h_19")
    bus = da.run_csv(rid, "ac_bus_voltages.csv")
    br = da.run_csv(rid, "ac_branch_loading.csv")
    vals, hours = _metric_values(rid, metric)
    kpis = [
        ("Demanda (pico)", _fmt(summ.get("demand_mw"), " MW"), "hora " + str(peak).replace("h_", "")),
        ("Pérdidas AC", _fmt(summ.get("losses_mw"), " MW", 1), "AC vs despacho"),
        ("Tensión mín", _fmt(summ.get("v_min"), " pu", 3), "barra más baja"),
        ("Tensión máx", _fmt(summ.get("v_max"), " pu", 3), "barra más alta"),
        ("Violaciones V", f"{(summ.get('n_v_below_090') or 0) + (summ.get('n_v_above_110') or 0)}",
         "<0.9 / >1.1 pu"),
        ("Barras con V", str(summ.get("modom_buses_with_v") or "—"),
         f"de {summ.get('modom_buses_total') or 717}"),
    ]
    multi = "hour" in bus.columns and len(hours) > 1
    nmap = charts.network_map_div(vals, br, metric=metric, hours=hours,
                                  init_hour=peak, div_id="acmap", external_controls=multi)
    if multi:
        profile = charts.voltage_profile_anim_div(bus, hours, peak, "acprofile")
        loading = _ac_loading_anim(br, hours, peak)
        sync = charts.anim_controller("acmap", hours, ["acprofile", "acloading"], [], peak)
    else:
        profile = charts.voltage_profile_div(bus, peak)
        loading = charts.loading_bars_div(br, peak)
        sync = ""
    iters = r.get("iterations", [])
    return view("ac.html", ctx(
        request, active="ac", heading="Pandapower · Modelo AC", run=r,
        summary=summ, fmt=_fmt, metric=metric, metric_labels=METRIC_LABELS, kpis=kpis,
        peak=peak, nmap=nmap, profile=profile, loading=loading, sync=sync,
        iters=iters, convergence=charts.convergence_div(iters),
        dcac=charts.dc_vs_ac_div(da.run_csv(rid, "summary_by_hour.csv"))))


# --------------------------------------------------------------- Auditoría
def _load_dispatch() -> pd.DataFrame:
    pdd = _latest_pdd_dir()
    p = (pdd / "dispatch.csv" if (pdd and (pdd / "dispatch.csv").exists())
         else REPO_ROOT / "data/processed/modom_results/modom_generator_dispatch.csv")
    return pd.read_csv(p, index_col=0) if p.exists() else pd.DataFrame()


@app.get("/legacy/audit", response_class=HTMLResponse)
def audit_page(request: Request, kind: str = "barra", eq: str | None = None,
               hour: str = "h_19"):
    items, _ = _audit_items(kind)
    eq = eq or (items[0][0] if items else None)
    return view("audit.html", ctx(
        request, active="audit", heading="Auditoría por equipo", kind=kind,
        items=items, eq=eq, hours=HOURS, sel_hour=hour,
        panel=_audit_panel(kind, eq, hour)))


@app.get("/legacy/audit/panel", response_class=HTMLResponse)
def audit_panel(request: Request, kind: str, eq: str, hour: str = "h_19"):
    return view("partials/audit_panel.html", ctx(
        request, **_audit_panel(kind, eq, hour)))


def _audit_items(kind: str):
    r = da.latest_run("iterative") or da.latest_run("ac_verify")
    if kind == "barra":
        bus = da.run_csv(r["run_id"], "ac_bus_voltages.csv") if r else pd.DataFrame()
        ids = sorted(bus["bus_id_modom"].dropna().unique()) if "bus_id_modom" in bus else []
        return [(b, f"{charts.bus_name(b)} ({b})") for b in ids], r
    if kind in ("linea", "transformador"):
        br = da.run_csv(r["run_id"], "ac_branch_loading.csv") if r else pd.DataFrame()
        want = "line" if kind == "linea" else "trafo"
        if "kind" in br.columns:
            names = sorted(br[br["kind"] == want]["name"].dropna().unique())
            return [(n, n) for n in names], r
        return [], r
    # generador
    disp = _load_dispatch()
    return [(g, g) for g in list(disp.columns)], r


def _audit_panel(kind: str, eq: str | None, hour: str) -> dict:
    r = da.latest_run("iterative") or da.latest_run("ac_verify")
    rows, series, title, ylabel = [], [], eq or "—", ""
    if eq and r:
        if kind == "barra":
            title = f"{charts.bus_name(eq)} ({eq})"
            ylabel = "Tensión (pu)"
            bus = da.run_csv(r["run_id"], "ac_bus_voltages.csv")
            sub = bus[bus["bus_id_modom"] == eq] if "bus_id_modom" in bus else pd.DataFrame()
            if "hour" in sub.columns:
                series = [(h, _round(v)) for h, v in zip(sub["hour"], sub["vm_pu"])]
                cur = sub[sub["hour"] == hour]
            else:
                cur = sub
            if len(cur):
                row = cur.iloc[0]
                rows = [("Tensión (pu)", _round(row.get("vm_pu"))),
                        ("Ángulo (°)", _round(row.get("va_degree"), 2)),
                        ("kV nominal", _round(row.get("vn_kv"), 1)),
                        ("¿Cruzada?", "Sí" if row.get("matched") else "No")]
        elif kind in ("linea", "transformador"):
            ylabel = "Cargabilidad (%)"
            br = da.run_csv(r["run_id"], "ac_branch_loading.csv")
            sub = br[br["name"] == eq]
            if "hour" in sub.columns:
                series = [(h, _round(v, 1)) for h, v in zip(sub["hour"], sub["loading_percent"])]
                cur = sub[sub["hour"] == hour]
            else:
                cur = sub
            if len(cur):
                row = cur.iloc[0]
                rows = [("Cargabilidad (%)", _round(row.get("loading_percent"), 1)),
                        ("P extremo (MW)", _round(row.get("p_from_mw"), 1)),
                        ("Barra origen", f"{charts.bus_name(row.get('from_w'))}"),
                        ("Barra destino", f"{charts.bus_name(row.get('to_w'))}")]
        else:  # generador
            ylabel = "Despacho (MW)"
            disp = _load_dispatch()
            if eq in disp.columns:
                series = [(h, _round(disp.at[h, eq], 1)) for h in disp.index]
                if hour in disp.index:
                    rows = [("Despacho (MW)", _round(disp.at[hour, eq], 1))]
    chart = charts.series_line_div(series, ylabel=ylabel, sel_hour=hour)
    return {"kind": kind, "eq": title, "rows": rows, "series": series,
            "sel_hour": hour, "chart": chart}


def _round(v, dec=3):
    try:
        f = float(v)
        return round(f, dec) if f == f else "—"
    except (TypeError, ValueError):
        return "—"


# --------------------------------------------------------------- Optimizador MILP
import threading
import time as _time_mod

from fastapi import Form

MILP_DIR = REPO_ROOT / "results/pypsa_milp"
MILP_SUMMARY_JSON = MILP_DIR / "pypsa_milp_summary.json"
MILP_GEN_CSV = MILP_DIR / "generation_by_snapshot.csv"
MILP_FG_CSV = MILP_DIR / "flowgate_utilization_by_snapshot.csv"
MILP_CONSID_JSON = MILP_DIR / "considerations.json"
MILP_OVERRIDES_JSON = MILP_DIR / "overrides.json"
MILP_SCEN_DIR = MILP_DIR / "scenarios"
AC_BUS_CSV = MILP_DIR / "ac_bus_voltages.csv"
AC_BR_CSV = MILP_DIR / "ac_branch_loading.csv"
AC_SUMMARY_JSON = MILP_DIR / "ac_summary.json"
_AC_JOB = {"status": "idle", "started": 0.0, "elapsed": 0.0, "error": None,
           "cancel": False, "phase": "", "done_hours": 0}
_AC_LOCK = threading.Lock()

DEFAULT_CONSID = {"reserves": True, "flowgates": True, "pors": 3.0,
                  "min_sync": 0.0, "gap": 2.0, "time": 300}
# started = epoch al lanzar (para elapsed en vivo); cancel = bandera de cancelación;
# time_limit = para el watchdog "sin respuesta"; phase = etapa legible del solve.
_MILP_JOB = {"status": "idle", "started": 0.0, "elapsed": 0.0, "error": None,
             "cancel": False, "time_limit": 0.0, "phase": ""}
_MILP_LOCK = threading.Lock()
_MILP_MC: dict = {}


def _milp_considerations() -> dict:
    if MILP_CONSID_JSON.exists():
        try:
            return {**DEFAULT_CONSID, **json.loads(MILP_CONSID_JSON.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return dict(DEFAULT_CONSID)


def _milp_summary() -> dict:
    if MILP_SUMMARY_JSON.exists():
        try:
            return json.loads(MILP_SUMMARY_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _milp_marginal_cost() -> dict:
    """Costo marginal del sistema por hora desde el despacho del MILP (CVP de la unidad
    flexible más cara: 0 < despacho < Pmax). Análogo a `_modom_marginal_cost`."""
    if _MILP_MC:
        return _MILP_MC
    if not (MILP_GEN_CSV.exists() and GENERATORS_CSV2.exists()):
        return {}
    disp = pd.read_csv(MILP_GEN_CSV, index_col=0)
    g = pd.read_csv(GENERATORS_CSV2)
    pmax = dict(zip(g.generator_id, pd.to_numeric(g.effective_pmax_mw, errors="coerce")))
    cvp = {}
    for _, r in g.iterrows():
        c = pd.to_numeric(r.get("effective_cvp"), errors="coerce")
        if pd.isna(c):
            c = pd.to_numeric(r.get("cvp"), errors="coerce")
        if pd.notna(c) and 0 < float(c) < 50000:
            cvp[r.generator_id] = float(c)
    for h in disp.index:
        prices = [cvp[gid] for gid in disp.columns
                  if gid in cvp and gid in pmax
                  and 1e-3 < float(disp.at[h, gid]) < float(pmax[gid]) - 1e-3]
        _MILP_MC[str(h)] = max(prices) if prices else 0.0
    return _MILP_MC


def _milp_cost_values() -> dict:
    mc, lf = _milp_marginal_cost(), _loss_factor_map()
    buses = list(charts._geometry()["coords"].keys())
    return {h: {b: mc.get(h, 0.0) * float(lf.get(b, 1.0) or 1.0) for b in buses}
            for h in HOURS}


def _milp_flowgate_kpis() -> list:
    if not MILP_FG_CSV.exists():
        return []
    fg = pd.read_csv(MILP_FG_CSV)
    out = []
    for name, grp in fg.groupby("flowgate_id"):
        up = pd.to_numeric(grp["util_pct"], errors="coerce").dropna()
        out.append((str(name), float(grp["limit_mw"].iloc[0]),
                    float(up.max()) if len(up) else 0.0,
                    int((up >= 99.5).sum())))
    return out


def _modom_version() -> dict:
    """Serie y fecha del MODOM cargado: serial del nombre del workbook + fecha de carga
    (mtime) + fecha del último PDD ingerido. Es el 'sello' de versión de los datos."""
    import re

    wb = list((REPO_ROOT / "data" / "raw").glob("MODOM_*.xlsm"))
    serial, loaded = "—", "—"
    if wb:
        f = wb[0]
        mo = re.search(r"V(\d+)", f.name)
        serial = f"V{mo.group(1)}" if mo else "—"
        loaded = _dt.datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
    return {"serial": serial, "loaded": loaded, "pdd": _pdd_date() or "—"}


def _flowgate_rows(overrides: dict) -> list[dict]:
    """Flowgates con su límite MODOM por defecto y el límite editado vigente (si hay)."""
    p = REPO_ROOT / "data/processed/flowgates/flowgate_limits.csv"
    if not p.exists():
        return []
    fl = pd.read_csv(p)
    ov = (overrides or {}).get("flowgates", {}) or {}
    out = []
    for fg, grp in fl.groupby("flowgate_id"):
        default = float(pd.to_numeric(grp["fmax_mw"], errors="coerce").dropna().iloc[0])
        cur = ov.get(str(fg), {}).get("limit_mw")
        out.append({"id": str(fg), "default": round(default, 0),
                    "current": round(float(cur), 0) if cur not in (None, "") else round(default, 0),
                    "edited": cur not in (None, "")})
    return sorted(out, key=lambda r: r["id"])


def _milp_gen_editor_rows(overrides: dict, limit: int = 40) -> list[dict]:
    """Filas curadas del editor por generador: las de mayor energía en la última corrida,
    con su CVP base, disponibilidad y on/off (aplicando los overrides vigentes)."""
    if not GENERATORS_CSV2.exists():
        return []
    g = pd.read_csv(GENERATORS_CSV2)
    name_by = dict(zip(g.generator_id, g.generator_name.astype(str)))
    cvp_by = {}
    for _, r in g.iterrows():
        c = pd.to_numeric(r.get("effective_cvp"), errors="coerce")
        if pd.isna(c):
            c = pd.to_numeric(r.get("cvp"), errors="coerce")
        cvp_by[r.generator_id] = round(float(c), 1) if pd.notna(c) else None
    # ranking por energía de la última corrida (si existe); si no, por Pmax
    rank = {}
    if MILP_GEN_CSV.exists():
        disp = pd.read_csv(MILP_GEN_CSV, index_col=0)
        for gid in disp.columns:
            rank[gid] = float(pd.to_numeric(disp[gid], errors="coerce").fillna(0).abs().sum())
    pmax_by = dict(zip(g.generator_id, pd.to_numeric(g.effective_pmax_mw, errors="coerce")))
    # candidatos: térmicas/hidro despachables (excluye holguras); enabled en el workbook
    ov_gens = (overrides or {}).get("generators", {}) or {}
    cand = [gid for gid in g.generator_id if str(gid).startswith("G")]
    cand.sort(key=lambda x: (-(rank.get(x, 0.0)), -(pmax_by.get(x, 0) or 0)))
    rows = []
    for gid in cand[:limit]:
        ed = ov_gens.get(gid, {})
        rows.append({
            "gid": gid, "name": name_by.get(gid, gid)[:26],
            "cvp": ed.get("cvp", cvp_by.get(gid)),
            "avail": ed.get("availability_pct", 100),
            "enabled": ed.get("enabled", True) is not False,
            "edited": bool(ed),
        })
    return rows


def _scenario_gen_csv(slug: str) -> Path:
    return MILP_SCEN_DIR / slug / "generation_by_snapshot.csv"


def _current_overrides() -> dict:
    if MILP_OVERRIDES_JSON.exists():
        try:
            return json.loads(MILP_OVERRIDES_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _slug(name: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())
    return "-".join(p for p in s.split("-") if p)[:48] or "escenario"


def _save_scenario(name: str, consid: dict, overrides: dict) -> str:
    """Persiste el escenario (metadatos + copia de los CSV de resultado) y lo devuelve."""
    import shutil

    slug = _slug(name)
    dest = MILP_SCEN_DIR / slug
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "scenario.json").write_text(json.dumps({
        "name": name, "slug": slug, "considerations": consid, "overrides": overrides,
        "summary": _milp_summary(), "saved": _dt.datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for fn in ("generation_by_snapshot.csv", "commitment_by_snapshot.csv",
               "flowgate_utilization_by_snapshot.csv"):
        src = MILP_DIR / fn
        if src.exists():
            shutil.copy2(src, dest / fn)
    return slug


def _list_scenarios() -> list[dict]:
    if not MILP_SCEN_DIR.exists():
        return []
    out = []
    for d in sorted(MILP_SCEN_DIR.iterdir()):
        meta = d / "scenario.json"
        if meta.exists():
            try:
                out.append(json.loads(meta.read_text(encoding="utf-8")))
            except Exception:
                pass
    return sorted(out, key=lambda s: s.get("saved", ""), reverse=True)


def _archive_run(consid: dict, overrides: dict) -> str:
    """Archiva la corrida del MILP en results/runs/milp_<fecha-hora>/ (historial, gitignored).

    Reproduce el guardado 'como al principio': cada corrida queda versionada por fecha con
    su manifiesto (consideraciones + overrides + resumen) y una copia de los CSV de salida.
    """
    import shutil

    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = REPO_ROOT / "results" / "runs" / f"milp_{ts}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps({
        "run_id": f"milp_{ts}", "kind": "milp", "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "modom": _modom_version(), "considerations": consid, "overrides": overrides,
        "summary": _milp_summary(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    for fn in ("generation_by_snapshot.csv", "commitment_by_snapshot.csv",
               "flowgate_utilization_by_snapshot.csv", "nodal_prices_by_snapshot.csv"):
        src = MILP_DIR / fn
        if src.exists():
            shutil.copy2(src, dest / fn)
    return f"milp_{ts}"


def _load_scenario(slug: str) -> dict | None:
    meta = MILP_SCEN_DIR / slug / "scenario.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _run_milp_job(consid: dict, overrides: dict | None = None, name: str = "") -> None:
    """Corre el MILP en background y persiste resultados, consideraciones y overrides.

    TODO va dentro del try (incluida la importación): cualquier fallo pasa a `error`, nunca
    deja el estado en `running` fantasma. Respeta la bandera de cancelación entre etapas.
    """
    import time as _time
    t0 = _time.time()

    def _cancelled() -> bool:
        with _MILP_LOCK:
            return bool(_MILP_JOB.get("cancel"))

    def _phase(p: str) -> None:
        with _MILP_LOCK:
            _MILP_JOB["phase"] = p
            _MILP_JOB["elapsed"] = _time.time() - t0

    try:
        _phase("armando la red")
        from .. import pypsa_milp as milp
        n = milp.build_milp_network(
            with_reserves=bool(consid["reserves"]),
            with_flowgates=bool(consid["flowgates"]),
            pors=float(consid["pors"]) / 100.0,
            min_sync_fraction=float(consid["min_sync"]) / 100.0,
            overrides=overrides)
        if _cancelled():
            raise RuntimeError("__cancelled__")
        _phase("optimizando (MILP)")
        milp.solve_milp(n, mip_rel_gap=float(consid["gap"]) / 100.0,
                        time_limit=float(consid["time"]))
        if _cancelled():
            raise RuntimeError("__cancelled__")
        if n.objective is None:
            raise RuntimeError("El MILP resultó infactible con estas consideraciones "
                               "(no hay solución factible dentro del tiempo límite).")
        _phase("exportando resultados")
        milp.export_results(n)
        MILP_DIR.mkdir(parents=True, exist_ok=True)
        MILP_CONSID_JSON.write_text(json.dumps(consid), encoding="utf-8")
        MILP_OVERRIDES_JSON.write_text(json.dumps(overrides or {}), encoding="utf-8")
        _MILP_MC.clear()
        _archive_run(consid, overrides or {})  # historial versionado por fecha
        if name.strip():
            _save_scenario(name.strip(), consid, overrides or {})
        with _MILP_LOCK:
            _MILP_JOB.update(status="done", elapsed=_time.time() - t0, error=None, phase="")
    except Exception as e:  # noqa: BLE001
        cancelled = str(e) == "__cancelled__"
        with _MILP_LOCK:
            _MILP_JOB.update(
                status="cancelled" if cancelled else "error",
                elapsed=_time.time() - t0, phase="",
                error=None if cancelled else str(e))


# ---- Verificación AC (pandapower) del despacho del MILP: lo que el MODOM hace en DIgSILENT
def _run_ac_job() -> None:
    """Corre el flujo AC (pandapower) sobre el despacho del MILP, hora a hora (24 h).

    Reproduce la verificación que el MODOM hace en DIgSILENT: inyecta NUESTRO despacho en la
    red real del export y calcula tensiones/cargabilidad. Persiste ac_bus_voltages.csv,
    ac_branch_loading.csv y ac_summary.json en results/pypsa_milp/.
    """
    import time as _time
    t0 = _time.time()
    try:
        if not MILP_GEN_CSV.exists():
            raise RuntimeError("Primero corre una optimización MILP.")
        from ..ac_inject import run_ac_modom
        from ..iterative import DEFAULT_EXPORT
        if not Path(DEFAULT_EXPORT).exists():
            raise RuntimeError("Falta el export DIgSILENT en data/external/.")
        gd = pd.read_csv(MILP_GEN_CSV, index_col=0)
        bus_rows, br_rows, summ_rows = [], [], []
        for i, h in enumerate(HOURS, start=1):
            with _AC_LOCK:
                if _AC_JOB.get("cancel"):
                    raise RuntimeError("__cancelled__")
                _AC_JOB.update(phase=f"flujo AC {h}", done_hours=i - 1,
                               elapsed=_time.time() - t0)
            _net, _ctx, bus_res, br_res, summ = run_ac_modom(
                DEFAULT_EXPORT, hour=h, root=str(REPO_ROOT), gen_disp=gd)
            if len(bus_res):
                bus_res = bus_res.assign(hour=h)
                bus_rows.append(bus_res)
            if len(br_res):
                br_rows.append(br_res.assign(hour=h))
            summ_rows.append(summ)
        MILP_DIR.mkdir(parents=True, exist_ok=True)
        if bus_rows:
            pd.concat(bus_rows, ignore_index=True).to_csv(AC_BUS_CSV, index=False)
        if br_rows:
            pd.concat(br_rows, ignore_index=True).to_csv(AC_BR_CSV, index=False)
        conv = sum(1 for s in summ_rows if s.get("converged"))
        AC_SUMMARY_JSON.write_text(json.dumps({
            "hours": summ_rows, "converged_hours": conv, "total_hours": len(HOURS),
        }, ensure_ascii=False), encoding="utf-8")
        with _AC_LOCK:
            _AC_JOB.update(status="done", elapsed=_time.time() - t0, phase="",
                           done_hours=len(HOURS), error=None)
    except Exception as e:  # noqa: BLE001
        cancelled = str(e) == "__cancelled__"
        with _AC_LOCK:
            _AC_JOB.update(status="cancelled" if cancelled else "error",
                           elapsed=_time.time() - t0, phase="",
                           error=None if cancelled else str(e))


def _live_ac_job() -> dict:
    with _AC_LOCK:
        job = dict(_AC_JOB)
    if job["status"] == "running" and job.get("started"):
        job["elapsed"] = max(0.0, _time_mod.time() - float(job["started"]))
    return job


def _ac_summary() -> dict:
    if AC_SUMMARY_JSON.exists():
        try:
            return json.loads(AC_SUMMARY_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _ac_voltage_values() -> dict:
    """{hora: {barra: vm_pu}} desde la verificación AC persistida (para el mapa)."""
    if not AC_BUS_CSV.exists():
        return {}
    bus = pd.read_csv(AC_BUS_CSV)
    if "hour" not in bus.columns:
        return {}
    out = {}
    for h, g in bus.groupby("hour"):
        out[str(h)] = {b: float(v) for b, v in zip(g["bus_id_modom"], g["vm_pu"])
                       if pd.notna(v)}
    return out


@app.post("/milp/verify-ac", response_class=HTMLResponse)
def milp_verify_ac(request: Request):
    with _AC_LOCK:
        if _AC_JOB["status"] == "running":
            return view("partials/milp_ac_status.html", ctx(request, ac=_live_ac_job()))
        _AC_JOB.update(status="running", started=_time_mod.time(), elapsed=0.0,
                       error=None, cancel=False, phase="iniciando", done_hours=0)
    threading.Thread(target=_run_ac_job, daemon=True).start()
    return view("partials/milp_ac_status.html", ctx(request, ac=_live_ac_job()))


@app.get("/milp/ac-status", response_class=HTMLResponse)
def milp_ac_status(request: Request):
    return view("partials/milp_ac_status.html", ctx(request, ac=_live_ac_job()))


@app.get("/", response_class=HTMLResponse)
@app.get("/milp", response_class=HTMLResponse)
def milp_page(request: Request, cost_bus: str | None = None):
    consid = _milp_considerations()
    summ = _milp_summary()
    commit = summ.get("commitment", {}) or {}
    counts = summ.get("counts", {}) or {}
    kpis = [
        ("Costo total", _fmt(summ.get("objective"), " RD$", 0), "objetivo del MILP"),
        ("Demanda pico", _fmt(summ.get("peak_load_mw"), " MW"), "24 h"),
        ("No suministrada", _fmt(summ.get("unserved_mwh"), " MWh"), "holgura"),
        ("Unidades ON (pico)", str(commit.get("units_on_peak", "—")),
         f"de {commit.get('committable_units', '—')} committable"),
        ("Arranques", str(commit.get("total_startups", "—")), "en 24 h"),
        ("Reservas RPF/RSF", f"{counts.get('reserve_rpf_units', '—')}/{counts.get('reserve_rsf_units', '—')}",
         "unidades habilitadas"),
    ]
    # mapa de costo por barra del MILP (mismo componente/estilo que MODOM)
    dem = _modom_demand()
    peak = dem.idxmax() if len(dem.dropna()) else "h_19"
    vals = _milp_cost_values() if MILP_GEN_CSV.exists() else {}
    cost_map = ""
    if vals and any(vals.values()):
        allv = [v for h in vals for v in vals[h].values() if v == v]
        vmax = max(allv) if allv else None
        cost_map = charts.network_map_div(vals, None, metric="costo", hours=HOURS,
                                          init_hour=peak, div_id="milpmap", cmin=0.0,
                                          cmax=vmax, external_controls=True)
    # despacho por tecnología + heatmap de commitment + curva de costo
    mix = charts.milp_mix_div(MILP_GEN_CSV) if MILP_GEN_CSV.exists() else ""
    heat = charts.commitment_heatmap_div(MILP_GEN_CSV) if MILP_GEN_CSV.exists() else ""
    mc = _milp_marginal_cost()
    bus_opts, default_bus = _cost_bus_options()
    cost_bus = cost_bus or default_bus
    lf = _loss_factor_map()
    _f = lf.get(cost_bus, 1.0)
    factor = float(_f) if (_f == _f and _f) else 1.0
    mc_curve = charts.series_line_div(
        [(h, mc.get(h, 0.0) * factor) for h in HOURS], ylabel="RD$/MWh",
        color="#b0683c", div_id="milpmccurve", markers=False, grid=False)
    sync = charts.anim_controller("milpmap", HOURS, [], ["milpmccurve"], peak) if cost_map else ""
    fgk = _milp_flowgate_kpis()
    overrides = _current_overrides()
    # curva de demanda del SENI (24 h), escalada por el override de demanda si lo hay
    dpct = float((overrides.get("global", {}) or {}).get("demand_pct", 100) or 100) / 100.0
    dem_curve = charts.series_line_div(
        [(h, float(dem.get(h, 0.0)) * dpct) for h in HOURS if pd.notna(dem.get(h))],
        ylabel="MW", color="#2563eb", div_id="milpdemand", markers=False, grid=False)
    # --- Verificación AC (pandapower) del despacho del MILP, si existe ---
    ac_sum = _ac_summary()
    ac_map = ac_loading = ac_sync = ""
    ac_kpis: list = []
    ac_vals = _ac_voltage_values()
    if ac_vals and any(ac_vals.values()):
        acbr = pd.read_csv(AC_BR_CSV) if AC_BR_CSV.exists() else None
        ac_map = charts.network_map_div(ac_vals, acbr, metric="tension", hours=HOURS,
                                        init_hour=peak, div_id="acmap2",
                                        external_controls=True)
        if acbr is not None and "hour" in acbr.columns:
            lbh = {h: dict(zip(gp["name"], pd.to_numeric(gp["loading_percent"], errors="coerce")))
                   for h, gp in acbr.groupby("hour")}
            ac_loading = charts.ranked_loading_anim_div(lbh, HOURS, peak, "acload2")
        ac_sync = charts.anim_controller("acmap2", HOURS, ["acload2"] if ac_loading else [], [], peak)
        hrs = ac_sum.get("hours", [])
        pk = next((s for s in hrs if s.get("hour") == peak), (hrs[0] if hrs else {}))
        ac_kpis = [
            ("Convergencia", f"{ac_sum.get('converged_hours', 0)}/{ac_sum.get('total_hours', 24)}", "horas AC"),
            ("Pérdidas AC", _fmt(pk.get("losses_mw"), " MW", 1), f"hora {str(peak).replace('h_', '')}"),
            ("Tensión mín", _fmt(pk.get("v_min"), " pu", 3), "barra más baja"),
            ("Tensión máx", _fmt(pk.get("v_max"), " pu", 3), "barra más alta"),
            ("Violaciones V", str((pk.get("n_v_below_090") or 0) + (pk.get("n_v_above_110") or 0)), "<0.9 / >1.1 pu"),
            ("Barras con V", str(pk.get("modom_buses_with_v") or "—"), f"de {pk.get('modom_buses_total') or 717}"),
        ]
    return view("milp.html", ctx(
        request, active="milp", heading="Optimizador MILP · MODOM completo",
        consid=consid, kpis=kpis, cost_map=cost_map, mix=mix, heat=heat,
        mc_curve=mc_curve, sync=sync, bus_opts=bus_opts, cost_bus=cost_bus,
        flowgates=fgk, has_result=bool(summ), job=_live_job(), peak=peak,
        oglobal=overrides.get("global", {}) or {}, dem_curve=dem_curve,
        version=_modom_version(), fg_rows=_flowgate_rows(overrides),
        gen_rows=_milp_gen_editor_rows(overrides), scenarios=_list_scenarios(),
        n_overrides=_n_overrides(overrides),
        ac_map=ac_map, ac_loading=ac_loading, ac_sync=ac_sync, ac_kpis=ac_kpis,
        has_ac=bool(ac_vals), ac_job=_live_ac_job()))


def _n_overrides(overrides: dict) -> int:
    o = overrides or {}
    return len(o.get("generators", {})) + len([k for k, v in (o.get("global", {}) or {}).items()
                                               if v not in (None, "", 100, 100.0)])


@app.get("/milp/compare", response_class=HTMLResponse)
def milp_compare(request: Request, a: str, b: str):
    sa, sb = _load_scenario(a), _load_scenario(b)
    if not sa or not sb:
        return view("milp_compare.html", ctx(
            request, active="milp", heading="Comparar escenarios", ok=False))
    ca = (sa.get("summary") or {}); cb = (sb.get("summary") or {})
    cma = ca.get("commitment", {}) or {}; cmb = cb.get("commitment", {}) or {}

    def _d(x, y, unit="", dec=0):
        if x is None or y is None:
            return "—"
        return f"{(y - x):+,.{dec}f}{unit}"

    deltas = [
        ("Costo total", _fmt(ca.get("objective"), " RD$"), _fmt(cb.get("objective"), " RD$"),
         _d(ca.get("objective"), cb.get("objective"), " RD$")),
        ("No suministrada", _fmt(ca.get("unserved_mwh"), " MWh"), _fmt(cb.get("unserved_mwh"), " MWh"),
         _d(ca.get("unserved_mwh"), cb.get("unserved_mwh"), " MWh", 1)),
        ("Arranques", str(cma.get("total_startups", "—")), str(cmb.get("total_startups", "—")),
         _d(cma.get("total_startups"), cmb.get("total_startups"))),
        ("Unidades ON (pico)", str(cma.get("units_on_peak", "—")), str(cmb.get("units_on_peak", "—")),
         _d(cma.get("units_on_peak"), cmb.get("units_on_peak"))),
    ]
    mix_a = charts.milp_mix_div(_scenario_gen_csv(a)) if _scenario_gen_csv(a).exists() else ""
    mix_b = charts.milp_mix_div(_scenario_gen_csv(b)) if _scenario_gen_csv(b).exists() else ""
    movers = _scenario_gen_movers(a, b)
    return view("milp_compare.html", ctx(
        request, active="milp", heading="Comparar escenarios", ok=True,
        sa=sa, sb=sb, deltas=deltas, mix_a=mix_a, mix_b=mix_b, movers=movers))


def _scenario_gen_movers(a: str, b: str, top: int = 12) -> list:
    """Generadores con mayor cambio de energía diaria entre dos escenarios (A→B)."""
    pa, pb = _scenario_gen_csv(a), _scenario_gen_csv(b)
    if not (pa.exists() and pb.exists()):
        return []
    da = pd.read_csv(pa, index_col=0).sum()
    db = pd.read_csv(pb, index_col=0).sum()
    names = {}
    if GENERATORS_CSV2.exists():
        g = pd.read_csv(GENERATORS_CSV2)
        names = dict(zip(g.generator_id, g.generator_name.astype(str)))
    gids = [c for c in set(da.index) | set(db.index) if str(c).startswith("G")]
    rows = []
    for gid in gids:
        ea, eb = float(da.get(gid, 0.0)), float(db.get(gid, 0.0))
        if abs(eb - ea) > 1.0:
            rows.append((names.get(gid, gid)[:26], round(ea, 0), round(eb, 0), round(eb - ea, 0)))
    rows.sort(key=lambda t: -abs(t[3]))
    return rows[:top]


@app.post("/milp/run", response_class=HTMLResponse)
def milp_run(request: Request, reserves: str = Form("off"), flowgates: str = Form("off"),
             pors: float = Form(3.0), min_sync: float = Form(0.0),
             gap: float = Form(2.0), time: int = Form(300),
             overrides: str = Form("{}"), scenario_name: str = Form("")):
    try:
        ov = json.loads(overrides) if overrides else {}
        if not isinstance(ov, dict):
            ov = {}
    except Exception:
        ov = {}
    with _MILP_LOCK:
        if _MILP_JOB["status"] == "running":
            return view("partials/milp_status.html", ctx(request, job=_live_job()))
        consid = {"reserves": reserves in ("on", "true", "1", "yes"),
                  "flowgates": flowgates in ("on", "true", "1", "yes"),
                  "pors": float(pors), "min_sync": float(min_sync),
                  "gap": float(gap), "time": int(time)}
        _MILP_JOB.update(status="running", started=_time_mod.time(), elapsed=0.0,
                         error=None, cancel=False, time_limit=float(time),
                         phase="armando la red")
    threading.Thread(target=_run_milp_job, args=(consid, ov, scenario_name),
                     daemon=True).start()
    return view("partials/milp_status.html", ctx(request, job=_live_job()))


def _live_job() -> dict:
    """Snapshot del job con `elapsed` calculado en vivo + watchdog de 'sin respuesta'."""
    with _MILP_LOCK:
        job = dict(_MILP_JOB)
    if job["status"] == "running" and job.get("started"):
        job["elapsed"] = max(0.0, _time_mod.time() - float(job["started"]))
        # watchdog: si pasó el time_limit + 45 s sin terminar, se declara sin respuesta.
        if job["elapsed"] > float(job.get("time_limit") or 300.0) + 45.0:
            with _MILP_LOCK:
                _MILP_JOB.update(status="error", error="El solver no respondió a tiempo.")
            job = dict(_MILP_JOB)
    return job


@app.get("/milp/status", response_class=HTMLResponse)
def milp_status(request: Request):
    return view("partials/milp_status.html", ctx(request, job=_live_job()))


@app.post("/milp/cancel", response_class=HTMLResponse)
def milp_cancel(request: Request):
    with _MILP_LOCK:
        if _MILP_JOB["status"] == "running":
            _MILP_JOB["cancel"] = True
            _MILP_JOB["phase"] = "cancelando…"
    return view("partials/milp_status.html", ctx(request, job=_live_job()))


@app.post("/milp/scenario/save", response_class=HTMLResponse)
def milp_scenario_save(request: Request, scenario_name: str = Form("")):
    """Guarda la corrida ACTUAL como escenario con nombre (sin re-optimizar)."""
    name = scenario_name.strip() or f"escenario-{_dt.datetime.now():%H%M%S}"
    if MILP_SUMMARY_JSON.exists():
        _save_scenario(name, _milp_considerations(), _current_overrides())
    return view("partials/milp_scenarios.html", ctx(request, scenarios=_list_scenarios()))


@app.get("/milp/inspect", response_class=HTMLResponse)
def milp_inspect(request: Request, bus: str):
    """Panel inspector de una barra: nombre/kV, curva de costo 24 h y generadores en ella."""
    geo = charts._geometry()
    name = geo["names"].get(bus, bus)
    kv = geo["bus_kv"].get(bus)
    mc, lf = _milp_marginal_cost(), _loss_factor_map()
    _f = lf.get(bus, 1.0)
    factor = float(_f) if (_f == _f and _f) else 1.0
    curve = charts.series_line_div([(h, mc.get(h, 0.0) * factor) for h in HOURS],
                                   ylabel="RD$/MWh", color="#b0683c",
                                   div_id="inspcurve", markers=False, grid=False)
    gens = []
    if MILP_GEN_CSV.exists() and GENERATORS_CSV2.exists():
        g = pd.read_csv(GENERATORS_CSV2)
        at_bus = g[g["bus_id"] == bus]
        disp = pd.read_csv(MILP_GEN_CSV, index_col=0)
        for _, r in at_bus.iterrows():
            gid = r["generator_id"]
            if gid in disp.columns:
                e = float(pd.to_numeric(disp[gid], errors="coerce").fillna(0).sum())
                if e > 1e-3:
                    gens.append((str(r.get("generator_name") or gid), round(e, 1)))
    gens.sort(key=lambda t: -t[1])
    return view("partials/milp_inspect.html", ctx(
        request, bus=bus, bus_name=name, bus_kv=_round(kv, 1), curve=curve,
        gens=gens[:12], factor=round(factor, 4)))


# --------------------------------------------------------------- Metodología
@app.get("/metodologia", response_class=HTMLResponse)
def metodologia(request: Request):
    return view("metodologia.html", ctx(
        request, active="metodologia", heading="Metodología y supuestos",
        modom_mix=charts.modom_mix_div()))


# --------------------------------------------------------------- Próximamente
@app.get("/coming/{name}", response_class=HTMLResponse)
def coming(request: Request, name: str):
    return view("coming_soon.html", ctx(
        request, active="", heading=name.capitalize(), name=name.capitalize()))

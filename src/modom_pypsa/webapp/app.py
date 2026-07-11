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


@app.get("/", response_class=HTMLResponse)
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
@app.get("/pypsa", response_class=HTMLResponse)
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


@app.get("/ac", response_class=HTMLResponse)
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


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, kind: str = "barra", eq: str | None = None,
               hour: str = "h_19"):
    items, _ = _audit_items(kind)
    eq = eq or (items[0][0] if items else None)
    return view("audit.html", ctx(
        request, active="audit", heading="Auditoría por equipo", kind=kind,
        items=items, eq=eq, hours=HOURS, sel_hour=hour,
        panel=_audit_panel(kind, eq, hour)))


@app.get("/audit/panel", response_class=HTMLResponse)
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

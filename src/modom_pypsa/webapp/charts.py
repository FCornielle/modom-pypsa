"""Constructores de gráficos Plotly para la plataforma (devuelven divs HTML embebibles).

Gráficos AC y de convergencia del lazo iterativo, más reuso del caso base
(`dashboard.build_figures`) para la página principal. Plotly.js se carga una sola vez
en la plantilla base (CDN), por eso aquí `include_plotlyjs=False`.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
COORDS_CSV = REPO_ROOT / "data/external/buses_with_coords.csv"
BUSES_CSV = REPO_ROOT / "data/processed/buses/buses.csv"
LINES_CSV = REPO_ROOT / "data/processed/pypsa_branch_components/lines_v1.csv"
TRAFOS_CSV = REPO_ROOT / "data/processed/pypsa_branch_components/transformers_v1.csv"

# niveles de tensión: etiqueta + color (para leyenda con toggles, como antes)
VOLT_LEVELS = [(345, "LT 345 kV", "#7c3aed"), (230, "LT 230 kV", "#0ea5e9"),
               (138, "LT 138 kV", "#10b981"), (69, "LT 69 kV", "#f59e0b")]
VOLT_OTHER = ("LT otra", "#94a3b8")


def _volt_bucket(kv):
    try:
        kv = float(kv)
    except (TypeError, ValueError):
        return VOLT_OTHER
    for std, lbl, col in VOLT_LEVELS:
        if abs(kv - std) < 1.0:
            return (lbl, col)
    return VOLT_OTHER


_GEO = {}


def _geometry() -> dict:
    """Coordenadas, nombres, tensión por barra y segmentos de línea (cacheado)."""
    if _GEO:
        return _GEO
    coords, names, bus_kv, segs = {}, {}, {}, []
    if COORDS_CSV.exists():
        c = pd.read_csv(COORDS_CSV)
        c = c[pd.to_numeric(c["lat"], errors="coerce").notna()]
        coords = {str(r.bus_id_modom): (float(r.lat), float(r.lon)) for r in c.itertuples()}
    if BUSES_CSV.exists():
        b = pd.read_csv(BUSES_CSV)
        for r in b.itertuples():
            nm = str(getattr(r, "bus_name", "") or "").strip()
            names[str(r.bus_id_modom)] = nm if nm and nm.lower() != "nan" else str(r.bus_id_modom)
            bus_kv[str(r.bus_id_modom)] = pd.to_numeric(getattr(r, "v_nom_kv", None), errors="coerce")
    frames = [p for p in (LINES_CSV, TRAFOS_CSV) if p.exists()]
    if frames:
        br = pd.concat([pd.read_csv(p) for p in frames], ignore_index=True)
        for r in br.itertuples():
            b0, b1 = str(r.bus0), str(r.bus1)
            if b0 in coords and b1 in coords:
                kv = pd.to_numeric(getattr(r, "v_nom_bus0_kv", None), errors="coerce")
                segs.append((coords[b0], coords[b1], _volt_bucket(kv), str(r.name)))
    _GEO.update(coords=coords, names=names, bus_kv=bus_kv, segs=segs)
    return _GEO

# Paleta GridLab (clara)
ACCENT = "#2563EB"
GOOD = "#16a34a"
WARN = "#f59e0b"
BAD = "#dc2626"
GRID = "#e5e7eb"
INK = "#0f172a"
MUTED = "#64748b"

_LAYOUT = dict(
    template="plotly_white", margin=dict(l=40, r=16, t=30, b=36),
    font=dict(family="Inter,Segoe UI,Arial", size=12, color=INK),
    paper_bgcolor="white", plot_bgcolor="white",
)


def _div(fig, div_id: str | None = None, height: int = 320) -> str:
    import plotly.io as pio

    fig.update_layout(height=height, **_LAYOUT)
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id,
                       config={"displayModeBar": False, "responsive": True})


def _hnum(h) -> int:
    """'h_07' -> 7 (la hora como número para el eje, como antes)."""
    try:
        return int(str(h).replace("h_", ""))
    except (TypeError, ValueError):
        return 0


def _empty(msg: str = "Sin datos") -> str:
    return f'<div class="chart-empty">{msg}</div>'


# ----------------------------------------------------------- AC: mapa de tensión
def voltage_map_div(bus_voltages: pd.DataFrame, hour: str | None = None,
                    branch_loading: pd.DataFrame | None = None,
                    height: int = 460) -> str:
    """Mapa: red de transmisión (líneas por nivel de tensión) + barras por V (nombres)."""
    import plotly.graph_objects as go
    import plotly.io as pio

    geo = _geometry()
    if bus_voltages.empty or not geo["coords"]:
        return _empty("Sin tensiones / coordenadas")
    df = bus_voltages.copy()
    if hour and "hour" in df.columns:
        df = df[df["hour"] == hour]
    df = df[df["vm_pu"].notna()]
    coords, names, segs = geo["coords"], geo["names"], geo["segs"]

    # líneas sobrecargadas de ESTA hora (rojo)
    overloaded = set()
    if branch_loading is not None and not branch_loading.empty:
        bl = branch_loading
        if hour and "hour" in bl.columns:
            bl = bl[bl["hour"] == hour]
        overloaded = set(bl[bl["loading_percent"] > 90]["name"]) if "name" in bl else set()

    fig = go.Figure()
    # red de transmisión, agrupada por nivel de tensión (leyenda con toggles)
    by_lvl: dict[tuple, list] = {}
    red_lat, red_lon = [], []
    for (a, b, bucket, name) in segs:
        if name in overloaded:
            red_lat += [a[0], b[0], None]; red_lon += [a[1], b[1], None]
            continue
        d = by_lvl.setdefault(bucket, [[], []])
        d[0] += [a[0], b[0], None]; d[1] += [a[1], b[1], None]
    for (lbl, col), (la, lo) in sorted(by_lvl.items(), key=lambda kv: kv[0][0]):
        fig.add_trace(go.Scattermapbox(lat=la, lon=lo, mode="lines", name=lbl,
            line=dict(width=1.6, color=col), hoverinfo="skip"))
    if red_lat:
        fig.add_trace(go.Scattermapbox(lat=red_lat, lon=red_lon, mode="lines",
            line=dict(width=3, color=BAD), name="≥90%", hoverinfo="skip"))

    # barras coloreadas por tensión, con NOMBRE en el hover
    lat = [coords[str(b)][0] for b in df["bus_id_modom"] if str(b) in coords]
    lon = [coords[str(b)][1] for b in df["bus_id_modom"] if str(b) in coords]
    vv = [v for b, v in zip(df["bus_id_modom"], df["vm_pu"]) if str(b) in coords]
    txt = [f"<b>{names.get(str(b), b)}</b><br>{b} · {v:.3f} pu"
           for b, v in zip(df["bus_id_modom"], df["vm_pu"]) if str(b) in coords]
    fig.add_trace(go.Scattermapbox(lat=lat, lon=lon, mode="markers",
        marker=dict(size=8, color=vv, colorscale="RdYlGn", cmin=0.90, cmax=1.10,
                    showscale=True, colorbar=dict(title="V pu", thickness=12)),
        text=txt, hoverinfo="text", showlegend=False))
    fig.update_layout(mapbox=dict(style="carto-positron",
                                  center=dict(lat=18.9, lon=-70.4), zoom=7.2),
                      margin=dict(l=0, r=0, t=0, b=0), height=height,
                      legend=dict(x=0, y=1, bgcolor="rgba(255,255,255,.7)"))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config={"scrollZoom": True, "displaylogo": False,
                               "responsive": True})


METRICS = {
    "tension": dict(label="Tensión (pu)", scale="RdYlGn", cmin=0.90, cmax=1.10, dec=3),
    "costo": dict(label="Costo marginal MODOM (RD$/MWh)", scale="Turbo", cmin=7000, cmax=11500, dec=0),
    "delta_v": dict(label="ΔV vs MODOM (pu)", scale="RdBu", cmin=-0.06, cmax=0.06, dec=3),
}


def network_map_div(values_by_hour: dict, branch_loading: pd.DataFrame | None,
                    metric: str = "tension", hours: list | None = None,
                    init_hour: str | None = None, height: int = 620,
                    div_id: str | None = None, cmin: float | None = None,
                    cmax: float | None = None, external_controls: bool = False) -> str:
    """Mapa ANIMADO 24h: red por nivel de tensión (leyenda toggle) + barras coloreadas
    por la métrica elegida (tensión / costo marginal / Δ vs MODOM). Play + scroll-zoom."""
    import plotly.graph_objects as go
    import plotly.io as pio

    geo = _geometry()
    coords, names, bus_kv, segs = geo["coords"], geo["names"], geo["bus_kv"], geo["segs"]
    hours = hours or sorted(values_by_hour.keys())
    if not hours or not coords:
        return _empty("Sin datos para el mapa")
    init_hour = init_hour if init_hour in hours else hours[0]
    m = dict(METRICS.get(metric, METRICS["tension"]))
    if cmin is not None:
        m["cmin"] = cmin
    if cmax is not None:
        m["cmax"] = cmax

    # congestión por hora (líneas ≥90%)
    cong = {h: set() for h in hours}
    if branch_loading is not None and not branch_loading.empty and "hour" in branch_loading.columns:
        for h in hours:
            sub = branch_loading[(branch_loading.hour == h) & (branch_loading.loading_percent > 90)]
            cong[h] = set(sub["name"])

    fig = go.Figure()
    # --- líneas por nivel de tensión (estáticas, leyenda con toggle) ---
    by_lvl: dict[tuple, list] = {}
    seg_names: list = []
    for (a, b, bucket, name) in segs:
        d = by_lvl.setdefault(bucket, [[], []])
        d[0] += [a[0], b[0], None]; d[1] += [a[1], b[1], None]
        seg_names.append((bucket, a, b, name))
    for (lbl, col), (la, lo) in sorted(by_lvl.items(), key=lambda kv: kv[0][0]):
        fig.add_trace(go.Scattermapbox(lat=la, lon=lo, mode="lines", name=lbl,
            line=dict(width=1.6, color=col), hoverinfo="skip"))
    n_lines = len(fig.data)

    # --- congestión (dinámica) ---
    def cong_xy(h):
        la, lo = [], []
        for (_, a, b, name) in seg_names:
            if name in cong[h]:
                la += [a[0], b[0], None]; lo += [a[1], b[1], None]
        return la, lo
    cla, clo = cong_xy(init_hour)
    fig.add_trace(go.Scattermapbox(lat=cla, lon=clo, mode="lines", name="≥90% carga",
        line=dict(width=3.5, color=BAD), hoverinfo="skip"))
    idx_cong = len(fig.data) - 1

    # --- barras por nivel de tensión (marcadores, color = métrica) ---
    buckets: dict[tuple, list] = {}
    for b in coords:
        buckets.setdefault(_volt_bucket(bus_kv.get(b)), []).append(b)
    order = sorted(buckets.keys(), key=lambda k: k[0])

    nan = float("nan")

    def colors_text(bs, h):
        vals = values_by_hour.get(h, {})
        col, txt = [], []
        for b in bs:
            v = vals.get(b)
            col.append(float(v) if isinstance(v, (int, float)) else nan)
            vs = f"{v:.{m['dec']}f}" if isinstance(v, (int, float)) else "—"
            txt.append(f"<b>{names.get(b, b)}</b><br>{b}<br>{m['label']}: {vs}")
        return col, txt

    bus_trace_idx = []
    for bucket in order:
        bs = buckets[bucket]
        col, txt = colors_text(bs, init_hour)
        fig.add_trace(go.Scattermapbox(
            lat=[coords[b][0] for b in bs], lon=[coords[b][1] for b in bs],
            mode="markers", name=f"Barras {bucket[0].split()[-2]} {bucket[0].split()[-1]}"
                 if len(bucket[0].split()) >= 3 else f"Barras {bucket[0]}",
            marker=dict(size=8, color=col, coloraxis="coloraxis"),
            text=txt, hovertemplate="%{text}<extra></extra>", legendrank=2000 + bucket[0].__hash__() % 100))
        bus_trace_idx.append(len(fig.data) - 1)

    # --- frames por hora (actualizan congestión + colores/text de barras) ---
    frames = []
    for h in hours:
        fdata = []
        la, lo = cong_xy(h)
        fdata.append(go.Scattermapbox(lat=la, lon=lo))
        for bucket in order:
            col, txt = colors_text(buckets[bucket], h)
            fdata.append(go.Scattermapbox(marker=dict(color=col), text=txt))
        frames.append(go.Frame(name=h, data=fdata, traces=[idx_cong] + bus_trace_idx))
    fig.frames = frames

    steps = [dict(method="animate", label=h.replace("h_", ""),
                  args=[[h], dict(mode="immediate", frame=dict(duration=0, redraw=True),
                                  transition=dict(duration=0))]) for h in hours]
    fig.update_layout(
        mapbox=dict(style="carto-positron", center=dict(lat=18.9, lon=-70.4), zoom=7),
        margin=dict(l=0, r=0, t=0, b=0), height=height,
        coloraxis=dict(colorscale=m["scale"], cmin=m["cmin"], cmax=m["cmax"],
                       colorbar=dict(title=m["label"].split(" (")[0], thickness=13, len=0.6, x=0.99)),
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,.88)", bordercolor=GRID,
                    borderwidth=1, font=dict(size=11)),
        sliders=[dict(active=hours.index(init_hour), x=0.05, y=0, len=0.92,
                      ticklen=5, tickwidth=1, tickcolor=MUTED, minorticklen=0,
                      currentvalue=dict(prefix="Hora "), steps=steps)])
    if not external_controls:
        fig.update_layout(updatemenus=[dict(
            type="buttons", direction="left", x=0.0, y=0, xanchor="right",
            yanchor="bottom", showactive=False, buttons=[
                dict(label="▶", method="animate", args=[None, dict(
                    frame=dict(duration=800, redraw=True), fromcurrent=True,
                    transition=dict(duration=0))]),
                dict(label="⏸", method="animate", args=[[None], dict(mode="immediate",
                    frame=dict(duration=0, redraw=False))])])])
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id,
                       config={"scrollZoom": True, "displaylogo": False, "responsive": True})


def bus_name(w: str) -> str:
    """Nombre legible de una barra MODOM (W-code -> nombre)."""
    return _geometry()["names"].get(str(w), str(w))


# ----------------------------------------------------------- auditoría: serie 24h
def series_line_div(series, ylabel: str = "", sel_hour: str | None = None,
                    color: str = ACCENT, div_id: str | None = None,
                    markers: bool = True, grid: bool = False) -> str:
    """Gráfico de línea de una serie 24h [(hora, valor)]. `markers`/`grid` opcionales."""
    import plotly.graph_objects as go

    pts = [(h, v) for h, v in (series or []) if isinstance(v, (int, float))]
    if not pts:
        return _empty("Sin serie numérica")
    xs = [_hnum(h) for h, _ in pts]
    ys = [v for _, v in pts]
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers" if markers else "lines",
                               line=dict(color=color, width=2.5),
                               marker=dict(size=6), fill="tozeroy",
                               fillcolor="rgba(176,104,60,.08)"))
    if markers and sel_hour is not None and _hnum(sel_hour) in xs:
        i = xs.index(_hnum(sel_hour))
        fig.add_trace(go.Scatter(x=[xs[i]], y=[ys[i]], mode="markers",
                                 marker=dict(size=12, color=WARN), showlegend=False))
    fig.update_yaxes(title=ylabel, showgrid=grid, gridcolor=GRID)
    fig.update_xaxes(title="Hora", showgrid=grid, gridcolor=GRID, dtick=2)
    return _div(fig, div_id=div_id, height=280)


# ----------------------------------------------------------- AC: cargabilidad
def loading_bars_div(branch_loading: pd.DataFrame, hour: str | None = None,
                     top: int = 15) -> str:
    import plotly.graph_objects as go

    if branch_loading.empty:
        return _empty()
    df = branch_loading.copy()
    if hour and "hour" in df.columns:
        df = df[df["hour"] == hour]
    df = df.sort_values("loading_percent", ascending=False).head(top).iloc[::-1]
    colors = [BAD if v > 100 else WARN if v > 90 else ACCENT for v in df["loading_percent"]]
    fig = go.Figure(go.Bar(
        x=df["loading_percent"], y=df["name"], orientation="h",
        marker_color=colors, text=[f"{v:.0f}%" for v in df["loading_percent"]],
        textposition="auto"))
    fig.update_xaxes(title="Cargabilidad %", gridcolor=GRID)
    fig.update_yaxes(automargin=True)
    return _div(fig, height=420)


# --------------------------------------- AC animados (sincronizan con el mapa)
def _anim_html(fig, div_id, height, margin_l=None):
    import plotly.io as pio

    fig.update_layout(height=height, **_LAYOUT)
    if margin_l is not None:                # margen fijo: ejes no se mueven entre frames
        fig.update_layout(margin=dict(l=margin_l, r=16, t=30, b=36))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id,
                       config={"displayModeBar": False, "responsive": True})


def voltage_profile_anim_div(bus_voltages: pd.DataFrame, hours: list,
                             init_hour: str, div_id: str) -> str:
    """Perfil de tensión animado por hora (frames). Lo mueve el mapa vía JS."""
    import plotly.graph_objects as go

    if bus_voltages.empty or "hour" not in bus_voltages.columns:
        return _empty()

    def sorted_vals(h):
        v = bus_voltages[bus_voltages.hour == h]["vm_pu"].dropna().sort_values()
        return list(v)

    def bar(h):
        v = sorted_vals(h)
        colors = [BAD if x < 0.9 or x > 1.1 else GOOD for x in v]
        return go.Bar(x=list(range(len(v))), y=v, marker_color=colors)
    fig = go.Figure(bar(init_hour))
    fig.frames = [go.Frame(name=h, data=[bar(h)]) for h in hours]
    fig.add_hline(y=0.9, line_dash="dot", line_color=BAD)
    fig.add_hline(y=1.1, line_dash="dot", line_color=BAD)
    fig.update_yaxes(title="V pu", range=[0.7, 1.15], gridcolor=GRID)
    fig.update_xaxes(title="Barras (ordenadas por tensión)", showticklabels=False)
    return _anim_html(fig, div_id, 300)


def loading_bars_anim_div(branch_loading: pd.DataFrame, hours: list,
                          init_hour: str, div_id: str, top: int = 15) -> str:
    """Cargabilidad animada por hora de un set FIJO de ramas (top por carga máxima)."""
    import plotly.graph_objects as go

    if branch_loading.empty or "hour" not in branch_loading.columns:
        return _empty()
    peak = (branch_loading.groupby("name")["loading_percent"].max()
            .sort_values(ascending=False).head(top).index.tolist())
    peak = peak[::-1]                                  # menor arriba en barh
    by_hour = {h: dict(zip(g["name"], g["loading_percent"]))
               for h, g in branch_loading.groupby("hour")}

    def xy(h):
        vals = [by_hour.get(h, {}).get(n, 0.0) for n in peak]
        colors = [BAD if v > 100 else WARN if v > 90 else ACCENT for v in vals]
        return vals, colors

    v0, c0 = xy(init_hour)
    fig = go.Figure(go.Bar(x=v0, y=peak, orientation="h", marker_color=c0,
                           text=[f"{v:.0f}%" for v in v0], textposition="auto"))
    fig.frames = [go.Frame(name=h, data=[go.Bar(
        x=xy(h)[0], marker=dict(color=xy(h)[1]),
        text=[f"{v:.0f}%" for v in xy(h)[0]])]) for h in hours]
    fig.update_xaxes(title="Cargabilidad %", showgrid=False, range=[0, 160])
    fig.update_yaxes(automargin=False)
    return _anim_html(fig, div_id, 360, margin_l=240)


def anim_controller(map_id: str, hours: list, anim_targets: list,
                    vline_targets: list, init_hour: str, period_ms: int = 850) -> str:
    """Botones ▶/⏸ + JS que conduce la animación del mapa en BUCLE (al llegar a 24
    reinicia en 01) hasta pausar. Sincroniza: anima `anim_targets` (barras) y dibuja una
    línea vertical con el VALOR de la hora sobre los `vline_targets` (series)."""
    import json

    init_idx = hours.index(init_hour) if init_hour in hours else 0
    return (
        '<div class="anim-ctrl"><button type="button" id="' + map_id + '-play">▶</button>'
        '<button type="button" id="' + map_id + '-pause">⏸</button>'
        '<span class="anim-h" id="' + map_id + '-lab"></span></div>'
        "<script>(function(){var M=document.getElementById(" + json.dumps(map_id) + ");"
        "var HRS=" + json.dumps(hours) + ",A=" + json.dumps(anim_targets) +
        ",V=" + json.dumps(vline_targets) + ",idx=" + str(init_idx) + ",timer=null;"
        "function hi(n){return parseInt(String(n).replace('h_',''));}"
        "function ann(d,xi){var t=d.data&&d.data[0];if(!t||!t.x)return[];"
        "var xs=t.x,ys=t.y,k=-1;for(var i=0;i<xs.length;i++){if(xs[i]==xi){k=i;break;}}"
        "if(k<0)return[];return[{x:xi,y:ys[k],text:Math.round(ys[k]).toLocaleString(),"
        "showarrow:true,arrowhead:0,ax:0,ay:-16,bgcolor:'#fff',bordercolor:'#f59e0b',"
        "borderwidth:1,font:{size:11,color:'#0f172a'}}];}"
        "function apply(name){var xi=hi(name);"
        "var lb=document.getElementById(M.id+'-lab');if(lb)lb.textContent='Hora '+name.replace('h_','');"
        "A.forEach(function(id){var d=document.getElementById(id);"
        "if(d&&d._fullLayout&&window.Plotly)Plotly.animate(d,[name],{mode:'immediate',"
        "frame:{duration:0,redraw:true},transition:{duration:0}});});"
        "V.forEach(function(id){var d=document.getElementById(id);if(!d||!d._fullLayout)return;"
        "Plotly.relayout(d,{shapes:[{type:'line',xref:'x',yref:'paper',x0:xi,x1:xi,y0:0,y1:1,"
        "line:{color:'#f59e0b',width:2,dash:'dot'}}],annotations:ann(d,xi)});});}"
        "function show(){if(M&&M._fullLayout&&window.Plotly)Plotly.animate(M,[HRS[idx]],"
        "{mode:'immediate',frame:{duration:0,redraw:true},transition:{duration:0}});apply(HRS[idx]);}"
        "function step(){idx=(idx+1)%HRS.length;show();}"            # bucle: 24 -> 01
        "function play(){if(timer)return;timer=setInterval(step," + str(period_ms) + ");}"
        "function pause(){clearInterval(timer);timer=null;}"
        "function attach(){if(!M||!M.on){setTimeout(attach,200);return;}"
        "var pb=document.getElementById(M.id+'-play'),sb=document.getElementById(M.id+'-pause');"
        "if(pb)pb.onclick=play;if(sb)sb.onclick=pause;"
        "M.on('plotly_sliderchange',function(e){if(e&&e.step&&e.step.args&&e.step.args[0]){"
        "var n=e.step.args[0][0];var i=HRS.indexOf(n);if(i>=0)idx=i;apply(n);}});"
        "apply(HRS[idx]);}"
        "if(document.readyState!=='loading')attach();else window.addEventListener('load',attach);"
        "})();</script>")


# ----------------------------------------------------------- AC: perfil de tensión
def voltage_profile_div(bus_voltages: pd.DataFrame, hour: str | None = None) -> str:
    import plotly.graph_objects as go

    if bus_voltages.empty:
        return _empty()
    df = bus_voltages.copy()
    if hour and "hour" in df.columns:
        df = df[df["hour"] == hour]
    v = df["vm_pu"].dropna().sort_values().reset_index(drop=True)
    if v.empty:
        return _empty()
    colors = [BAD if x < 0.9 or x > 1.1 else GOOD for x in v]
    fig = go.Figure(go.Bar(x=list(range(len(v))), y=v, marker_color=colors))
    fig.add_hline(y=0.9, line_dash="dot", line_color=BAD)
    fig.add_hline(y=1.1, line_dash="dot", line_color=BAD)
    fig.update_yaxes(title="V pu", range=[0.7, 1.15], gridcolor=GRID)
    fig.update_xaxes(title="Barras (ordenadas por tensión)", showticklabels=False)
    return _div(fig, height=300)


# ----------------------------------------------------------- lazo: convergencia
def convergence_div(iterations: list[dict]) -> str:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if not iterations:
        return _empty("Sin iteraciones")
    it = [r["iter"] for r in iterations]
    delta = [r.get("loss_factor_delta") for r in iterations]
    losses = [r.get("losses_mw") for r in iterations]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=it, y=delta, name="Δ factor", mode="lines+markers",
                             line=dict(color=ACCENT, width=2)), secondary_y=False)
    fig.add_trace(go.Scatter(x=it, y=losses, name="Pérdidas MW", mode="lines+markers",
                             line=dict(color=WARN, width=2)), secondary_y=True)
    fig.update_xaxes(title="Iteración", dtick=1, gridcolor=GRID)
    fig.update_yaxes(title="Δ factor (log)", type="log", secondary_y=False, gridcolor=GRID)
    fig.update_yaxes(title="Pérdidas MW", secondary_y=True)
    fig.update_layout(legend=dict(orientation="h", y=1.12))
    return _div(fig, height=300)


# ----------------------------------------------------- MODOM: flujos por rama (24h)
def _branch_ratings() -> dict:
    """Snom (MVA) por par de barras, desde pypsa_branch_components (para % de carga)."""
    rt = {}
    for p in (LINES_CSV, TRAFOS_CSV):
        if p.exists():
            df = pd.read_csv(p)
            for r in df.itertuples():
                s = pd.to_numeric(getattr(r, "s_nom_mva_hint", None), errors="coerce")
                if pd.notna(s) and s > 0:
                    rt[frozenset((str(r.bus0), str(r.bus1)))] = float(s)
    return rt


def modom_flows_anim_div(flows: pd.DataFrame, hours: list, init_hour: str,
                         div_id: str, top: int = 15) -> str:
    """Cargabilidad (%) de las ramas MODOM más cargadas, animado por hora.

    El PDD publica el flujo activo en MW; el % = |flujo|/Snom usando los ratings de la
    red (pypsa_branch_components). Las ramas sin rating se omiten del % ."""
    import plotly.graph_objects as go

    if flows.empty:
        return _empty("Sin flujos MODOM")
    rt = _branch_ratings()

    def endpoints(c):
        p = str(c).split("|")
        return (p[0], p[1]) if len(p) >= 2 else (None, None)

    # cargabilidad por columna y hora (solo ramas con rating)
    cap = {}
    for c in flows.columns:
        a, b = endpoints(c)
        s = rt.get(frozenset((a, b))) if a else None
        if s:
            cap[c] = s
    if not cap:
        return _empty("Sin ratings para calcular %")
    loadpct = flows[list(cap)].abs().div(pd.Series(cap)) * 100.0
    lbl = {c: f"{bus_name(endpoints(c)[0])} → {bus_name(endpoints(c)[1])}" for c in cap}

    def frame_data(h):
        """Top-15 ramas de ESA hora, de mayor a menor cargabilidad."""
        row = loadpct.loc[h].sort_values(ascending=False).head(top) if h in loadpct.index \
            else loadpct.iloc[0].head(top)
        row = row.iloc[::-1]                            # mayor arriba en barh
        labels = [lbl[c] for c in row.index]
        vals = [float(v) for v in row.values]
        colors = [BAD if v > 100 else WARN if v > 90 else ACCENT for v in vals]
        return labels, vals, colors

    y0, v0, c0 = frame_data(init_hour)
    fig = go.Figure(go.Bar(x=v0, y=y0, orientation="h", marker_color=c0,
                           text=[f"{v:.0f}%" for v in v0], textposition="auto"))
    frames = []
    for h in hours:
        y, v, c = frame_data(h)
        frames.append(go.Frame(name=h, data=[go.Bar(
            x=v, y=y, marker=dict(color=c), text=[f"{x:.0f}%" for x in v])]))
    fig.frames = frames
    fig.update_xaxes(title="Cargabilidad %", showgrid=False, range=[0, 160])
    fig.update_yaxes(automargin=False)
    return _anim_html(fig, div_id, 380, margin_l=240)


# ----------------------------------------------------- base MODOM: mezcla por tec
def modom_mix_div() -> str:
    """Despacho MODOM por tecnología/combustible (24h), coloreado con la misma
    clasificación que el resto del proyecto. Fuente: modom_generator_dispatch.csv."""
    import plotly.graph_objects as go

    from ..dashboard import FUEL_COLORS, classify_fuel
    disp_p = REPO_ROOT / "data/processed/modom_results/modom_generator_dispatch.csv"
    gen_p = REPO_ROOT / "data/processed/generators/generators.csv"
    if not (disp_p.exists() and gen_p.exists()):
        return _empty("Sin despacho MODOM")
    disp = pd.read_csv(disp_p, index_col=0)
    g = pd.read_csv(gen_p)
    name_by = dict(zip(g.generator_id, g.generator_name.astype(str)))
    tech_by = dict(zip(g.generator_id, g.technology_group.astype(str)))
    cols: dict[str, list] = {}
    for gid in disp.columns:
        fuel = classify_fuel(name_by.get(gid, gid), tech_by.get(gid, ""))
        cols.setdefault(fuel, []).append(gid)
    x = [_hnum(h) for h in disp.index]
    order = ["Carbón", "Fuel Oil / Diesel", "Gas Natural", "Biomasa", "Hidro",
             "Eólica", "Solar", "Otra"]
    fig = go.Figure()
    for fuel in [f for f in order if f in cols] + [f for f in cols if f not in order]:
        s = disp[cols[fuel]].sum(axis=1)
        col = FUEL_COLORS.get(fuel, "#888")
        fig.add_trace(go.Scatter(x=x, y=s, name=fuel, stackgroup="m",
                                 mode="none", fillcolor=col,
                                 hovertemplate=f"{fuel}: %{{y:.0f}} MW<extra></extra>"))
    fig.update_yaxes(title="MW", showgrid=False)
    fig.update_xaxes(title="Hora", showgrid=False, dtick=2)
    fig.update_layout(legend=dict(orientation="h", y=1.12))
    return _div(fig, height=320)


# ----------------------------------------------------- comparación DC vs AC (24h)
def dc_vs_ac_div(summary_by_hour: pd.DataFrame) -> str:
    """Demanda vs generación AC y pérdidas por hora (la corrección que aporta la AC)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if summary_by_hour.empty or "hour" not in summary_by_hour.columns:
        return _empty("Sin resumen por hora")
    d = summary_by_hour.sort_values("hour")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=d["hour"], y=d.get("demand_mw"), name="Demanda (DC)",
                             line=dict(color=ACCENT, width=2)), secondary_y=False)
    if "gen_mw" in d:
        fig.add_trace(go.Scatter(x=d["hour"], y=d["gen_mw"], name="Generación (AC)",
                                 line=dict(color=GOOD, width=2, dash="dot")), secondary_y=False)
    fig.add_trace(go.Bar(x=d["hour"], y=d.get("losses_mw"), name="Pérdidas AC",
                         marker_color="rgba(245,158,11,.55)"), secondary_y=True)
    fig.update_yaxes(title="MW", secondary_y=False, gridcolor=GRID)
    fig.update_yaxes(title="Pérdidas MW", secondary_y=True)
    fig.update_xaxes(gridcolor=GRID)
    fig.update_layout(legend=dict(orientation="h", y=1.12))
    return _div(fig, height=300)


# ----------------------------------------------------------- estado de corridas
def run_status_donut_div(counts: dict) -> str:
    import plotly.graph_objects as go

    labels = ["Completadas", "Advertencia", "Fallidas", "En curso"]
    keys = ["completed", "warning", "failed", "running"]
    vals = [counts.get(k, 0) for k in keys]
    cols = [GOOD, WARN, BAD, ACCENT]
    if sum(vals) == 0:
        return _empty("Sin corridas")
    fig = go.Figure(go.Pie(labels=labels, values=vals, hole=0.62,
                           marker_colors=cols, textinfo="value"))
    fig.update_layout(showlegend=True, legend=dict(orientation="v", x=1, y=0.5),
                      annotations=[dict(text=str(sum(vals)), x=0.5, y=0.5,
                                        font_size=22, showarrow=False)])
    return _div(fig, height=260)


# ----------------------------------------------------------- caso base (Dashboard)
def base_figures() -> dict[str, str]:
    """Mezcla de generación, demanda vs gen y costo marginal del caso base."""
    try:
        from ..dashboard import (DEFAULT_DATA_DIR, DEFAULT_EXTERNAL_DIR,
                                 DEFAULT_RESULTS_DIR, build_figures, load_inputs)
        data = load_inputs(DEFAULT_RESULTS_DIR, DEFAULT_DATA_DIR, DEFAULT_EXTERNAL_DIR)
        figs, *_ = build_figures(data)
        return {k: _div(figs[k], div_id=f"{k}-div") for k in ("mix", "price", "cong")
                if k in figs}
    except Exception:  # noqa: BLE001
        return {}

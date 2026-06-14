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

# color de líneas por nivel de tensión (tenue, para que resalten las barras por V)
VOLT_LINE = {345: "#7c3aed", 230: "#0ea5e9", 138: "#10b981", 69: "#f59e0b"}


def _volt_color(kv) -> str:
    try:
        kv = float(kv)
    except (TypeError, ValueError):
        return "#cbd5e1"
    for std, col in VOLT_LINE.items():
        if abs(kv - std) < 0.7:
            return col
    return "#cbd5e1"


_GEO = {}


def _geometry() -> dict:
    """Coordenadas, nombres de barra y segmentos de línea (cacheado)."""
    if _GEO:
        return _GEO
    coords, names, segs = {}, {}, []
    if COORDS_CSV.exists():
        c = pd.read_csv(COORDS_CSV)
        c = c[pd.to_numeric(c["lat"], errors="coerce").notna()]
        coords = {str(r.bus_id_modom): (float(r.lat), float(r.lon)) for r in c.itertuples()}
    if BUSES_CSV.exists():
        b = pd.read_csv(BUSES_CSV)
        for r in b.itertuples():
            nm = str(getattr(r, "bus_name", "") or "").strip()
            names[str(r.bus_id_modom)] = nm if nm and nm.lower() != "nan" else str(r.bus_id_modom)
    frames = [p for p in (LINES_CSV, TRAFOS_CSV) if p.exists()]
    if frames:
        br = pd.concat([pd.read_csv(p) for p in frames], ignore_index=True)
        for r in br.itertuples():
            b0, b1 = str(r.bus0), str(r.bus1)
            if b0 in coords and b1 in coords:
                kv = pd.to_numeric(getattr(r, "v_nom_bus0_kv", None), errors="coerce")
                segs.append((coords[b0], coords[b1], _volt_color(kv), str(r.name)))
    _GEO.update(coords=coords, names=names, segs=segs)
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
    # red de transmisión, agrupada por color (nivel de tensión)
    by_col: dict[str, list] = {}
    red_lat, red_lon = [], []
    for (a, b, col, name) in segs:
        if name in overloaded:
            red_lat += [a[0], b[0], None]; red_lon += [a[1], b[1], None]
            continue
        d = by_col.setdefault(col, [[], []])
        d[0] += [a[0], b[0], None]; d[1] += [a[1], b[1], None]
    for col, (la, lo) in by_col.items():
        fig.add_trace(go.Scattermapbox(lat=la, lon=lo, mode="lines",
            line=dict(width=1.4, color=col), hoverinfo="skip", showlegend=False))
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
                       config={"displayModeBar": False, "responsive": True})


def bus_name(w: str) -> str:
    """Nombre legible de una barra MODOM (W-code -> nombre)."""
    return _geometry()["names"].get(str(w), str(w))


# ----------------------------------------------------------- auditoría: serie 24h
def series_line_div(series, ylabel: str = "", sel_hour: str | None = None,
                    color: str = ACCENT) -> str:
    """Gráfico de línea de una serie 24h [(hora, valor)] para la auditoría."""
    import plotly.graph_objects as go

    pts = [(h, v) for h, v in (series or []) if isinstance(v, (int, float))]
    if not pts:
        return _empty("Sin serie numérica")
    xs = [h for h, _ in pts]
    ys = [v for _, v in pts]
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers",
                               line=dict(color=color, width=2.5),
                               marker=dict(size=6), fill="tozeroy",
                               fillcolor="rgba(37,99,235,.08)"))
    if sel_hour in xs:
        i = xs.index(sel_hour)
        fig.add_trace(go.Scatter(x=[sel_hour], y=[ys[i]], mode="markers",
                                 marker=dict(size=12, color=WARN), showlegend=False))
    fig.update_yaxes(title=ylabel, gridcolor=GRID)
    fig.update_xaxes(gridcolor=GRID)
    return _div(fig, height=280)


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

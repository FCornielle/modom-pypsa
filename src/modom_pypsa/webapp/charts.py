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
def voltage_map_div(bus_voltages: pd.DataFrame, hour: str | None = None) -> str:
    import plotly.graph_objects as go

    if bus_voltages.empty or not COORDS_CSV.exists():
        return _empty("Sin tensiones / coordenadas")
    df = bus_voltages.copy()
    if hour and "hour" in df.columns:
        df = df[df["hour"] == hour]
    df = df[df["vm_pu"].notna()]
    coords = pd.read_csv(COORDS_CSV)
    coords = coords[["bus_id_modom", "lat", "lon"]].dropna()
    df = df.merge(coords, on="bus_id_modom", how="inner")
    if df.empty:
        return _empty("Sin barras geolocalizadas con tensión")
    fig = go.Figure(go.Scattermapbox(
        lat=df["lat"], lon=df["lon"], mode="markers",
        marker=dict(size=9, color=df["vm_pu"], colorscale="RdYlGn",
                    cmin=0.90, cmax=1.10, showscale=True,
                    colorbar=dict(title="V pu", thickness=12)),
        text=[f"{b}<br>{v:.3f} pu" for b, v in zip(df["bus_id_modom"], df["vm_pu"])],
        hoverinfo="text"))
    fig.update_layout(mapbox=dict(style="carto-positron",
                                  center=dict(lat=18.8, lon=-70.2), zoom=7),
                      margin=dict(l=0, r=0, t=0, b=0), height=420)
    import plotly.io as pio
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False, "responsive": True})


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

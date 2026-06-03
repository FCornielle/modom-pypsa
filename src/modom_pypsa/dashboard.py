"""Genera un dashboard del SENI como un único HTML autocontenido y compartible.

Inspirado en gridstatus.io/live: tema oscuro, KPIs, mapa geográfico de precios,
mezcla de generación por combustible ("fuel mix") y curva de demanda. NO es un
servidor: produce un archivo `.html` con Plotly.js embebido para abrir/compartir
sin conexión.

Insumos (ya generados por el pipeline):
- `results/pypsa_basecase/*.csv` y `pypsa_basecase_summary.json` (despacho LOPF)
- `data/external/buses_with_coords.csv` (barras geolocalizadas)
- `data/processed/generators/generators.csv` (para el combustible por generador)
- `data/processed/pypsa_branch_components/{lines_v1,transformers_v1}.csv` (aristas)
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = REPO_ROOT / "results" / "pypsa_basecase"
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "processed"
DEFAULT_EXTERNAL_DIR = REPO_ROOT / "data" / "external"
DEFAULT_OUT = REPO_ROOT / "results" / "dashboard" / "seni_dashboard.html"

# Paleta tipo "fuel mix" (combustible -> color).
FUEL_COLORS = {
    "Solar": "#f4c430",
    "Eólica": "#33c9b8",
    "Hidro": "#3b9ae1",
    "Gas Natural": "#f08a24",
    "Fuel Oil / Diesel": "#b0683c",
    "Carbón": "#6b6f76",
    "Biomasa": "#5cb85c",
    "Otra": "#9b7fd4",
}


def _norm(text: str) -> str:
    out = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return out.upper()


def classify_fuel(name: str, technology_group: str) -> str:
    """Clasifica un generador en un combustible a partir de su nombre.

    Reglas por palabra clave; hidro como respaldo para los grupos tecnológicos
    2 y 3 (centrales hidroeléctricas de EGEHID en MODOM).
    """
    n = _norm(name)
    if re.search(r"SOLAR|FOTOVOLT|\bFV\b|PV", n):
        return "Solar"
    if re.search(r"EOLIC|VIENTO|WIND", n):
        return "Eólica"
    if "CARBON" in n:
        return "Carbón"
    if re.search(r"\bGN\b|GAS NATURAL|ENERGAS|CICLO COMBINADO|\bCC\b", n):
        return "Gas Natural"
    if re.search(r"\bFO\b|FUEL|VAPOR|DIESEL|MOTOR|GASOIL|\bGAS OIL\b", n):
        return "Fuel Oil / Diesel"
    if re.search(r"BIO|INGENIO|BAGAZO", n):
        return "Biomasa"
    if str(technology_group).strip() in {"2", "3"}:
        return "Hidro"
    return "Otra"


def _read(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, **kw)


def line_label(branch_name: str, name_by_bus: dict[str, str]) -> str:
    """`WAANDE__WENADE__L1` -> `AES ANDRÉS ↔ ENRIQUILLO · L1` (nombres largos)."""
    parts = str(branch_name).split("__")
    if len(parts) >= 2:
        a = name_by_bus.get(parts[0], parts[0])
        b = name_by_bus.get(parts[1], parts[1])
        circ = f" · {parts[2]}" if len(parts) > 2 and parts[2] else ""
        return f"{a} ↔ {b}{circ}"
    return str(branch_name)


def load_inputs(
    results_dir: Path, data_dir: Path, external_dir: Path
) -> dict[str, object]:
    gen = _read(results_dir / "generation_by_snapshot.csv", index_col=0)
    load = _read(results_dir / "load_by_snapshot.csv", index_col=0)
    prices = _read(results_dir / "nodal_prices_by_snapshot.csv", index_col=0)
    loading = _read(results_dir / "line_loading_by_snapshot.csv", index_col=0)
    summary = json.loads((results_dir / "pypsa_basecase_summary.json").read_text("utf-8"))

    generators = _read(data_dir / "generators" / "generators.csv")
    fuel_by_gen = {
        str(r.generator_id): classify_fuel(r.generator_name, r.technology_group)
        for r in generators.itertuples()
    }
    buses_full = _read(data_dir / "buses" / "buses.csv")
    name_by_bus = {
        str(r.bus_id_modom): (str(r.bus_name).strip() or str(r.bus_id_modom))
        for r in buses_full.itertuples()
    }
    coords = _read(external_dir / "buses_with_coords.csv")
    coords = coords[coords["lat"].astype(str).str.strip() != ""].copy()
    coords["lat"] = pd.to_numeric(coords["lat"], errors="coerce")
    coords["lon"] = pd.to_numeric(coords["lon"], errors="coerce")
    coords = coords.dropna(subset=["lat", "lon"])

    lines = _read(data_dir / "pypsa_branch_components" / "lines_v1.csv")
    trafos = _read(data_dir / "pypsa_branch_components" / "transformers_v1.csv")
    branches = pd.concat([lines[["name", "bus0", "bus1"]], trafos[["name", "bus0", "bus1"]]])

    return {
        "gen": gen,
        "load": load,
        "prices": prices,
        "loading": loading,
        "summary": summary,
        "fuel_by_gen": fuel_by_gen,
        "name_by_bus": name_by_bus,
        "coords": coords,
        "branches": branches,
    }


def _fuel_mix(gen: pd.DataFrame, fuel_by_gen: dict[str, str]) -> pd.DataFrame:
    real = [c for c in gen.columns if not str(c).startswith("unserved")]
    fuels = pd.Series({c: fuel_by_gen.get(str(c), "Otra") for c in real})
    mix = gen[real].T.groupby(fuels).sum().T
    # ordenar columnas por aporte total descendente
    return mix[mix.sum().sort_values(ascending=False).index]


def build_figures(data: dict[str, object]):
    import plotly.graph_objects as go

    gen, load, prices = data["gen"], data["load"], data["prices"]
    loading, coords, branches = data["loading"], data["coords"], data["branches"]
    fuel_by_gen = data["fuel_by_gen"]
    name_by_bus = data["name_by_bus"]

    hours = list(range(1, len(gen.index) + 1))
    total_load = load.sum(axis=1)
    peak_i = int(total_load.values.argmax())
    peak_snap = load.index[peak_i]

    # ---- Fuel mix (área apilada) + demanda ----
    mix = _fuel_mix(gen, fuel_by_gen)
    fig_mix = go.Figure()
    for fuel in mix.columns:
        fig_mix.add_trace(
            go.Scatter(
                x=hours, y=mix[fuel], name=fuel, mode="lines", stackgroup="gen",
                line=dict(width=0.5, color=FUEL_COLORS.get(fuel, "#888")),
                fillcolor=FUEL_COLORS.get(fuel, "#888"),
                hovertemplate=f"{fuel}: %{{y:.0f}} MW<extra></extra>",
            )
        )
    fig_mix.add_trace(
        go.Scatter(
            x=hours, y=total_load.values, name="Demanda", mode="lines",
            line=dict(color="#ffffff", width=2, dash="dot"),
            hovertemplate="Demanda: %{y:.0f} MW<extra></extra>",
        )
    )
    fig_mix.update_layout(
        title="Mezcla de generación por combustible (24 h)",
        xaxis_title="Hora", yaxis_title="MW", template="plotly_dark",
        legend=dict(orientation="h", y=-0.2), margin=dict(l=40, r=20, t=50, b=40),
    )

    # ---- Precios nodales: banda min/prom/max por hora ----
    finite = prices.where(prices < 1e5)  # excluir precio de no-suministro (~1e6)
    p_min, p_avg, p_max = finite.min(axis=1), finite.mean(axis=1), finite.max(axis=1)
    fig_price = go.Figure()
    fig_price.add_trace(go.Scatter(x=hours, y=p_max, name="Máx", mode="lines",
                                   line=dict(width=0, color="#f08a24")))
    fig_price.add_trace(go.Scatter(x=hours, y=p_min, name="Mín", mode="lines",
                                   fill="tonexty", fillcolor="rgba(240,138,36,0.2)",
                                   line=dict(width=0, color="#f08a24")))
    fig_price.add_trace(go.Scatter(x=hours, y=p_avg, name="Promedio", mode="lines",
                                   line=dict(color="#f4c430", width=2)))
    fig_price.update_layout(
        title="Precio marginal nodal (RD$/MWh)", xaxis_title="Hora",
        yaxis_title="RD$/MWh", template="plotly_dark",
        legend=dict(orientation="h", y=-0.2), margin=dict(l=40, r=20, t=50, b=40),
    )

    # ---- Top líneas congestionadas (carga pico), con nombres largos ----
    peak_loading = loading.max().sort_values(ascending=False).head(15) * 100
    cong_labels = [line_label(n, name_by_bus) for n in peak_loading.index]
    fig_cong = go.Figure(
        go.Bar(
            x=peak_loading.values[::-1], y=cong_labels[::-1],
            orientation="h",
            marker=dict(color=peak_loading.values[::-1], colorscale="YlOrRd", cmin=0, cmax=100),
            hovertemplate="%{y}<br>%{x:.0f}% del límite<extra></extra>",
        )
    )
    fig_cong.update_layout(
        title="Top 15 líneas por carga máxima (%)", xaxis_title="% del límite térmico",
        template="plotly_dark", margin=dict(l=320, r=20, t=50, b=40),
        yaxis=dict(tickfont=dict(size=10)),
    )

    # ---- Mapa geográfico (hora pico) ----
    coord = {r.bus_id_modom: (r.lat, r.lon) for r in coords.itertuples()}
    price_peak = prices.loc[peak_snap]
    load_map = load.loc[peak_snap]
    load_by_bus = {c.replace("load_", ""): load_map[c] for c in load.columns}

    # aristas: segmentos normales vs congestionados (>=90% en la hora pico)
    load_peak_line = loading.loc[peak_snap]
    norm_lat, norm_lon, cong_lat, cong_lon = [], [], [], []
    n_lines_drawn = 0
    for b in branches.itertuples():
        if b.bus0 in coord and b.bus1 in coord:
            la0, lo0 = coord[b.bus0]
            la1, lo1 = coord[b.bus1]
            n_lines_drawn += 1
            congested = float(load_peak_line.get(b.name, 0) or 0) >= 0.9
            (cong_lat if congested else norm_lat).extend([la0, la1, None])
            (cong_lon if congested else norm_lon).extend([lo0, lo1, None])

    fig_map = go.Figure()
    fig_map.add_trace(go.Scattermapbox(
        lat=norm_lat, lon=norm_lon, mode="lines",
        line=dict(width=1.6, color="rgba(120,200,255,0.55)"),
        name="Líneas / transformadores", hoverinfo="skip"))
    fig_map.add_trace(go.Scattermapbox(
        lat=cong_lat, lon=cong_lon, mode="lines",
        line=dict(width=3.5, color="#ff3b3b"),
        name="Congestión ≥90%", hoverinfo="skip"))

    blat, blon, bcolor, bsize, btext = [], [], [], [], []
    pcap = float(finite.stack().quantile(0.97)) if finite.stack().size else 1.0
    for bus_id, (la, lo) in coord.items():
        pr = float(price_peak.get(bus_id, float("nan")))
        ld = float(load_by_bus.get(bus_id, 0) or 0)
        blat.append(la); blon.append(lo)
        bcolor.append(min(pr, pcap) if pr == pr else 0)
        bsize.append(6 + min(ld, 200) / 200 * 22)
        nm = name_by_bus.get(bus_id, bus_id)
        btext.append(
            f"<b>{nm}</b> ({bus_id})<br>precio: {pr:,.0f} RD$/MWh<br>carga: {ld:,.1f} MW"
        )
    fig_map.add_trace(go.Scattermapbox(
        lat=blat, lon=blon, mode="markers",
        marker=dict(size=bsize, color=bcolor, colorscale="Turbo", cmin=0, cmax=pcap,
                    colorbar=dict(title="RD$/MWh"), opacity=0.9),
        text=btext, hovertemplate="%{text}<extra></extra>", name="Barras"))
    fig_map.update_layout(
        title=f"Mapa SENI — precio nodal y congestión (hora pico {peak_snap})",
        mapbox=dict(style="open-street-map", center=dict(lat=18.8, lon=-70.4), zoom=6.7),
        template="plotly_dark", margin=dict(l=0, r=0, t=50, b=0), height=560,
        legend=dict(orientation="h", y=0, x=0, bgcolor="rgba(0,0,0,0.4)"),
    )

    kpis = _kpis(data, total_load, mix, peak_snap)
    stats = {
        "snapshots": len(gen.index),
        "peak_snap": str(peak_snap),
        "total_demand_mwh": float(total_load.sum()),
        "peak_load_mw": float(total_load.max()),
        "n_gen": len([c for c in gen.columns if not str(c).startswith("unserved")]),
        "n_buses": len(name_by_bus),
        "n_buses_geo": len(coords),
        "n_branches": len(branches),
        "n_lines_drawn": n_lines_drawn,
    }
    figs = {"map": fig_map, "mix": fig_mix, "price": fig_price, "cong": fig_cong}
    return figs, kpis, stats


def conditions_html(data: dict[str, object], stats: dict, mix, case_label: str) -> str:
    """Bloque HTML con las condiciones iniciales y supuestos del modelo."""
    s = data["summary"]
    renew = [c for c in mix.columns if c in ("Solar", "Eólica", "Hidro", "Biomasa")]
    renew_share = (mix[renew].sum().sum() / mix.sum().sum() * 100) if mix.sum().sum() else 0
    caso = [
        f"<b>Caso fuente:</b> {case_label}",
        f"<b>Eje temporal:</b> {stats['snapshots']} snapshots horarios (24 h); "
        f"hora pico = {stats['peak_snap']}",
        f"<b>Demanda total del día:</b> {stats['total_demand_mwh']:,.0f} MWh · "
        f"pico {stats['peak_load_mw']:,.0f} MW",
        f"<b>Cobertura del modelo:</b> {stats['n_buses']} barras, "
        f"{stats['n_branches']} ramas (líneas+transformadores), "
        f"{stats['n_gen']} generadores",
        f"<b>Energía servida / no suministrada:</b> {s.get('served_mwh', 0):,.0f} / "
        f"{s.get('unserved_mwh', 0):,.0f} MWh · aporte renovable ≈ {renew_share:.0f}%",
        f"<b>Geolocalización:</b> {stats['n_buses_geo']} barras con coordenadas reales "
        f"(puntos SMC del OC); {stats['n_lines_drawn']} ramas dibujadas en el mapa",
    ]
    supuestos = [
        "Despacho económico con red <b>LOPF lineal</b> (balance nodal + ley de "
        "Kirchhoff de tensiones + límites térmicos). No es flujo de potencia AC.",
        "Base <b>por-unidad</b> con <code>v_nom = 1.0</code> en todas las barras: las "
        "impedancias de MODOM ya vienen en pu y los flujos dependen de reactancias "
        "relativas. Transformadores tratados como impedancia serie.",
        "El <b>p_min</b> de los generadores se reporta pero no se impone en esta "
        "versión; el costo marginal usa <code>cvp</code> efectivo de MODOM.",
        "Generador de <b>energía no suministrada</b> (costo muy alto) por barra con "
        "demanda: garantiza factibilidad y mide el déficit por congestión.",
        "Impedancias, unidades y costos son <b>insumos provisionales v1</b>; la energía "
        "no suministrada y los precios son señales analíticas, no resultados operativos "
        "ni de mercado finales.",
    ]
    li = lambda items: "".join(f"<li>{x}</li>" for x in items)
    return (
        '<div class="cond-grid">'
        f'<div><h3>Condiciones iniciales del caso</h3><ul>{li(caso)}</ul></div>'
        f'<div><h3>Supuestos del modelo</h3><ul>{li(supuestos)}</ul></div>'
        "</div>"
    )


def _kpis(data, total_load, mix, peak_snap) -> list[tuple[str, str]]:
    s = data["summary"]
    served = s.get("served_mwh", 0.0)
    unserved = s.get("unserved_mwh", 0.0)
    total = served + unserved
    renew = [c for c in mix.columns if c in ("Solar", "Eólica", "Hidro", "Biomasa")]
    renew_share = (mix[renew].sum().sum() / mix.sum().sum() * 100) if mix.sum().sum() else 0
    return [
        ("Demanda pico", f"{s.get('peak_load_mw', 0):,.0f} MW"),
        ("Energía servida", f"{served:,.0f} MWh"),
        ("No suministrada", f"{unserved:,.0f} MWh ({(unserved/total*100 if total else 0):.1f}%)"),
        ("Líneas ≥90%", f"{s.get('lines_above_90pct_peak', 0)}"),
        ("Aporte renovable", f"{renew_share:.0f}%"),
        ("Barras geolocalizadas", f"{len(data['coords'])}"),
    ]


_TEMPLATE = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SENI · Dashboard de despacho</title>
<script>{plotly_js}</script>
<style>
 body{{margin:0;background:#0e1117;color:#e6e6e6;font-family:Segoe UI,Roboto,Arial,sans-serif}}
 header{{padding:18px 24px;border-bottom:1px solid #232730}}
 header h1{{margin:0;font-size:20px}} header p{{margin:4px 0 0;color:#8b94a3;font-size:13px}}
 .kpis{{display:flex;flex-wrap:wrap;gap:14px;padding:18px 24px}}
 .kpi{{background:#161b24;border:1px solid #232730;border-radius:10px;padding:14px 18px;min-width:150px;flex:1}}
 .kpi .v{{font-size:22px;font-weight:600}} .kpi .l{{color:#8b94a3;font-size:12px;margin-top:4px}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0 24px 24px}}
 .card{{background:#0e1117;border:1px solid #232730;border-radius:10px;overflow:hidden}}
 .full{{grid-column:1 / -1}}
 .cond{{padding:8px 24px 24px}}
 .cond-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
 .cond h3{{font-size:14px;margin:0 0 8px;color:#cdd5e0}}
 .cond ul{{margin:0;padding-left:18px}} .cond li{{font-size:12.5px;color:#aab3c0;margin:6px 0;line-height:1.5}}
 .cond code{{background:#1b2230;padding:1px 5px;border-radius:4px;color:#d6e2f0}}
 .cond .box{{background:#161b24;border:1px solid #232730;border-radius:10px;padding:16px 20px}}
 footer{{color:#6b7280;font-size:12px;padding:0 24px 30px}}
 @media(max-width:900px){{.grid,.cond-grid{{grid-template-columns:1fr}}}}
</style></head>
<body>
<header><h1>⚡ SENI · Dashboard de despacho</h1>
<p>Modelo PyPSA (LOPF lineal, 24 h) desde la capa canónica MODOM · {gen_date}</p></header>
<div class="kpis">{kpi_html}</div>
<div class="grid">
 <div class="card full">{map}</div>
 <div class="card">{mix}</div>
 <div class="card">{price}</div>
 <div class="card full">{cong}</div>
</div>
<section class="cond"><div class="box">{conditions}</div></section>
<footer>Artefacto analítico reproducible. La energía no suministrada y los precios
reflejan insumos provisionales (impedancias/costos) del modelo v1, no resultados
operativos finales.</footer>
</body></html>"""


DEFAULT_CASE_LABEL = "MODOM_DIARIO (V449) — caso diario del SENI"


def build_dashboard(
    results_dir: Path = DEFAULT_RESULTS_DIR,
    data_dir: Path = DEFAULT_DATA_DIR,
    external_dir: Path = DEFAULT_EXTERNAL_DIR,
    out_path: Path = DEFAULT_OUT,
    case_label: str = DEFAULT_CASE_LABEL,
) -> Path:
    import datetime as _dt

    import plotly.io as pio
    from plotly.offline import get_plotlyjs

    data = load_inputs(results_dir, data_dir, external_dir)
    figs, kpis, stats = build_figures(data)
    mix = _fuel_mix(data["gen"], data["fuel_by_gen"])
    cond = conditions_html(data, stats, mix, case_label)

    def div(fig) -> str:
        return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                           config={"displayModeBar": False, "responsive": True})

    kpi_html = "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'
        for l, v in kpis
    )
    html = _TEMPLATE.format(
        plotly_js=get_plotlyjs(),
        gen_date=_dt.date.today().isoformat(),
        kpi_html=kpi_html,
        map=div(figs["map"]), mix=div(figs["mix"]),
        price=div(figs["price"]), cong=div(figs["cong"]),
        conditions=cond,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path

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

# Paleta por nivel de tensión (kV -> color) para las líneas del mapa.
# Colores según la convención del SENI; el 138 kV va en naranja CLARO a propósito
# para que una línea congestionada (roja y gruesa) se distinga con claridad.
VOLT_COLORS = {
    "LT 345 kV": "#0b6e36",            # verde oscuro
    "LT 230 kV": "#4b0082",            # índigo / morado
    "LT 138 kV": "#ff9e3d",            # naranja claro
    "LT 69 kV": "#1414ff",             # azul
    "LT o cable 34.5 kV": "#10c0d0",   # cian
    "LT Fuera de servicio": "#9aa0a8", # gris
}
VOLT_ORDER = ["LT 345 kV", "LT 230 kV", "LT 138 kV", "LT 69 kV",
              "LT o cable 34.5 kV", "LT Fuera de servicio"]
CONGESTION_COLOR = "#e8001c"  # rojo para líneas congestionadas (>=90%)
_VOLT_STD = [(345, "LT 345 kV"), (230, "LT 230 kV"), (138, "LT 138 kV"),
             (69, "LT 69 kV"), (34.5, "LT o cable 34.5 kV")]


def volt_bucket(kv: float | None) -> str:
    """Asigna una tensión (kV) al nivel estándar más cercano del SENI."""
    if kv is None or kv != kv:  # None o NaN
        return "LT Fuera de servicio"
    for std, label in _VOLT_STD:
        if abs(float(kv) - std) < 0.7:
            return label
    return "LT Fuera de servicio"


def _norm(text: str) -> str:
    out = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return out.upper()


# Combustible por central, según el unifilar (SLD) del OC. Listas de nombres para
# las plantas cuyo combustible no se infiere del nombre genérico.
_CARBON = ("PUNTA CATALINA", "BARAHONA CARBON")
_WIND = ("LOS COCOS", "JUANCHO", "QUILVIO", "CABRERA", "GUANILLO", "MATAFONGO",
         "AGUA CLARA", "GUZMANCITO", "LARIMAR", "PECASA")
_GAS = ("ESTRELLA DEL MAR", "SEABOARD", "LOS MINA", "SIBA", "MANZANILLO", "ENERGAS")
_FUEL = ("POWERSHIP", "KPS", "SULTANA", "PIMENTEL", "PALAMARA", "LA VEGA", "BERSAL",
         "HAINA TG", "INCA", "METALDOM", "MONTE RIO", "SAN LORENZO", "PALENQUE",
         "LOS ORIGENES", "QUISQUEYA", "EDM", "CESPM")
_HYDRO = ("JIGUEY", "AGUACATE", "VALDESIA", "TAVERA", "PALOMINO", "MONCION",
          "RIO BLANCO", "PINALITO", "HATILLO", "LOPEZ ANGOSTURA", "SABANA YEGUA",
          "SABANETA", "RINCON", "BAIGUAQUE", "ANIANA VARGAS", "DOMINGO RODRIGUEZ",
          "LAS DAMAS", "LAS BARIAS", "BRAZO DERECHO", "NIZAO", "NAJAYO", "MAGUEYAL",
          "JIMENOA", "EL SALTO", "CONTRAEMBALSE", "CONTRA EMBALSE", "LOS TOROS",
          "LOS ANONES")


def classify_fuel(name: str, technology_group: str) -> str:
    """Clasifica un generador en un combustible.

    Usa el combustible declarado en el unifilar (SLD) del OC: prioriza nombres
    explícitos (carbón, parques eólicos/solares, térmicas a gas o fuel oil) y deja
    los grupos tecnológicos 2/3 como hidro (centrales EGEHID).
    """
    n = _norm(name)
    tg = str(technology_group).strip()

    def has(words: tuple[str, ...]) -> bool:
        return any(w in n for w in words)

    if "ITABO" in n and "TG" not in n:        # Itabo 1/2 = carbón; Itabo TG = fuel oil
        return "Carbón"
    if has(_CARBON):
        return "Carbón"
    if re.search(r"SOLAR|FOTOVOLT|\bFV\b|\bPV\b", n):
        return "Solar"
    if re.search(r"EOLIC|VIENTO|\bWIND\b", n) or has(_WIND):
        return "Eólica"
    if re.search(r"BIO|INGENIO|BAGAZO", n):
        return "Biomasa"
    if tg in {"2", "3"} or has(_HYDRO):
        return "Hidro"
    if re.search(r"\bGN\b|GAS NATURAL|CICLO COMBINADO|\bCC\b", n) or has(_GAS):
        return "Gas Natural"
    if re.search(r"\bFO\b|FUEL|VAPOR|DIESEL|MOTOR|GASOIL", n) or has(_FUEL):
        return "Fuel Oil / Diesel"
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

    def _name(raw, bus_id) -> str:
        s = "" if raw is None else str(raw).strip()
        return s if s and s.lower() != "nan" else str(bus_id)

    name_by_bus = {
        str(r.bus_id_modom): _name(r.bus_name, r.bus_id_modom)
        for r in buses_full.itertuples()
    }

    # Barra de referencia del SENI: PALAMARA 138 kV (la usa el OC para el CMg).
    def _find_ref_bus() -> str:
        bf = buses_full.copy()
        bf["v"] = pd.to_numeric(bf["v_nom_kv"], errors="coerce")
        names = (bf["bus_name"].astype(str) + " " + bf.get("bus_name_legacy", "").astype(str))
        pal = bf[names.str.contains("PALAMARA", case=False, na=False)]
        ref = pal[(pal["v"] - 138).abs() < 1]
        pick = ref if len(ref) else pal
        return str(pick["bus_id_modom"].iloc[0]) if len(pick) else ""

    ref_bus = _find_ref_bus()
    coords = _read(external_dir / "buses_with_coords.csv")
    coords = coords[coords["lat"].astype(str).str.strip() != ""].copy()
    coords["lat"] = pd.to_numeric(coords["lat"], errors="coerce")
    coords["lon"] = pd.to_numeric(coords["lon"], errors="coerce")
    coords = coords.dropna(subset=["lat", "lon"])

    bcols = ["name", "bus0", "bus1", "v_nom_bus0_kv", "v_nom_bus1_kv"]
    lines = _read(data_dir / "pypsa_branch_components" / "lines_v1.csv")
    trafos = _read(data_dir / "pypsa_branch_components" / "transformers_v1.csv")
    branches = pd.concat([lines[bcols], trafos[bcols]], ignore_index=True)
    excl_path = data_dir / "pypsa_branch_components" / "excluded_branches_v1.csv"
    excluded = (
        _read(excl_path)
        if excl_path.exists()
        else pd.DataFrame(columns=["branch_id", "from_bus", "to_bus"])
    )

    return {
        "gen": gen,
        "load": load,
        "prices": prices,
        "loading": loading,
        "summary": summary,
        "fuel_by_gen": fuel_by_gen,
        "name_by_bus": name_by_bus,
        "ref_bus": ref_bus,
        "coords": coords,
        "branches": branches,
        "excluded": excluded,
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
    excluded = data["excluded"]
    fuel_by_gen = data["fuel_by_gen"]
    name_by_bus = data["name_by_bus"]
    ref_bus = data.get("ref_bus", "")

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
    mix_ymax = float(max(total_load.max(), mix.sum(axis=1).max())) * 1.05
    fig_mix.update_layout(
        title="Mezcla de generación (MW)",
        xaxis_title="Hora", yaxis_title="MW", template="plotly_dark",
        xaxis=dict(range=[0.5, len(hours) + 0.5]),
        yaxis=dict(range=[0, mix_ymax]),
        legend=dict(orientation="h", y=-0.2), margin=dict(l=40, r=20, t=50, b=40),
    )

    # ---- Precio nodal en la BARRA DE REFERENCIA (Palamara 138 kV) ----
    finite = prices.where(prices < 1e5)  # excluir precio de no-suministro (~1e6)
    if ref_bus and ref_bus in finite.columns:
        ref_series = finite[ref_bus]
        ref_title = "Precio nodal · Palamara 138 kV (ref.)"
    else:  # respaldo si no se halla la barra de referencia
        ref_series = finite.mean(axis=1)
        ref_title = "Precio nodal (promedio del sistema)"
    price_ymax = float(ref_series.max()) * 1.1 if ref_series.notna().any() else 1.0
    fig_price = go.Figure(
        go.Scatter(
            x=hours, y=ref_series.values, name="Palamara 138 kV", mode="lines",
            line=dict(color="#f4c430", width=2.5),
            fill="tozeroy", fillcolor="rgba(244,196,48,0.15)",
            hovertemplate="Hora %{x}<br>%{y:,.0f} RD$/MWh<extra></extra>",
        )
    )
    fig_price.update_layout(
        title=ref_title, xaxis_title="Hora", yaxis_title="RD$/MWh",
        template="plotly_dark", showlegend=False,
        xaxis=dict(range=[0.5, len(hours) + 0.5]),
        yaxis=dict(range=[0, price_ymax]),
        margin=dict(l=50, r=20, t=50, b=40),
    )

    # ---- Top 15 líneas más cargadas (varía con el deslizador de hora vía JS) ----
    def _top15(snap):
        s = (loading.loc[snap] * 100).sort_values(ascending=False).head(15)
        labels = [line_label(n, name_by_bus) for n in s.index][::-1]
        vals = [round(float(v), 1) for v in s.values][::-1]
        return labels, vals

    top_labels, top_vals = _top15(peak_snap)
    fig_cong = go.Figure(
        go.Bar(
            x=top_vals, y=top_labels, orientation="h",
            marker=dict(color=top_vals, colorscale="YlOrRd", cmin=0, cmax=100),
            hovertemplate="%{y}<br>%{x:.0f}% del límite<extra></extra>",
        )
    )
    fig_cong.update_layout(
        title="Top 15 líneas más cargadas",
        xaxis_title="% del límite térmico", xaxis=dict(range=[0, 105]),
        template="plotly_dark", margin=dict(l=232, r=12, t=50, b=40),
        yaxis=dict(tickfont=dict(size=8.5)),
    )

    # ---- Mapa geográfico ANIMADO por hora (slider 1..24) ----
    # Geometría estática (las líneas no se mueven); por hora cambian: color/size/
    # hover de barras (precio y carga) y la capa roja de congestión + el % en el hover.
    coord = {r.bus_id_modom: (r.lat, r.lon) for r in coords.itertuples()}
    src_by_bus = {str(r.bus_id_modom): str(getattr(r, "coord_source", "") or "")
                  for r in coords.itertuples()}
    snaps = list(load.index)
    hour_labels = [str(i + 1) for i in range(len(snaps))]
    load_cols = {c.replace("load_", ""): c for c in load.columns}
    pcap = float(finite.stack().quantile(0.97)) if finite.stack().size else 1.0

    seg_by_bucket: dict[str, list] = {}
    n_lines_drawn = 0
    for b in branches.itertuples():
        if b.bus0 not in coord or b.bus1 not in coord:
            continue
        n_lines_drawn += 1
        vals = [v for v in (pd.to_numeric(b.v_nom_bus0_kv, errors="coerce"),
                            pd.to_numeric(b.v_nom_bus1_kv, errors="coerce")) if pd.notna(v)]
        bucket = volt_bucket(max(vals) if vals else None)
        (la0, lo0), (la1, lo1) = coord[b.bus0], coord[b.bus1]
        seg_by_bucket.setdefault(bucket, []).append(
            (la0, lo0, la1, lo1, b.name, line_label(b.name, name_by_bus)))
    volt_buckets = [bk for bk in VOLT_ORDER
                    if bk != "LT Fuera de servicio" and bk in seg_by_bucket]

    fs_lat, fs_lon, fs_text = [], [], []
    for e in excluded.itertuples():
        a = str(getattr(e, "from_bus", "") or "").strip()
        c = str(getattr(e, "to_bus", "") or "").strip()
        if a in coord and c in coord:
            (la0, lo0), (la1, lo1) = coord[a], coord[c]
            lbl = f"{line_label(getattr(e, 'branch_id', ''), name_by_bus)}<br>fuera del modelo v1"
            fs_lat += [la0, la1, None]; fs_lon += [lo0, lo1, None]; fs_text += [lbl, lbl, None]

    bus_items = list(coord.items())

    def _line_texts(snap, bk):
        lp = loading.loc[snap]
        txt: list = []
        for (_, _, _, _, name, base) in seg_by_bucket[bk]:
            pct = float(lp.get(name, 0) or 0) * 100
            t = f"{base}<br>carga {pct:.0f}% del límite"
            txt += [t, t, None]
        return txt

    def _cong_trace(snap):
        lp = loading.loc[snap]
        lat, lon, txt = [], [], []
        for bk in volt_buckets:
            for (la0, lo0, la1, lo1, name, base) in seg_by_bucket[bk]:
                pct = float(lp.get(name, 0) or 0) * 100
                if pct >= 90:
                    t = f"{base}<br>carga {pct:.0f}% del límite"
                    lat += [la0, la1, None]; lon += [lo0, lo1, None]; txt += [t, t, None]
        return go.Scattermapbox(
            lat=lat, lon=lon, mode="lines", line=dict(width=4.5, color=CONGESTION_COLOR),
            name="Congestión ≥90%", legendrank=1007,
            text=txt, hovertemplate="%{text}<extra></extra>")

    def _marker_arrays(snap):
        pr_s, ld_s = prices.loc[snap], load.loc[snap]
        color, size, text = [], [], []
        for bus_id, _ in bus_items:
            pr = float(pr_s.get(bus_id, float("nan")))
            ld = float(ld_s.get(load_cols.get(bus_id, ""), 0) or 0) if bus_id in load_cols else 0.0
            color.append(min(pr, pcap) if pr == pr else 0)
            size.append(6 + min(ld, 200) / 200 * 22)
            nm = name_by_bus.get(bus_id, bus_id)
            approx = " · ubic. aprox." if src_by_bus.get(bus_id) == "inferred_topology" else ""
            text.append(f"<b>{nm}</b> ({bus_id}){approx}<br>"
                        f"precio: {pr:,.0f} RD$/MWh<br>carga: {ld:,.1f} MW")
        return color, size, text

    # --- figura base (abre en la hora pico) ---
    fig_map = go.Figure()
    fig_map.add_trace(go.Scattermapbox(
        lat=fs_lat, lon=fs_lon, mode="lines",
        line=dict(width=1.2, color=VOLT_COLORS["LT Fuera de servicio"]),
        name="LT Fuera de servicio", legendrank=1006,
        text=fs_text, hovertemplate="%{text}<extra></extra>"))
    for bk in volt_buckets:
        lat, lon = [], []
        for (la0, lo0, la1, lo1, _, _) in seg_by_bucket[bk]:
            lat += [la0, la1, None]; lon += [lo0, lo1, None]
        fig_map.add_trace(go.Scattermapbox(
            lat=lat, lon=lon, mode="lines", line=dict(width=2.0, color=VOLT_COLORS[bk]),
            name=bk, legendrank=1000 + VOLT_ORDER.index(bk),
            text=_line_texts(peak_snap, bk), hovertemplate="%{text}<extra></extra>"))
    fig_map.add_trace(_cong_trace(peak_snap))
    b_color, b_size, b_text = _marker_arrays(peak_snap)
    fig_map.add_trace(go.Scattermapbox(
        lat=[la for _, (la, _) in bus_items], lon=[lo for _, (_, lo) in bus_items],
        mode="markers",
        marker=dict(size=b_size, color=b_color, colorscale="Turbo", cmin=0, cmax=pcap,
                    opacity=0.9,
                    colorbar=dict(title=dict(text="RD$/MWh", font=dict(color="#222")),
                                  tickfont=dict(color="#222"), bgcolor="rgba(255,255,255,0.75)",
                                  outlinewidth=0, thickness=14, len=0.55, x=0.99)),
        text=b_text, hovertemplate="%{text}<extra></extra>",
        name="Barras (precio nodal)", legendrank=1009))

    # índices de trazas para los frames: [fs=0, buckets 1..k, cong=k+1, barras=k+2]
    n_vb = len(volt_buckets)
    idx_buckets = list(range(1, 1 + n_vb))
    idx_cong, idx_mark = 1 + n_vb, 2 + n_vb
    frames = []
    for i, snap in enumerate(snaps):
        fdata = [go.Scattermapbox(text=_line_texts(snap, bk)) for bk in volt_buckets]
        fdata.append(_cong_trace(snap))
        c, s, t = _marker_arrays(snap)
        fdata.append(go.Scattermapbox(marker=dict(color=c, size=s), text=t))
        frames.append(go.Frame(name=hour_labels[i], data=fdata,
                               traces=idx_buckets + [idx_cong, idx_mark]))
    fig_map.frames = frames

    steps = [dict(method="animate", label=hour_labels[i],
                  args=[[hour_labels[i]], dict(mode="immediate",
                        frame=dict(duration=0, redraw=True), transition=dict(duration=0))])
             for i in range(len(snaps))]
    fig_map.update_layout(
        title="Mapa SENI · precio nodal y tensión",
        mapbox=dict(style="carto-positron", center=dict(lat=18.8, lon=-70.4), zoom=6.7),
        template="plotly_dark", margin=dict(l=0, r=0, t=50, b=0), height=660,
        legend=dict(orientation="v", x=0.012, y=0.985, xanchor="left", yanchor="top",
                    bgcolor="rgba(255,255,255,0.92)", font=dict(color="#1a1a1a", size=11),
                    bordercolor="#c2c9d2", borderwidth=1,
                    title=dict(text="Leyenda", font=dict(color="#1a1a1a", size=12))),
        sliders=[dict(active=snaps.index(peak_snap), x=0.06, y=0, len=0.9,
                      pad=dict(t=6, b=2),
                      currentvalue=dict(prefix="Hora: ", font=dict(color="#e6e6e6")),
                      steps=steps)],
        updatemenus=[dict(type="buttons", direction="left", showactive=False,
                          x=0.0, y=0, xanchor="right", yanchor="bottom", pad=dict(r=8, t=4),
                          buttons=[
                              dict(label="▶", method="animate",
                                   args=[None, dict(frame=dict(duration=700, redraw=True),
                                                    fromcurrent=True, transition=dict(duration=0))]),
                              dict(label="⏸", method="animate",
                                   args=[[None], dict(mode="immediate",
                                                      frame=dict(duration=0, redraw=False))])])],
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
        "n_coords_real": sum(1 for v in src_by_bus.values() if v == "smc_match"),
        "n_coords_inferred": sum(1 for v in src_by_bus.values() if v == "inferred_topology"),
        "n_branches": len(branches),
        "n_lines_drawn": n_lines_drawn,
    }
    # datos por hora del Top-15 (para que el gráfico siga al deslizador vía JS)
    hourly_top = {}
    for i, snap in enumerate(snaps):
        labels, vals = _top15(snap)
        hourly_top[hour_labels[i]] = {"y": labels, "x": vals, "color": vals}

    figs = {"map": fig_map, "mix": fig_mix, "price": fig_price, "cong": fig_cong}
    return figs, kpis, stats, hourly_top


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
        f"<b>Geolocalización:</b> {stats['n_buses_geo']} barras con coordenadas "
        f"({stats.get('n_coords_real', 0)} reales del mapa SMC del OC + "
        f"{stats.get('n_coords_inferred', 0)} aproximadas por topología); "
        f"{stats['n_lines_drawn']} de {stats['n_branches']} ramas dibujadas en el mapa",
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
<p>Modelo PyPSA (LOPF lineal, 24 h) desde la capa canónica MODOM · mapa interactivo por hora (deslizador 1–24) · {gen_date}</p></header>
<div class="kpis">{kpi_html}</div>
<div class="grid">
 <div class="card full">{map}</div>
 <div class="card">{mix}</div>
 <div class="card">{price}</div>
 <div class="card">{cong}</div>
</div>
<section class="cond"><div class="box">{conditions}</div></section>
<footer>Artefacto analítico reproducible. La energía no suministrada y los precios
reflejan insumos provisionales (impedancias/costos) del modelo v1, no resultados
operativos finales.</footer>
{sync_script}
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
    figs, kpis, stats, hourly_top = build_figures(data)
    mix = _fuel_mix(data["gen"], data["fuel_by_gen"])
    cond = conditions_html(data, stats, mix, case_label)

    def div(fig, config: dict | None = None, div_id: str | None = None) -> str:
        cfg = {"displayModeBar": False, "responsive": True}
        if config:
            cfg.update(config)
        return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                           config=cfg, div_id=div_id)

    # El mapa se comporta como Google Maps: zoom con la rueda, arrastrar para mover,
    # doble clic para acercar y barra con zoom/encuadre. Basemap OSM (open source).
    map_config = {
        "scrollZoom": True,
        "displayModeBar": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "toImage"],
    }

    # Script que sincroniza el Top-15 y la mezcla de generación con el deslizador.
    try:
        init_hour = int(str(stats.get("peak_snap", "h_01")).split("_")[1])
    except Exception:
        init_hour = 1
    sync_script = (
        "<script>(function(){var HOURLY=" + json.dumps(hourly_top, ensure_ascii=False) + ";"
        "var INIT=" + str(init_hour) + ";"
        # Top-15 líneas: reemplaza los datos por los de la hora seleccionada
        "function updCong(h){var d=HOURLY[String(h)];var g=document.getElementById('cong-div');"
        "if(d&&g&&window.Plotly){Plotly.update(g,{x:[d.x],y:[d.y],'marker.color':[d.color]},{},[0]);}}"
        # Mezcla de generación: se llena moviendo el rango del eje X hasta la hora h
        "function updMix(h){var g=document.getElementById('mix-div');"
        "if(g&&window.Plotly){Plotly.relayout(g,{'xaxis.range':[0.5,h+0.5]});}}"
        # Precio de la barra de referencia: se llena igual que la mezcla
        "function updPrice(h){var g=document.getElementById('price-div');"
        "if(g&&window.Plotly){Plotly.relayout(g,{'xaxis.range':[0.5,h+0.5]});}}"
        "function upd(h){h=parseInt(h);if(!isNaN(h)){updCong(h);updMix(h);updPrice(h);}}"
        "function attach(){var m=document.getElementById('map-div');"
        "if(!m||!m.on){setTimeout(attach,300);return;}"
        "m.on('plotly_sliderchange',function(e){if(e&&e.step&&e.step.label!=null)upd(e.step.label);});"
        "m.on('plotly_animatingframe',function(e){if(e&&e.frame&&e.frame.name!=null)upd(e.frame.name);});"
        "setTimeout(function(){upd(INIT);},900);}"
        "if(document.readyState!=='loading')attach();else window.addEventListener('load',attach);"
        "})();</script>"
    )

    kpi_html = "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>'
        for l, v in kpis
    )
    html = _TEMPLATE.format(
        plotly_js=get_plotlyjs(),
        gen_date=_dt.date.today().isoformat(),
        kpi_html=kpi_html,
        map=div(figs["map"], map_config, div_id="map-div"),
        mix=div(figs["mix"], div_id="mix-div"),
        price=div(figs["price"], div_id="price-div"),
        cong=div(figs["cong"], div_id="cong-div"),
        conditions=cond,
        sync_script=sync_script,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path

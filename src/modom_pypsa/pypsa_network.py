"""Primera red `pypsa.Network()` real desde la capa canónica de MODOM.

Decisiones de modelado v1 (documentadas y conservadoras):

- Base por-unidad: todas las barras usan `v_nom = 1.0`. Las impedancias de MODOM
  (`r_pu`, `x_pu`) ya vienen en por-unidad, y en un LOPF linealizado los flujos
  dependen solo de reactancias relativas (la base se cancela en las restricciones
  KVL). Con `v_nom = 1` los transformadores quedan 1:1, que es lo correcto en
  por-unidad. El `v_nom_kv` real se conserva como metadato para visualización.
- Ramas: líneas y transformadores se añaden como componentes `Line` con su
  reactancia en por-unidad. Con base común esto es eléctricamente equivalente a
  una impedancia serie; la columna `branch_kind` preserva la distinción.
- Generadores: `p_nom` = capacidad estática efectiva (o disponibilidad máxima).
  `p_max_pu` por snapshot: para las unidades VRE (con perfil en
  `renewable_profiles`) se usa el **pronóstico** (`forecast_mw`, ~0 de noche para
  el solar); el resto usa `generator_availability`. Sin esto, el solar (costo ≈0)
  se despacharía de madrugada hasta su disponibilidad. `p_min` no se impone
  todavía (consistente con el despacho copperplate v1).
- Demanda: nodal, por snapshot, desde `loads_time_series`.
- Holgura: un generador `unserved` muy caro por barra con demanda garantiza
  factibilidad y entrega un KPI de energía no suministrada por nodo.

Esto NO es todavía un flujo de potencia AC; es un despacho económico con
restricciones de red (KVL + límites térmicos) linealizado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results" / "pypsa_basecase"

EPS_X = 1e-5  # reactancia mínima para que KVL sea resoluble
UNSERVED_COST = 1_000_000.0  # costo de energía no suministrada
MISSING_COST_FALLBACK = 1_000_000.0  # costo de respaldo si falta `cvp`
DUMP_COST = 1_000_000.0  # penalización por sobre-generación (holgura de balance)
COMMIT_EPS = 0.05  # MW: umbral para considerar una unidad "encendida" en el MODOM


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def resolve_paths(data_dir: Path) -> dict[str, Path]:
    return {
        "snapshots": data_dir / "snapshots" / "snapshots.csv",
        "buses": data_dir / "buses" / "buses.csv",
        "lines": data_dir / "pypsa_branch_components" / "lines_v1.csv",
        "transformers": data_dir / "pypsa_branch_components" / "transformers_v1.csv",
        "generators": data_dir / "generators" / "generators.csv",
        "availability": data_dir / "generator_availability" / "generator_availability.csv",
        "loads": data_dir / "loads_time_series" / "loads_time_series.csv",
    }


def build_network(
    data_dir: Path = DEFAULT_DATA_DIR, use_modom_commitment: bool = True
):
    """Arma la red PyPSA desde las tablas canónicas. Devuelve un `pypsa.Network`.

    Si `use_modom_commitment` y existe `modom_results/modom_generator_dispatch.csv`,
    el estado de encendido/apagado por hora se TOMA del despacho del propio MODOM
    (las unidades que el OC no commiteó quedan apagadas; las commiteadas deben dar
    >= su Pmin técnico). PyPSA resuelve el despacho económico y los flujos DENTRO de
    ese commitment. Es la vía fiel para reproducir el operativo del OC: GAMS decide
    el commitment (con contratos/reservas/seguridad que no modelamos aún) y nosotros
    reproducimos la red. Una holgura de sobre-generación mantiene el LP factible.
    """
    import pypsa

    paths = resolve_paths(data_dir)
    for name, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"Falta la tabla canónica `{name}`: {path}")

    snapshots = _read(paths["snapshots"]).sort_values(
        by="snapshot_order", key=lambda s: _num(s)
    )
    snapshot_ids = list(snapshots["snapshot_id"])

    n = pypsa.Network()
    n.set_snapshots(snapshot_ids)

    # --- Buses (v_nom = 1.0 en por-unidad; kV real como metadato) ---
    buses = _read(paths["buses"])
    n.add("Bus", list(buses["bus_id_modom"]), v_nom=1.0)
    bus_index = buses.set_index("bus_id_modom")
    n.buses["v_nom_kv"] = _num(bus_index["v_nom_kv"]).reindex(n.buses.index)
    n.buses["bus_role"] = bus_index["bus_role"].reindex(n.buses.index)
    n.buses["bus_name"] = bus_index["bus_name"].reindex(n.buses.index)
    valid_buses = set(n.buses.index)

    # --- Ramas: líneas + transformadores como Line en por-unidad ---
    def add_branches(df: pd.DataFrame, kind: str) -> int:
        added = 0
        for _, row in df.iterrows():
            bus0, bus1 = row["bus0"], row["bus1"]
            if bus0 not in valid_buses or bus1 not in valid_buses or bus0 == bus1:
                continue
            x = pd.to_numeric(row.get("x_pu_hint", ""), errors="coerce")
            r = pd.to_numeric(row.get("r_pu_hint", ""), errors="coerce")
            s_nom = pd.to_numeric(row.get("s_nom_mva_hint", ""), errors="coerce")
            x = EPS_X if pd.isna(x) or x <= 0 else float(x)
            r = 0.0 if pd.isna(r) or r < 0 else float(r)
            s_nom = 0.0 if pd.isna(s_nom) or s_nom <= 0 else float(s_nom)
            n.add(
                "Line",
                row["name"],
                bus0=bus0,
                bus1=bus1,
                x=x,
                r=r,
                s_nom=s_nom,
                s_nom_extendable=(s_nom == 0.0),
            )
            added += 1
        return added

    lines = _read(paths["lines"])
    transformers = _read(paths["transformers"])
    n_lines = add_branches(lines, "line")
    n_trafos = add_branches(transformers, "transformer")
    n.lines["branch_kind"] = "line"
    n.lines.loc[n.lines.index.isin(transformers["name"]), "branch_kind"] = "transformer"

    # --- Demanda nodal por snapshot ---
    loads = _read(paths["loads"])
    loads = loads[loads["snapshot_id"].isin(snapshot_ids)].copy()
    loads["p_set_mw"] = _num(loads["p_set_mw"]).fillna(0.0)
    load_pivot = loads.pivot_table(
        index="snapshot_id", columns="load_id", values="p_set_mw", aggfunc="sum"
    ).reindex(snapshot_ids).fillna(0.0)
    load_buses = [b for b in load_pivot.columns if b in valid_buses]

    # Factores de nodo (pérdidas marginales del MODOM): se aplican a la demanda como
    # uplift de pérdidas (effective_load = load * factor_retiro). Cierra parte del
    # sesgo del balance sin pérdidas y acerca el despacho/precios al MODOM.
    n_loss_factors = 0
    nf_path = data_dir / "modom_results" / "nodal_factors.csv"
    if nf_path.exists():
        nf = _read(nf_path).set_index("bus_id_modom")
        fr = _num(nf["factor_retiro"]) if "factor_retiro" in nf.columns else pd.Series(dtype=float)
        for b in load_buses:
            f = fr.get(b)
            if f is not None and f == f and f > 0:
                load_pivot[b] = load_pivot[b] * float(f)
                n_loss_factors += 1

    load_names = [f"load_{b}" for b in load_buses]
    n.add("Load", load_names, bus=load_buses)
    p_set = load_pivot[load_buses]
    p_set.columns = load_names
    n.loads_t.p_set = p_set

    # --- Generadores ---
    generators = _read(paths["generators"])
    availability = _read(paths["availability"])
    availability = availability[availability["snapshot_id"].isin(snapshot_ids)].copy()
    availability["available_mw"] = _num(availability["available_mw"]).fillna(0.0)
    avail_pivot = availability.pivot_table(
        index="snapshot_id", columns="generator_id", values="available_mw", aggfunc="sum"
    ).reindex(snapshot_ids)

    # Pronóstico renovable (solar/eólico): es el tope CORRECTO para las VRE.
    # La disponibilidad refleja la capacidad en servicio (no-cero de noche), así que
    # usarla como tope dejaría correr el solar de madrugada. Para las unidades con
    # perfil renovable se usa el pronóstico (~0 de noche); el resto usa disponibilidad.
    rp_path = data_dir / "renewable_profiles" / "renewable_profiles.csv"
    forecast_pivot = None
    vre_ids: set[str] = set()
    if rp_path.exists():
        rp = _read(rp_path)
        rp = rp[rp["snapshot_id"].isin(snapshot_ids)].copy()
        rp["forecast_mw"] = _num(rp["forecast_mw"]).fillna(0.0)
        forecast_pivot = rp.pivot_table(
            index="snapshot_id", columns="generator_id", values="forecast_mw", aggfunc="sum"
        ).reindex(snapshot_ids)
        vre_ids = set(forecast_pivot.columns)

    # Commitment (encendido/apagado por hora) tomado del despacho del propio MODOM.
    commit_pivot = None
    commit_path = data_dir / "modom_results" / "modom_generator_dispatch.csv"
    if use_modom_commitment and commit_path.exists():
        commit_pivot = _read(commit_path)
        commit_pivot = commit_pivot.set_index(commit_pivot.columns[0])
        commit_pivot.index = [str(i) for i in commit_pivot.index]
        commit_pivot = commit_pivot.apply(pd.to_numeric, errors="coerce").reindex(snapshot_ids)

    p_max_pu_cols: dict[str, pd.Series] = {}
    p_min_pu_cols: dict[str, pd.Series] = {}
    gen_buses: set[str] = set()
    committed_units = 0
    gen_added: list[str] = []
    for _, row in generators.iterrows():
        gid = row["generator_id"]
        bus = row["bus_id"]
        if bus not in valid_buses:
            continue
        enabled = row.get("enabled_flag", "") == "1"
        eff_pmax = pd.to_numeric(row.get("effective_pmax_mw", ""), errors="coerce")
        eff_pmax = 0.0 if pd.isna(eff_pmax) else float(eff_pmax)
        avail_series = (
            avail_pivot[gid] if gid in avail_pivot.columns else pd.Series(dtype=float)
        )
        avail_max = float(avail_series.max()) if len(avail_series) else 0.0
        p_nom = max(eff_pmax, avail_max, 0.0) if enabled else 0.0

        cost = pd.to_numeric(row.get("effective_cvp", ""), errors="coerce")
        if pd.isna(cost):
            cost = pd.to_numeric(row.get("cvp", ""), errors="coerce")
        cost = MISSING_COST_FALLBACK if pd.isna(cost) else float(cost)

        n.add(
            "Generator",
            gid,
            bus=bus,
            p_nom=p_nom,
            marginal_cost=cost,
            carrier=str(row.get("technology_group", "") or "unknown"),
        )
        gen_added.append(gid)
        gen_buses.add(bus)
        if p_nom > 0:
            if gid in vre_ids and forecast_pivot is not None:
                # VRE: tope = pronóstico renovable (0 de noche para el solar)
                cap_mw = forecast_pivot[gid].reindex(snapshot_ids).fillna(0.0)
                p_max_pu_cols[gid] = (cap_mw / p_nom).clip(0.0, 1.0)
            elif gid in avail_pivot.columns:
                # convencional: tope = disponibilidad declarada
                p_max_pu_cols[gid] = (
                    avail_series.reindex(snapshot_ids).fillna(0.0) / p_nom
                ).clip(0.0, 1.0)

            # Commitment del MODOM (solo unidades convencionales, no VRE):
            # apaga lo no-commiteado por hora; lo commiteado debe dar >= Pmin tecnico.
            if (commit_pivot is not None and gid in commit_pivot.columns
                    and gid not in vre_ids):
                com = commit_pivot[gid].fillna(0.0) > COMMIT_EPS
                base_cap = p_max_pu_cols.get(gid, pd.Series(1.0, index=snapshot_ids))
                pmax_s = base_cap.where(com, 0.0)
                eff_pmin = pd.to_numeric(row.get("effective_pmin_mw", ""), errors="coerce")
                pmin_pu = (0.0 if pd.isna(eff_pmin) or eff_pmin <= 0
                           else min(float(eff_pmin) / p_nom, 1.0))
                pmin_s = pd.Series(pmin_pu, index=snapshot_ids).where(com, 0.0)
                p_max_pu_cols[gid] = pmax_s
                p_min_pu_cols[gid] = pd.concat([pmin_s, pmax_s], axis=1).min(axis=1)
                committed_units += 1

    if p_max_pu_cols:
        n.generators_t.p_max_pu = pd.DataFrame(p_max_pu_cols, index=snapshot_ids)
    if p_min_pu_cols:
        n.generators_t.p_min_pu = pd.DataFrame(p_min_pu_cols, index=snapshot_ids).fillna(0.0)

    # --- Holgura: generador de energía no suministrada por barra con demanda ---
    total_peak_load = float(load_pivot.sum(axis=1).max()) if len(load_pivot) else 0.0
    unserved_names = [f"unserved_{b}" for b in load_buses]
    n.add(
        "Generator",
        unserved_names,
        bus=load_buses,
        p_nom=max(total_peak_load, 1.0),
        marginal_cost=UNSERVED_COST,
        carrier="unserved",
    )

    # --- Holgura de sobre-generación: si los Pmin forzados (commitment del MODOM)
    # superan la demanda en alguna hora (el balance sin pérdidas no la absorbe),
    # este "dump" la disipa con penalización. Generador con p en [-p_nom, 0] y costo
    # negativo, de modo que disipar suma penalización al objetivo. ---
    if p_min_pu_cols:
        dump_buses = sorted(gen_buses | set(load_buses))
        dump_names = [f"dump_{b}" for b in dump_buses]
        n.add(
            "Generator",
            dump_names,
            bus=dump_buses,
            p_nom=max(total_peak_load, 1.0),
            p_min_pu=-1.0,
            p_max_pu=0.0,
            marginal_cost=-DUMP_COST,
            carrier="dump",
        )

    n.meta = {
        "model": "linear_lopf_v2_modom_commitment" if committed_units else "linear_lopf_v1",
        "per_unit_base_note": "v_nom=1.0 en todas las barras; impedancias en por-unidad de MODOM.",
        "counts": {
            "buses": int(len(n.buses)),
            "lines_added": int(n_lines),
            "transformers_added": int(n_trafos),
            "generators_added": int(len(gen_added)),
            "vre_with_forecast": int(sum(1 for g in gen_added if g in vre_ids)),
            "load_buses": int(len(load_buses)),
            "committed_from_modom": int(committed_units),
            "loads_with_nodal_factor": int(n_loss_factors),
        },
        "vre_note": "Las unidades con perfil renovable se capan por pronóstico "
                    "(forecast_mw), no por disponibilidad; el resto por disponibilidad.",
        "commitment_note": (
            "Encendido/apagado por hora tomado del despacho del MODOM (S_DESPACHOM); "
            "las commiteadas dan >= su Pmin tecnico. PyPSA resuelve despacho economico "
            "y flujos dentro de ese commitment."
            if committed_units else "Sin commitment del MODOM (despacho libre por merito)."
        ),
    }
    return n


def solve_network(n, solver_name: str = "highs"):
    n.optimize(solver_name=solver_name)
    return n


def summarize(n) -> dict[str, object]:
    real_gens = n.generators.index[~n.generators.carrier.isin(["unserved", "dump"])]
    unserved_gens = n.generators.index[n.generators.carrier == "unserved"]
    gen_p = n.generators_t.p

    served = gen_p[real_gens].sum(axis=1)
    unserved = gen_p[unserved_gens].sum(axis=1) if len(unserved_gens) else served * 0.0
    total_load = n.loads_t.p_set.sum(axis=1)

    # despacho por tecnología (carrier) sumado en el horizonte
    by_carrier = (
        gen_p[real_gens]
        .T.groupby(n.generators.loc[real_gens, "carrier"])
        .sum()
        .T.sum()
        .to_dict()
    )

    # carga de líneas (|flujo| / s_nom) máxima en el horizonte
    line_loading = {}
    if len(n.lines):
        s_nom = n.lines["s_nom"].replace(0.0, pd.NA)
        loading = n.lines_t.p0.abs().div(s_nom, axis=1)
        line_loading = {
            "lines_above_90pct_peak": int((loading.max() > 0.9).sum()),
            "max_line_loading_pu": round(float(loading.max().max()), 4) if loading.size else 0.0,
        }

    return {
        "model": n.meta.get("model"),
        "objective": float(n.objective) if n.objective is not None else None,
        "snapshots": int(len(n.snapshots)),
        "total_load_mwh": round(float(total_load.sum()), 3),
        "served_mwh": round(float(served.sum()), 3),
        "unserved_mwh": round(float(unserved.sum()), 3),
        "peak_load_mw": round(float(total_load.max()), 3),
        "peak_unserved_mw": round(float(unserved.max()), 3),
        "dispatch_by_carrier_mwh": {str(k): round(float(v), 3) for k, v in by_carrier.items()},
        **line_loading,
        "counts": n.meta.get("counts", {}),
    }


def export_results(n, outdir: Path = DEFAULT_RESULTS_DIR) -> dict[str, object]:
    outdir.mkdir(parents=True, exist_ok=True)
    summary = summarize(n)

    # se excluye el "dump" (holgura de sobre-generación) de los resultados publicados
    keep_gens = n.generators.index[n.generators.carrier != "dump"]
    n.generators_t.p[keep_gens].round(4).to_csv(outdir / "generation_by_snapshot.csv")
    n.loads_t.p_set.round(4).to_csv(outdir / "load_by_snapshot.csv")
    if len(n.lines):
        n.lines_t.p0.round(4).to_csv(outdir / "line_flows_by_snapshot.csv")
        loading = n.lines_t.p0.abs().div(n.lines["s_nom"].replace(0.0, pd.NA), axis=1)
        loading.round(4).to_csv(outdir / "line_loading_by_snapshot.csv")
    n.buses_t.marginal_price.round(4).to_csv(outdir / "nodal_prices_by_snapshot.csv")
    (outdir / "pypsa_basecase_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary

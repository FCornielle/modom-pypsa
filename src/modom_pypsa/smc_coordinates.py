"""Cruza los puntos SMC geolocalizados del OC con las barras del modelo de red.

El mapa del OC (ver `scripts/scrape_oc_smc.py`) entrega ~535 puntos con
`lat, lon, punto, tipo, tension, agente`, pero el `punto` es un nombre descriptivo,
no un código de barra. Aquí se resuelve el nombre del punto a una barra del modelo
usando tres fuentes de nombres ya presentes en la capa canónica:

- nombres de barra (`buses.csv`: `bus_name`, `bus_name_legacy`),
- nombres de generador (`generators.csv`: `generator_name`),
- nombres de carga del registro SMC (`smc_load_registry.csv`: `load_name_examples`),
  que además trae `resolved_bus_id`.

El emparejamiento es por nombre normalizado (sin acentos, mayúsculas, sin palabras
genéricas como PARQUE/EOLICO/TERMINAL) con dos niveles:

- `exact`: el nombre normalizado coincide exactamente (alta confianza),
- `fuzzy`: similitud de tokens (Jaccard) por encima de un umbral (confianza media).

Salida: cada barra emparejada recibe lat/lon (promedio si varios puntos del OC caen
en la misma barra, p.ej. turbinas T1/T2 de un mismo parque).
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
DEFAULT_EXTERNAL_DIR = Path(__file__).resolve().parents[2] / "data" / "external"
DEFAULT_OC_CSV = DEFAULT_EXTERNAL_DIR / "oc_smc_points.csv"

FUZZY_THRESHOLD = 0.5

_STOPWORDS = {
    "PARQUE", "EOLICO", "SOLAR", "FOTOVOLTAICO", "CENTRAL", "TERMOELECTRICA",
    "TERMINAL", "TER", "RETIRO", "UNR", "GENERACION", "DE", "DEL", "LA", "EL",
    "LOS", "LAS", "Y", "VIRTUAL", "TG", "TV", "AT", "KV", "GRUPO", "PLANTA",
    "SE", "S", "A", "DISTRIBUCION", "ENERGY", "POWER", "S R L", "SRL",
}
_UNIT_TOKEN = re.compile(r"^[A-Z]+\d+$")  # T01, T1, G10, KPS... (sufijos de unidad)


def clean(value: object) -> str:
    return str(value or "").strip()


def normalize(text: str) -> str:
    out = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    out = re.sub(r"[^A-Za-z0-9 ]", " ", out.upper())
    return re.sub(r"\s+", " ", out).strip()


def token_set(text: str) -> frozenset[str]:
    toks = set()
    for tok in normalize(text).split():
        if tok in _STOPWORDS or len(tok) <= 1 or _UNIT_TOKEN.match(tok):
            continue
        toks.add(tok)
    return frozenset(toks)


def to_float(value: object) -> float | None:
    text = clean(value)
    if not text:
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)[A-Za-z]*", text)
    return float(m.group(1)) if m else None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Candidate:
    __slots__ = ("name", "norm", "tokens", "bus_id", "source")

    def __init__(self, name: str, bus_id: str, source: str) -> None:
        self.name = name
        self.norm = normalize(name)
        self.tokens = token_set(name)
        self.bus_id = bus_id
        self.source = source


def build_candidates(
    buses: list[dict[str, str]],
    generators: list[dict[str, str]],
    registry: list[dict[str, str]],
) -> list[Candidate]:
    """Lista de candidatos (nombre -> barra) desde las tres fuentes."""
    valid_buses = {clean(b["bus_id_modom"]) for b in buses}
    cands: list[Candidate] = []
    for b in buses:
        bus_id = clean(b["bus_id_modom"])
        for nm in (b.get("bus_name"), b.get("bus_name_legacy")):
            if clean(nm):
                cands.append(Candidate(clean(nm), bus_id, "bus_name"))
    for g in generators:
        bus_id = clean(g.get("bus_id"))
        nm = clean(g.get("generator_name"))
        if nm and bus_id in valid_buses:
            cands.append(Candidate(nm, bus_id, "generator_name"))
    for r in registry:
        bus_id = clean(r.get("resolved_bus_id"))
        if bus_id not in valid_buses:
            continue
        for nm in re.findall(r"'([^']+)'", r.get("load_name_examples", "")):
            if clean(nm):
                cands.append(Candidate(clean(nm), bus_id, "registry_load_name"))
    return cands


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter else 0.0


def match_point(
    punto: str,
    candidates: list[Candidate],
    exact_index: dict[str, Candidate],
) -> tuple[Candidate | None, str, float]:
    norm = normalize(punto)
    if norm in exact_index:
        return exact_index[norm], "exact", 1.0
    ptoks = token_set(punto)
    best: Candidate | None = None
    best_score = 0.0
    for cand in candidates:
        score = _jaccard(ptoks, cand.tokens)
        if score > best_score:
            best, best_score = cand, score
    if best is not None and best_score >= FUZZY_THRESHOLD:
        return best, "fuzzy", round(best_score, 3)
    return None, "unmatched", round(best_score, 3)


def join_coordinates(
    data_dir: Path = DEFAULT_DATA_DIR,
    oc_csv: Path = DEFAULT_OC_CSV,
) -> dict[str, object]:
    buses = read_csv(data_dir / "buses" / "buses.csv")
    generators = read_csv(data_dir / "generators" / "generators.csv")
    registry_path = data_dir / "loads_time_series" / "smc_load_registry.csv"
    registry = read_csv(registry_path) if registry_path.exists() else []
    oc_points = read_csv(oc_csv)

    candidates = build_candidates(buses, generators, registry)
    # Índice exacto: prioriza bus_name > registry_load_name > generator_name.
    priority = {"bus_name": 0, "registry_load_name": 1, "generator_name": 2}
    exact_index: dict[str, Candidate] = {}
    for cand in sorted(candidates, key=lambda c: priority.get(c.source, 9)):
        exact_index.setdefault(cand.norm, cand)

    # Emparejar cada punto del OC -> barra; acumular coords por barra.
    per_bus: dict[str, dict[str, object]] = {}
    point_rows: list[dict[str, object]] = []
    method_counts = {"exact": 0, "fuzzy": 0, "unmatched": 0}
    for pt in oc_points:
        punto = clean(pt.get("punto"))
        lat = to_float(pt.get("lat"))
        lon = to_float(pt.get("lon"))
        cand, method, score = match_point(punto, candidates, exact_index)
        method_counts[method] += 1
        point_rows.append(
            {
                "oc_punto": punto,
                "oc_tipo": clean(pt.get("tipo")),
                "oc_tension": clean(pt.get("tension")),
                "oc_agente": clean(pt.get("agente")),
                "lat": lat if lat is not None else "",
                "lon": lon if lon is not None else "",
                "matched_bus_id": cand.bus_id if cand else "",
                "matched_name": cand.name if cand else "",
                "match_source": cand.source if cand else "",
                "match_method": method,
                "match_score": score,
            }
        )
        if cand is None or lat is None or lon is None:
            continue
        agg = per_bus.setdefault(
            cand.bus_id,
            {"lat_sum": 0.0, "lon_sum": 0.0, "n": 0, "best_method": method,
             "best_score": score, "puntos": []},
        )
        agg["lat_sum"] += lat
        agg["lon_sum"] += lon
        agg["n"] += 1
        agg["puntos"].append(punto)
        if (method == "exact" and agg["best_method"] != "exact") or score > agg["best_score"]:
            agg["best_method"] = method
            agg["best_score"] = score

    # Filas de barras enriquecidas (todas las barras; coords donde haya match).
    bus_rows: list[dict[str, object]] = []
    for b in buses:
        bus_id = clean(b["bus_id_modom"])
        agg = per_bus.get(bus_id)
        if agg and agg["n"]:
            lat = round(agg["lat_sum"] / agg["n"], 6)
            lon = round(agg["lon_sum"] / agg["n"], 6)
        else:
            lat = lon = ""
        bus_rows.append(
            {
                "bus_id_modom": bus_id,
                "bus_name": clean(b.get("bus_name")),
                "v_nom_kv": clean(b.get("v_nom_kv")),
                "bus_role": clean(b.get("bus_role")),
                "lat": lat,
                "lon": lon,
                "oc_point_count": agg["n"] if agg else 0,
                "match_method": agg["best_method"] if agg else "",
                "match_score": agg["best_score"] if agg else "",
                "oc_puntos": "; ".join(agg["puntos"]) if agg else "",
            }
        )

    buses_with_coords = sum(1 for r in bus_rows if r["lat"] != "")
    summary = {
        "oc_points_total": len(oc_points),
        "oc_points_matched_exact": method_counts["exact"],
        "oc_points_matched_fuzzy": method_counts["fuzzy"],
        "oc_points_unmatched": method_counts["unmatched"],
        "buses_total": len(bus_rows),
        "buses_with_coordinates": buses_with_coords,
        "buses_without_coordinates": len(bus_rows) - buses_with_coords,
        "notes": [
            "El `punto` del OC se resuelve por nombre (exact/fuzzy) a una barra.",
            "Si varios puntos OC caen en la misma barra, lat/lon se promedian.",
            "Un match `fuzzy` con score bajo debe auditarse antes de usarse en producción.",
        ],
    }
    return {"bus_rows": bus_rows, "point_rows": point_rows, "summary": summary}


def export_coordinates(
    data_dir: Path = DEFAULT_DATA_DIR,
    oc_csv: Path = DEFAULT_OC_CSV,
    outdir: Path = DEFAULT_EXTERNAL_DIR,
) -> dict[str, object]:
    payload = join_coordinates(data_dir, oc_csv)
    outdir.mkdir(parents=True, exist_ok=True)

    def write(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write(
        outdir / "buses_with_coords.csv",
        payload["bus_rows"],
        ["bus_id_modom", "bus_name", "v_nom_kv", "bus_role", "lat", "lon",
         "oc_point_count", "match_method", "match_score", "oc_puntos"],
    )
    write(
        outdir / "smc_point_matches.csv",
        payload["point_rows"],
        ["oc_punto", "oc_tipo", "oc_tension", "oc_agente", "lat", "lon",
         "matched_bus_id", "matched_name", "match_source", "match_method", "match_score"],
    )
    (outdir / "smc_coordinates_summary.json").write_text(
        json.dumps(payload["summary"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload["summary"]

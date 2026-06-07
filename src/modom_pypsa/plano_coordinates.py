"""Georreferenciacion de subestaciones desde el plano geografico del OC.

El plano (`Plano RD Lineas Transmision *.pdf`) es vectorial: cada etiqueta de
subestacion tiene una posicion (x, y) en la pagina. La pagina NO es una
proyeccion cartografica conocida, asi que en vez de asumir una, calibramos una
transformacion afin (x, y) -> (lon, lat) ANCLANDOLA en los buses que ya tienen
coordenadas reales del OC (coord_source == "smc_match"). Con decenas de pares
ancla el ajuste por minimos cuadrados (con rechazo de outliers tipo RANSAC)
absorbe el desfase sistematico etiqueta<->punto y cualquier rotacion/escala.

Luego aplicamos esa transformacion SOLO a los buses sin coordenadas reales
(inferred_topology o sin coord), para sacarlos "del mar" sin tocar los 305 que
ya estan bien.
"""
from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from pathlib import Path

from .smc_coordinates import normalize, token_set, _jaccard

# Centro aproximado de RD para convertir grados -> km en los diagnosticos.
_LAT0 = 18.8
_KM_PER_LAT = 111.0
_KM_PER_LON = 111.0 * 0.9466  # cos(18.8 deg)


@dataclass
class Label:
    text: str
    x: float
    y: float
    tokens: frozenset[str]


def find_plano_pdf(data_dir: Path) -> Path:
    cands = [Path(p) for p in glob.glob(str(data_dir / "**" / "*.pdf"), recursive=True)]
    cands = [p for p in cands if "plano" in p.name.lower()]
    if not cands:
        raise FileNotFoundError(f"No encontre 'Plano*.pdf' bajo {data_dir}")
    # el mas reciente por nombre (fecha al final) suele ser el ultimo ordenado
    return sorted(cands)[-1]


def extract_labels(pdf_path: Path) -> list[Label]:
    """Agrupa las palabras vectoriales del plano en etiquetas de subestacion.

    Une palabras contiguas en la misma linea (mismo `top`, separacion horizontal
    menor a ~0.8x la altura del texto) para reconstruir nombres multi-palabra.
    """
    import pdfplumber

    with pdfplumber.open(str(pdf_path)) as pdf:
        words = pdf.pages[0].extract_words()
    # ordenar por linea (top) y luego x
    ws = sorted(words, key=lambda w: (round(w["top"] / 6.0), w["x0"]))
    labels: list[Label] = []
    cur: list[dict] = []

    def flush() -> None:
        if not cur:
            return
        text = " ".join(w["text"] for w in cur).strip()
        x = sum((w["x0"] + w["x1"]) / 2 for w in cur) / len(cur)
        y = sum((w["top"] + w["bottom"]) / 2 for w in cur) / len(cur)
        toks = token_set(text)
        if toks:
            labels.append(Label(text, x, y, toks))
        cur.clear()

    for w in ws:
        h = w["bottom"] - w["top"]
        if cur:
            prev = cur[-1]
            same_line = abs(w["top"] - prev["top"]) <= 0.4 * h
            gap = w["x0"] - prev["x1"]
            if same_line and gap <= 0.5 * h:
                cur.append(w)
                continue
        flush()
        cur.append(w)
    flush()
    return labels


def _affine_fit(xy: list[tuple[float, float]], target: list[float]):
    """Ajuste afin t = a*x + b*y + c por minimos cuadrados (sin numpy externo)."""
    import numpy as np

    P = np.array([[x, y, 1.0] for x, y in xy], dtype=float)
    coef, *_ = np.linalg.lstsq(P, np.array(target, dtype=float), rcond=None)
    return coef


@dataclass
class Affine:
    lon: tuple[float, float, float]
    lat: tuple[float, float, float]

    def apply(self, x: float, y: float) -> tuple[float, float]:
        a, b, c = self.lon
        d, e, f = self.lat
        return (a * x + b * y + c, d * x + e * y + f)


def fit_affine_ransac(
    pairs: list[tuple[float, float, float, float]],
    *,
    tol_km: float = 12.0,
    min_inliers: int = 8,
) -> tuple[Affine, list[bool], float]:
    """Ajusta (x,y)->(lon,lat) con rechazo iterativo de outliers.

    `pairs`: lista de (x, y, lon, lat). Devuelve (Affine, mascara_inliers, rms_km).
    """
    import numpy as np

    idx = list(range(len(pairs)))
    for _ in range(12):
        xy = [(pairs[i][0], pairs[i][1]) for i in idx]
        clon = _affine_fit(xy, [pairs[i][2] for i in idx])
        clat = _affine_fit(xy, [pairs[i][3] for i in idx])
        aff = Affine(tuple(clon), tuple(clat))
        errs = []
        for i in range(len(pairs)):
            x, y, lon, lat = pairs[i]
            plon, plat = aff.apply(x, y)
            dx = (plon - lon) * _KM_PER_LON
            dy = (plat - lat) * _KM_PER_LAT
            errs.append((dx * dx + dy * dy) ** 0.5)
        new_idx = [i for i in range(len(pairs)) if errs[i] <= tol_km]
        if len(new_idx) < min_inliers:
            # afloja: quedate con el mejor 70%
            order = sorted(range(len(pairs)), key=lambda i: errs[i])
            new_idx = order[: max(min_inliers, int(0.7 * len(pairs)))]
        if set(new_idx) == set(idx):
            break
        idx = new_idx
    inlier_errs = [errs[i] for i in idx]
    rms = (sum(e * e for e in inlier_errs) / len(inlier_errs)) ** 0.5
    mask = [i in set(idx) for i in range(len(pairs))]
    return aff, mask, rms


# Caja terrestre aproximada de RD (lon_min, lon_max, lat_min, lat_max).
RD_BBOX = (-72.05, -68.30, 17.55, 20.05)


@dataclass
class Anchor:
    bus_id: str
    name: str
    x: float
    y: float
    lon: float
    lat: float


def _idw(x: float, y: float, pool: list[Anchor], k: int = 4) -> tuple[float, float]:
    ds = sorted(((((x - a.x) ** 2 + (y - a.y) ** 2) ** 0.5, a) for a in pool),
                key=lambda t: t[0])[:k]
    if ds[0][0] < 1e-6:
        return ds[0][1].lon, ds[0][1].lat
    ws = [1.0 / d ** 2 for d, _ in ds]
    s = sum(ws)
    lon = sum(w * a.lon for w, (_, a) in zip(ws, ds)) / s
    lat = sum(w * a.lat for w, (_, a) in zip(ws, ds)) / s
    return lon, lat


def _km(lon1, lat1, lon2, lat2):
    return (((lon1 - lon2) * _KM_PER_LON) ** 2 + ((lat1 - lat2) * _KM_PER_LAT) ** 2) ** 0.5


def clean_anchor_pool(pool: list[Anchor], *, max_loo_km: float = 18.0,
                      k: int = 4) -> list[Anchor]:
    """Quita anclas cuya posicion en el plano es inconsistente con sus vecinas.

    Estas suelen venir de etiquetas mal fusionadas o de plantas nombradas como un
    pueblo pero ubicadas en otro sitio. Se eliminan de forma iterativa por error
    leave-one-out (IDW de las demas).
    """
    cur = list(pool)
    for _ in range(20):
        worst = None
        for i, a in enumerate(cur):
            others = [b for j, b in enumerate(cur) if j != i]
            if len(others) < k:
                continue
            plon, plat = _idw(a.x, a.y, others, k)
            e = _km(plon, plat, a.lon, a.lat)
            if worst is None or e > worst[0]:
                worst = (e, i)
        if worst is None or worst[0] <= max_loo_km:
            break
        cur.pop(worst[1])
    return cur


def georeference_gap_buses(
    buses: list[dict],
    labels: list[Label],
    *,
    min_jaccard: float = 0.85,
    k: int = 4,
    sanity_km: float = 40.0,
) -> tuple[dict[str, tuple[float, float]], dict]:
    """Asigna (lon, lat) a buses sin coordenada real usando el plano.

    Estrategia:
      1. Empareja etiquetas del plano con buses por tokens.
      2. Construye el pool de anclas con los buses `smc_match` (coords reales) que
         tienen etiqueta, y lo auto-depura (`clean_anchor_pool`).
      3. Para cada bus SIN coord real pero CON etiqueta, predice por IDW local.
      4. Recorta a la caja de RD y descarta predicciones que difieran del afin
         global por mas de `sanity_km` (tope de cordura para la cola).

    Devuelve (coords_por_bus, stats). Nunca toca buses `smc_match`.
    """
    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    matches = match_labels_to_buses(labels, buses, min_jaccard=min_jaccard)
    pool: list[Anchor] = []
    for b in buses:
        bid = (b.get("bus_id_modom") or "").strip()
        if b.get("coord_source") == "smc_match" and bid in matches:
            lat, lon = f(b.get("lat")), f(b.get("lon"))
            if lat is not None and lon is not None:
                lab = matches[bid]
                pool.append(Anchor(bid, b.get("bus_name") or "", lab.x, lab.y, lon, lat))
    pool_raw = len(pool)
    pool = clean_anchor_pool(pool, k=k)

    # afin global sobre el pool depurado (tope de cordura)
    aff = None
    if len(pool) >= 6:
        aff, _, _ = fit_affine_ransac(
            [(a.x, a.y, a.lon, a.lat) for a in pool], min_inliers=6)

    lon_min, lon_max, lat_min, lat_max = RD_BBOX
    out: dict[str, tuple[float, float]] = {}
    skipped_sanity = 0
    for b in buses:
        bid = (b.get("bus_id_modom") or "").strip()
        if b.get("coord_source") == "smc_match":
            continue
        if bid not in matches:
            continue
        lab = matches[bid]
        lon, lat = _idw(lab.x, lab.y, pool, k=k)
        if aff is not None:
            alon, alat = aff.apply(lab.x, lab.y)
            if _km(lon, lat, alon, alat) > sanity_km:
                skipped_sanity += 1
                continue
        lon = min(max(lon, lon_min), lon_max)
        lat = min(max(lat, lat_min), lat_max)
        out[bid] = (lon, lat)
    stats = {
        "labels": len(labels),
        "pool_raw": pool_raw,
        "pool_clean": len(pool),
        "placed": len(out),
        "skipped_sanity": skipped_sanity,
    }
    return out, stats


def match_labels_to_buses(
    labels: list[Label],
    buses: list[dict],
    *,
    min_jaccard: float = 0.6,
) -> dict[str, Label]:
    """Mapea bus_id -> Label del plano por solape de tokens del nombre.

    Para cada bus toma la etiqueta con mayor Jaccard de tokens (>= umbral).
    """
    best: dict[str, tuple[float, Label]] = {}
    for b in buses:
        name = (b.get("bus_name") or "").strip()
        if not name:
            continue
        bt = token_set(name)
        if not bt:
            continue
        bus_id = (b.get("bus_id_modom") or "").strip()
        for lab in labels:
            j = _jaccard(bt, lab.tokens)
            if j >= min_jaccard and (bus_id not in best or j > best[bus_id][0]):
                best[bus_id] = (j, lab)
    return {k: v[1] for k, v in best.items()}

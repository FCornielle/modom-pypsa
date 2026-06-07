"""Tests de la geometria de georreferenciacion del plano (sin depender del PDF)."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

pytest.importorskip("numpy")

from modom_pypsa import plano_coordinates as pc


def _true(x, y):
    # transformacion afin conocida: x->lon, y->lat (y invertida como en el plano)
    lon = -72.0 + 0.001 * x
    lat = 20.0 - 0.0009 * y
    return lon, lat


def _pairs():
    pts = [(100, 200), (3000, 300), (500, 2500), (3500, 2400), (2000, 1500),
           (800, 1800), (2600, 900), (1500, 2200)]
    return [(x, y, *_true(x, y)) for x, y in pts]


def test_affine_recovers_known_transform():
    aff, mask, rms = pc.fit_affine_ransac(_pairs(), min_inliers=6)
    assert all(mask)
    assert rms < 0.5  # km
    lon, lat = aff.apply(1800, 1200)
    elon, elat = _true(1800, 1200)
    assert abs(lon - elon) < 1e-3 and abs(lat - elat) < 1e-3


def test_ransac_rejects_outlier():
    pairs = _pairs()
    pairs.append((2000, 1500, -50.0, 5.0))  # ancla disparatada
    aff, mask, rms = pc.fit_affine_ransac(pairs, min_inliers=6)
    assert mask[-1] is False
    assert rms < 0.5


def _dense_pool():
    # malla densa de escala geografica pequena: vecinos a ~1-2 km, asi el IDW
    # leave-one-out de los puntos buenos es preciso (como en el plano real, que
    # tiene >100 anclas agrupadas). lon/lat varian poco con x/y a proposito.
    pool = []
    for i in range(10):
        for j in range(10):
            x, y = 100 + i * 100, 100 + j * 100
            lon, lat = -70.0 + 5e-5 * x, 19.0 - 5e-5 * y
            pool.append(pc.Anchor(f"b{i}{j}", "", x, y, lon, lat))
    return pool


def test_clean_anchor_pool_drops_inconsistent():
    pool = _dense_pool()
    bad = pc.Anchor("bad", "", 500, 500, -50.0, 5.0)  # coord disparatada
    cleaned = pc.clean_anchor_pool(pool + [bad], max_loo_km=18.0)
    assert all(a.bus_id != "bad" for a in cleaned)
    assert len(cleaned) >= 0.9 * len(pool)


def test_idw_matches_nearby_anchor():
    pool = [pc.Anchor(f"b{i}", "", x, y, *_true(x, y))
            for i, (x, y, _, _) in enumerate(_pairs())]
    # punto pegado a un ancla -> debe devolver ~su coordenada
    lon, lat = pc._idw(101, 201, pool, k=4)
    elon, elat = _true(100, 200)
    assert pc._km(lon, lat, elon, elat) < 5.0

"""Smoke tests de la plataforma web (FastAPI TestClient).

No requieren el export DIgSILENT: usan lo que haya en results/runs (o estado vacío).
Se saltan si faltan las dependencias web.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from modom_pypsa.webapp.app import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("url", [
    "/", "/pypsa", "/ac", "/ac?metric=costo", "/audit", "/audit?kind=linea",
    "/metodologia", "/coming/datasets",
])
def test_pages_ok(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert "GridLab" in r.text  # shell renderizado


def test_sidebar_sections(client):
    t = client.get("/").text
    for label in ("MODOM", "PyPSA", "Pandapower", "Auditoría", "Metodología"):
        assert label in t


def test_removed_pages_are_gone(client):
    assert client.get("/projects").status_code == 404
    assert client.get("/runs").status_code == 404

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
    "/", "/runs", "/ac", "/audit", "/audit?kind=linea", "/audit?kind=generador",
    "/projects", "/coming/datasets",
])
def test_pages_ok(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert "GridLab" in r.text  # shell renderizado


def test_dashboard_has_sidebar_sections(client):
    t = client.get("/").text
    for label in ("Dashboard", "Corridas", "Verificación AC", "Auditoría", "Proyectos"):
        assert label in t


def test_create_project_roundtrip(client, tmp_path, monkeypatch):
    from modom_pypsa.webapp import data_access as da
    monkeypatch.setattr(da, "PROJECTS_DIR", tmp_path)
    r = client.post("/projects", data={"name": "Prueba AC", "description": "x",
                                       "considerations": "pico"}, follow_redirects=False)
    assert r.status_code == 303
    projs = da.list_projects()
    assert any(p["name"] == "Prueba AC" for p in projs)

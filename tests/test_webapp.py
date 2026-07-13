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
    "/", "/milp", "/metodologia", "/coming/datasets",
])
def test_pages_ok(client, url):
    r = client.get(url)
    assert r.status_code == 200
    assert "GridLab" in r.text  # shell renderizado


def test_home_is_optimizer(client):
    """La página principal es el Optimizador; el nav solo tiene Optimizador + Metodología."""
    t = client.get("/").text
    assert "Consideraciones del escenario" in t          # es el optimizador
    for label in ("Optimizador", "Metodología"):
        assert label in t
    # las pestañas retiradas ya no están en la navegación
    for gone in ("PyPSA · Modelo", "Pandapower · Modelo AC", "MODOM · PDD"):
        assert gone not in t


def test_removed_pages_are_gone(client):
    assert client.get("/projects").status_code == 404
    assert client.get("/runs").status_code == 404
    # las 4 pestañas retiradas ya no responden en su ruta canónica
    for gone in ("/pypsa", "/ac", "/audit"):
        assert client.get(gone).status_code == 404


def test_milp_status_partial(client):
    """El endpoint de status devuelve el fragmento HTMX (no una página completa)."""
    r = client.get("/milp/status")
    assert r.status_code == 200
    assert "milp-run" in r.text          # clase del fragmento
    assert "GridLab" not in r.text       # es un partial, no la base


def test_milp_page_has_configurator(client):
    """La página del optimizador trae el configurador de consideraciones y el form de run."""
    r = client.get("/milp")
    assert r.status_code == 200
    assert "Consideraciones del escenario" in r.text
    assert 'hx-post="/milp/run"' in r.text


def test_milp_editor_and_scenarios(client):
    """La página trae editor de variables por generador, sliders globales y serializador."""
    r = client.get("/milp")
    assert r.status_code == 200
    for token in ("Variables del escenario", "gen-row", "g-demand", "buildOverrides",
                  "milp-inspector", "plotly_click", "data-tip"):
        assert token in r.text


def test_milp_inspect_and_compare(client):
    r = client.get("/milp/inspect?bus=WPALAF")
    assert r.status_code == 200 and "inspector" in r.text
    # comparar sin escenarios -> mensaje de faltantes (no error)
    r2 = client.get("/milp/compare?a=nope&b=nada")
    assert r2.status_code == 200 and "Faltan escenarios" in r2.text


def test_milp_job_robust_on_error(monkeypatch):
    """Un fallo en el job pasa a 'error', nunca deja 'running' fantasma (anti-cuelgue)."""
    import modom_pypsa.pypsa_milp as milp
    import modom_pypsa.webapp.app as A

    def boom(*a, **k):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(milp, "build_milp_network", boom)
    A._MILP_JOB.update(status="running", started=0.0, cancel=False)
    A._run_milp_job({"reserves": True, "flowgates": True, "pors": 3, "min_sync": 0,
                     "gap": 2, "time": 60})
    assert A._MILP_JOB["status"] == "error"
    assert "fallo simulado" in (A._MILP_JOB["error"] or "")
    A._MILP_JOB.update(status="idle", error=None)


def test_milp_watchdog_flags_stuck_job():
    """El watchdog convierte un job colgado (elapsed > time_limit+45) en error."""
    import time as _t
    import modom_pypsa.webapp.app as A
    A._MILP_JOB.update(status="running", started=_t.time() - 1000, time_limit=60.0)
    job = A._live_job()
    assert job["status"] == "error"
    A._MILP_JOB.update(status="idle", error=None)

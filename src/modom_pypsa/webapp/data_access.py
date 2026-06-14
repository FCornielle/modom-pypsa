"""Acceso a los artefactos de la plataforma: corridas y proyectos (en disco, sin BD).

Modelo:
- Corridas  `results/runs/<run_id>/manifest.json` (+ iterations.json, dispatch.csv,
  ac_bus_voltages.csv, ac_branch_loading.csv, loss_factors_final.csv).
- Proyectos `results/projects/<project_id>.json`.

`ensure_seed_runs()` envuelve las salidas existentes del pipeline (`results/pypsa_basecase`,
`data/processed/ac_modom`) como corridas, para que la plataforma nunca arranque vacía.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = REPO_ROOT / "results" / "runs"
PROJECTS_DIR = REPO_ROOT / "results" / "projects"


# ---------------------------------------------------------------- corridas
def list_runs() -> list[dict]:
    """Manifests de todas las corridas, más recientes primero."""
    runs = []
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            mf = d / "manifest.json"
            if mf.exists():
                try:
                    runs.append(json.loads(mf.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    continue
    runs.sort(key=lambda m: m.get("started", ""), reverse=True)
    return runs


def get_run(run_id: str) -> dict | None:
    mf = RUNS_DIR / run_id / "manifest.json"
    if not mf.exists():
        return None
    m = json.loads(mf.read_text(encoding="utf-8"))
    it = RUNS_DIR / run_id / "iterations.json"
    if it.exists():
        m["iterations"] = json.loads(it.read_text(encoding="utf-8"))
    return m


def run_csv(run_id: str, name: str) -> pd.DataFrame:
    p = RUNS_DIR / run_id / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def latest_run(run_type: str | None = None) -> dict | None:
    for m in list_runs():
        if run_type is None or m.get("type") == run_type:
            return m
    return None


def run_counts() -> dict[str, int]:
    runs = list_runs()
    c = {"total": len(runs), "completed": 0, "warning": 0, "failed": 0, "running": 0}
    for m in runs:
        c[m.get("status", "warning")] = c.get(m.get("status", "warning"), 0) + 1
    return c


# ---------------------------------------------------------------- proyectos
def list_projects() -> list[dict]:
    projs = []
    if PROJECTS_DIR.exists():
        for f in PROJECTS_DIR.glob("*.json"):
            try:
                projs.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    projs.sort(key=lambda p: p.get("created", ""), reverse=True)
    return projs


def get_project(project_id: str) -> dict | None:
    f = PROJECTS_DIR / f"{project_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save_project(name: str, description: str = "", considerations: str = "",
                 run_ids: list[str] | None = None, project_id: str | None = None,
                 owner: str = "Fernando Cornielle") -> dict:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if project_id is None:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "proyecto"
        project_id = f"{slug}-{uuid.uuid4().hex[:6]}"
    proj = {
        "id": project_id, "name": name, "description": description,
        "considerations": considerations, "run_ids": run_ids or [],
        "created": datetime.now(timezone.utc).isoformat(), "owner": owner,
    }
    (PROJECTS_DIR / f"{project_id}.json").write_text(
        json.dumps(proj, indent=2, ensure_ascii=False), encoding="utf-8")
    return proj


# ---------------------------------------------------------------- semilla
def _write_run(run_id: str, manifest: dict, files: dict[str, pd.DataFrame]) -> None:
    out = RUNS_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, df in files.items():
        df.to_csv(out / name, index=False)


def ensure_seed_runs() -> None:
    """Si no hay corridas, envuelve las salidas existentes del pipeline como corridas."""
    if list_runs():
        return
    # 1) verificación AC (data/processed/ac_modom) como corrida ac_verify
    ac_dir = REPO_ROOT / "data/processed/ac_modom"
    if (ac_dir / "summary_24h.csv").exists():
        summ = pd.read_csv(ac_dir / "summary_24h.csv")
        peak = summ.iloc[(summ["demand_mw"].fillna(0)).idxmax()] if "demand_mw" in summ else summ.iloc[0]
        bus = pd.read_csv(ac_dir / "bus_voltages_24h.csv") if (ac_dir / "bus_voltages_24h.csv").exists() else pd.DataFrame()
        br = pd.read_csv(ac_dir / "branch_loading_24h.csv") if (ac_dir / "branch_loading_24h.csv").exists() else pd.DataFrame()
        _write_run("seed_ac_verify_24h", {
            "run_id": "seed_ac_verify_24h", "project_id": None, "type": "ac_verify",
            "label": "Verificación AC · 24 h (MODOM)", "status": "completed",
            "started": "2026-06-13T00:00:00+00:00", "duration_s": 0,
            "params": {"hours": 24, "source": "data/processed/ac_modom"},
            "summary": {k: (float(peak[k]) if k in peak and pd.notna(peak[k]) else None)
                        for k in ("demand_mw", "gen_mw", "slack_mw", "losses_mw",
                                  "v_min", "v_max")},
            "coverage": {}, "_seed": True,
        }, {"ac_bus_voltages.csv": bus, "ac_branch_loading.csv": br})

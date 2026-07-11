from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

from modom_pypsa.pdd import HOURS, export_pdd, pdd_date_from_name

REPO_ROOT = Path(__file__).resolve().parents[1]
PDD_XLSX = REPO_ROOT / "data" / "external" / "PDD 11-06-26" / "PDD 11-06-26.xlsx"


def test_pdd_date_from_name() -> None:
    assert pdd_date_from_name(Path("PDD 11-06-26.xlsx")) == "2026-06-11"
    assert pdd_date_from_name(Path("dir/PDD 01-12-2026/PDD 01-12-2026.xlsx")) == "2026-12-01"


def test_export_pdd_from_workbook(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    if not PDD_XLSX.exists():
        pytest.skip("falta el PDD de ejemplo")

    payload = export_pdd(PDD_XLSX, tmp_path)
    assert payload["pdd_date"] == "2026-06-11"
    outdir = tmp_path / "2026-06-11"
    for f in ["dispatch.csv", "bus_voltage.csv", "branch_loading.csv",
              "nodal_factors.csv", "demand.csv", "meta.json"]:
        assert (outdir / f).exists()

    disp = pd.read_csv(outdir / "dispatch.csv", index_col=0)
    assert list(disp.index) == HOURS                      # 24 h del día 1
    assert any(c.startswith("G") for c in disp.columns)    # códigos de generador

    volt = pd.read_csv(outdir / "bus_voltage.csv", index_col=0)
    assert all(c.upper().startswith("W") for c in volt.columns)   # W-codes
    vmax = volt.max().max()
    assert 0.8 < vmax < 1.2                                # rango p.u. plausible

    nf = pd.read_csv(outdir / "nodal_factors.csv")
    assert len(nf) > 0 and "factor_retiro" in nf.columns

    # demanda total ≈ generación total (coherencia del balance), tolerancia 10 %
    dem = pd.read_csv(outdir / "demand.csv").set_index("snapshot_id").p_set_mw
    gen_h01 = float(disp.loc["h_01"].sum())
    assert abs(float(dem["h_01"]) - gen_h01) < 0.10 * gen_h01


def test_export_pdd_loading_uses_native_labels(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    if not PDD_XLSX.exists():
        pytest.skip("falta el PDD de ejemplo")
    export_pdd(PDD_XLSX, tmp_path)
    ld = pd.read_csv(tmp_path / "2026-06-11" / "branch_loading.csv", index_col=0)
    assert ld.shape[1] > 0
    assert ld.max().max() <= 130                           # cargabilidad % razonable
    assert "#N/A" not in ld.columns                        # se descartan etiquetas inválidas

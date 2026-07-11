"""Ingesta del **PDD** (Programa de Despacho Diario) que publica el OC.

El PDD es la SALIDA oficial de MODOM (el OC corre MODOM y publica el PDD del día). Trae el
caso operativo vigente con casi todo lo que muestra la pestaña MODOM·PDD, con llaves limpias:

- `DESPACHO EN OM`        → despacho por generador (códigos `G3…` = `generator_id`).
- `Analisis_Electrico`    → "VOLTAJES (p.u.)" por barra (W-code) y
                            "FLUJOS POR LINEAS (%)" por línea (etiqueta nativa Z-code).
- `Factores de Nodo (Retiro)` → factor de nodo por barra (W-code).
- `DEMANDA SENI`          → demanda por distribuidora ("Carga Estimada").

Eje horario: 48 períodos (2 días); se usa el **día 1** (1..24 → `h_01..h_24`), igual que el
resto del pipeline. La columna del período 1 se detecta por la cabecera `1,2,3,4…`.

`export_pdd` escribe un store canónico por fecha en `data/processed/pdd/<YYYY-MM-DD>/` que la
webapp lee como "el último PDD". El cruce de ramas Z→W NO se intenta: la cargabilidad se
muestra como barras con la etiqueta nativa del PDD (no necesita coordenadas).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

N_DAY1 = 24  # períodos del día 1
HOURS = [f"h_{p:02d}" for p in range(1, N_DAY1 + 1)]


def _snapshot_id(period_1based: int) -> str:
    return f"h_{period_1based:02d}"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _find_period_start(rows: list[list], from_row: int = 0, to_row: int | None = None) -> int | None:
    """Columna donde está el período `1` (cabecera con `1,2,3,4` consecutivos)."""
    to_row = len(rows) if to_row is None else to_row
    for i in range(from_row, to_row):
        row = rows[i]
        for j in range(len(row) - 3):
            seq = []
            for k in range(4):
                v = row[j + k]
                try:
                    seq.append(int(str(v).strip()))
                except (TypeError, ValueError):
                    seq = []
                    break
            if seq == [1, 2, 3, 4]:
                return j
    return None


def _row_periods(row: list, start_col: int) -> list[float | None]:
    """24 valores del día 1 desde `start_col`."""
    return [_num(row[start_col + p]) if start_col + p < len(row) else None
            for p in range(N_DAY1)]


def _load_sheet(wb, name: str) -> list[list]:
    ws = wb[name]
    return [list(r) for r in ws.iter_rows(values_only=True)]


# --------------------------------------------------------------- secciones del PDD
def parse_dispatch(rows: list[list]) -> pd.DataFrame:
    """Despacho por generador (hora × generator_id, MW). Filas con `G…` en col 0."""
    start = _find_period_start(rows)
    if start is None:
        return pd.DataFrame(index=HOURS)
    data: dict[str, list] = {}
    for row in rows:
        code = str(row[0]).strip() if row and row[0] is not None else ""
        if re.match(r"^G\d", code):
            data[code] = _row_periods(row, start)
    df = pd.DataFrame(data, index=HOURS)
    return df


_SECTION_RE = re.compile(r"VOLTAJE|FLUJO|PGENER|POTENCIA|MONITOREO", re.I)


def _section_starts(rows: list[list]) -> list[tuple[int, str]]:
    """Filas de etiqueta de sección en Analisis_Electrico, en orden."""
    out = []
    for i, row in enumerate(rows):
        for cell in row[:5]:
            s = str(cell).strip() if cell is not None else ""
            if _SECTION_RE.search(s):
                out.append((i, s))
                break
    return out


def _block_bounds(rows: list[list], label_exact: str) -> tuple[int | None, int]:
    """(start, end) del PRIMER bloque con etiqueta `label_exact`; end = siguiente sección."""
    starts = _section_starts(rows)
    for k, (i, s) in enumerate(starts):
        if s == label_exact:
            end = starts[k + 1][0] if k + 1 < len(starts) else len(rows)
            return i, end
    return None, len(rows)


def _parse_analisis_block(rows: list[list], start_row: int, end_row: int, code_ok,
                          code_col: int = 1) -> pd.DataFrame:
    """Parsea un bloque acotado de Analisis_Electrico (hora × código). `code_ok(str)->bool`."""
    pstart = _find_period_start(rows, from_row=start_row, to_row=start_row + 4)
    if pstart is None:
        return pd.DataFrame(index=HOURS)
    data: dict[str, list] = {}
    for i in range(start_row + 1, end_row):
        row = rows[i]
        code = str(row[code_col]).strip() if len(row) > code_col and row[code_col] is not None else ""
        if code and code_ok(code) and code not in data:
            data[code] = _row_periods(row, pstart)
    return pd.DataFrame(data, index=HOURS)


def parse_voltages(rows: list[list]) -> pd.DataFrame:
    start, end = _block_bounds(rows, "VOLTAJES  (p.u.)")
    if start is None:
        return pd.DataFrame(index=HOURS)
    return _parse_analisis_block(rows, start, end, lambda c: c.upper().startswith("W"))


def parse_branch_loading(rows: list[list]) -> pd.DataFrame:
    start, end = _block_bounds(rows, "FLUJOS POR LINEAS (%)")
    if start is None:
        return pd.DataFrame(index=HOURS)
    # etiqueta de línea nativa del PDD (Z-code con '_' y '-'); descartar #N/A vacías
    return _parse_analisis_block(
        rows, start, end, lambda c: ("_" in c or "-" in c) and c.upper() != "#N/A")


def parse_nodal_factors(rows: list[list]) -> pd.DataFrame:
    """Factor de nodo por barra (bus_id_modom = W-code, factor_retiro)."""
    # cabecera: ... 'BARRA TRANSACCION' (col3) ... 'FACTORES DE NODO' (col5)
    out = []
    for row in rows:
        bus = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""
        fac = _num(row[5]) if len(row) > 5 else None
        if bus.upper().startswith("W") and fac is not None:
            out.append({"bus_id_modom": bus, "factor_retiro": fac})
    return pd.DataFrame(out).drop_duplicates("bus_id_modom")


def parse_demand(rows: list[list], dispatch: pd.DataFrame | None = None) -> pd.DataFrame:
    """Demanda del SENI por hora desde la fila total `DEMANDA DEL SENI` con datos.

    (Sumar las 'Carga Estimada' por distribuidora duplicaría: hay totales + desgloses.)
    Respaldo: suma del despacho por hora.
    """
    start = _find_period_start(rows)
    if start is not None:
        for row in rows:
            label = str(row[1]).strip().upper() if len(row) > 1 and row[1] is not None else ""
            if label == "DEMANDA DEL SENI":
                vals = _row_periods(row, start)
                if any(v is not None for v in vals):
                    return pd.DataFrame({"snapshot_id": HOURS,
                                         "p_set_mw": [v or 0.0 for v in vals]})
    if dispatch is not None and not dispatch.empty:
        s = dispatch.sum(axis=1).reindex(HOURS)
        return pd.DataFrame({"snapshot_id": HOURS, "p_set_mw": s.values})
    return pd.DataFrame({"snapshot_id": HOURS, "p_set_mw": [0.0] * N_DAY1})


# --------------------------------------------------------------- fecha + export
def pdd_date_from_name(path: Path) -> str:
    """'PDD 11-06-26' → '2026-06-11'. Asume siglo 20xx."""
    m = re.search(r"(\d{2})-(\d{2})-(\d{2,4})", Path(path).stem)
    if not m:
        raise ValueError(f"No se pudo extraer fecha de {path}")
    dd, mm, yy = m.groups()
    year = int(yy) if len(yy) == 4 else 2000 + int(yy)
    return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"


def export_pdd(xlsx: Path, out_root: Path) -> dict[str, object]:
    """Parsea el PDD y escribe el store canónico `out_root/<YYYY-MM-DD>/`."""
    import openpyxl

    xlsx = Path(xlsx)
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    despacho = _load_sheet(wb, "DESPACHO EN OM")
    analisis = _load_sheet(wb, "Analisis_Electrico")
    factores = _load_sheet(wb, "Factores de Nodo (Retiro)")
    demanda = _load_sheet(wb, "DEMANDA SENI")
    wb.close()

    dispatch = parse_dispatch(despacho)
    voltages = parse_voltages(analisis)
    loading = parse_branch_loading(analisis)
    nodal = parse_nodal_factors(factores)
    demand = parse_demand(demanda, dispatch)

    date = pdd_date_from_name(xlsx)
    outdir = Path(out_root) / date
    outdir.mkdir(parents=True, exist_ok=True)
    dispatch.round(4).to_csv(outdir / "dispatch.csv")
    voltages.round(6).to_csv(outdir / "bus_voltage.csv")
    loading.round(2).to_csv(outdir / "branch_loading.csv")
    nodal.to_csv(outdir / "nodal_factors.csv", index=False)
    demand.to_csv(outdir / "demand.csv", index=False)
    meta = {
        "pdd_date": date,
        "source_file": str(xlsx),
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "generators": int(dispatch.shape[1]),
            "voltage_buses": int(voltages.shape[1]),
            "loading_lines": int(loading.shape[1]),
            "nodal_factors": int(len(nodal)),
        },
    }
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return {"outdir": str(outdir), **meta}

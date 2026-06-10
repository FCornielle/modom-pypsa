"""Extrae los RESULTADOS que el propio MODOM ya calculó (la "verdad de referencia").

El MODOM (GAMS + DIgSILENT) publica en su workbook su propio despacho, flujos y
energia no servida. Esas hojas son el objetivo de validacion: comparamos lo que
PyPSA resuelve contra lo que el OC realmente despacho, para medir fidelidad.

Hojas usadas (confirmadas por inspeccion):
- `S_DESPACHOM` ("POTENCIA DESpachada"): despacho activo MW por generador y periodo.
  Fila `PERIODO 1..48`; filas de datos `G3xxxx, mw1, mw2, ...` (cruza 140/140 con
  nuestros `generator_id`).
- `FLUJO_ACTIVA`: flujo activo MW por rama y periodo. Cabecera
  `BARRA, BARRA, CTO, LRATE, 1, 2, ...` (bus0, bus1, circuito, periodos desde col 4).
- `P_ENS`: energia no servida MW por barra y periodo. Cabecera `BARRA, 1, 2, ...`.

Eje temporal: el MODOM trae 48 periodos (2 dias); tomamos los **primeros 24**
(dia 1), igual que el resto del pipeline.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .xlsm import XlsmReader

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
N_PERIODS = 24
SNAPSHOT_IDS = [f"h_{i + 1:02d}" for i in range(N_PERIODS)]


def _to_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float("nan")


def _find_header_row(matrix: list[list[str]], col0_label: str) -> int:
    """Devuelve el indice de la fila cuyo primer campo empieza por `col0_label`."""
    target = col0_label.strip().upper()
    for i, row in enumerate(matrix):
        if row and str(row[0]).strip().upper().startswith(target):
            return i
    raise ValueError(f"No encontre la fila cabecera que empieza por '{col0_label}'")


def extract_generator_dispatch(
    reader: XlsmReader, valid_gen_ids: set[str], n: int = N_PERIODS
) -> pd.DataFrame:
    """Despacho activo MW por generador (S_DESPACHOM) -> DataFrame [snapshot x gen]."""
    m = reader.read_sheet_matrix("S_DESPACHOM")
    hr = _find_header_row(m, "PERIODO")
    data: dict[str, list[float]] = {}
    for row in m[hr + 1:]:
        if not row:
            continue
        gid = str(row[0]).strip()
        if gid not in valid_gen_ids:  # salta secciones (TERMICAS, HIDRO...) y vacios
            continue
        data[gid] = [_to_float(row[c]) if c < len(row) else float("nan")
                     for c in range(1, n + 1)]
    return pd.DataFrame(data, index=SNAPSHOT_IDS[:n])


def extract_branch_flows(reader: XlsmReader, n: int = N_PERIODS) -> pd.DataFrame:
    """Flujo activo MW por rama (FLUJO_ACTIVA) -> DataFrame [snapshot x branch_key].

    `branch_key` = `bus0|bus1|circuito` tal cual viene del MODOM (el matching con
    los nombres de nuestras ramas se hace en la capa de validacion, normalizando
    el circuito y el orden de barras).
    """
    m = reader.read_sheet_matrix("FLUJO_ACTIVA")
    hr = _find_header_row(m, "BARRA")
    # periodos empiezan en la primera columna cuyo header es "1"
    pcol = next(c for c, v in enumerate(m[hr]) if str(v).strip() == "1")
    data: dict[str, list[float]] = {}
    for row in m[hr + 1:]:
        if not row or not str(row[0]).strip():
            continue
        bus0, bus1, cto = (str(row[0]).strip(), str(row[1]).strip(),
                           str(row[2]).strip() if len(row) > 2 else "")
        key = f"{bus0}|{bus1}|{cto}"
        data[key] = [_to_float(row[c]) if c < len(row) else float("nan")
                     for c in range(pcol, pcol + n)]
    return pd.DataFrame(data, index=SNAPSHOT_IDS[:n])


def extract_bus_ens(reader: XlsmReader, n: int = N_PERIODS) -> pd.DataFrame:
    """Energia no servida MW por barra (P_ENS) -> DataFrame [snapshot x bus]."""
    m = reader.read_sheet_matrix("P_ENS")
    hr = _find_header_row(m, "BARRA")
    pcol = next(c for c, v in enumerate(m[hr]) if str(v).strip() == "1")
    data: dict[str, list[float]] = {}
    for row in m[hr + 1:]:
        if not row or not str(row[0]).strip():
            continue
        bus = str(row[0]).strip()
        data[bus] = [_to_float(row[c]) if c < len(row) else float("nan")
                     for c in range(pcol, pcol + n)]
    return pd.DataFrame(data, index=SNAPSHOT_IDS[:n])


def extract_nodal_factors(reader: XlsmReader) -> pd.DataFrame:
    """Factores de nodo del MODOM por barra (pérdidas marginales / pricing).

    `Factores de Nodo (Retiro)` -> factor por barra de retiro (col BARRA, col FACTOR);
    `Factores de Nodo (Inyección)` -> factor por barra de inyección. Devuelve
    DataFrame index=bus con columnas `factor_retiro`, `factor_inyeccion` (promedio si
    una barra aparece varias veces).
    """
    def _read_factor_sheet(sheet: str) -> pd.Series:
        m = reader.read_sheet_matrix(sheet)
        # localizar la fila de encabezado y las columnas de BARRA y FACTOR
        head_i = next((i for i, r in enumerate(m)
                       if any("BARRA" in str(c).upper() for c in r)), 1)
        head = [str(c).upper() for c in m[head_i]]
        bcol = next(i for i, c in enumerate(head) if "BARRA" in c)
        fcol = next(i for i, c in enumerate(head) if "FACTOR" in c)
        vals: dict[str, list[float]] = {}
        for row in m[head_i + 1:]:
            if bcol >= len(row) or fcol >= len(row):
                continue
            bus = str(row[bcol]).strip()
            f = _to_float(row[fcol])
            if bus.startswith("W") and f == f and f > 0:
                vals.setdefault(bus, []).append(f)
        return pd.Series({b: sum(v) / len(v) for b, v in vals.items()})

    ret = _read_factor_sheet("Factores de Nodo (Retiro)").rename("factor_retiro")
    inj = _read_factor_sheet("Factores de Nodo (Inyección)").rename("factor_inyeccion")
    return pd.concat([ret, inj], axis=1)


def export_modom_results(
    xlsm_path: Path, data_dir: Path = DEFAULT_DATA_DIR, n: int = N_PERIODS
) -> dict[str, object]:
    """Escribe las tablas de verdad de referencia + factores de nodo a `modom_results/`."""
    reader = XlsmReader(xlsm_path)
    gens_csv = data_dir / "generators" / "generators.csv"
    valid_gens = set(pd.read_csv(gens_csv, dtype=str)["generator_id"].str.strip())

    disp = extract_generator_dispatch(reader, valid_gens, n)
    flows = extract_branch_flows(reader, n)
    ens = extract_bus_ens(reader, n)
    factors = extract_nodal_factors(reader)

    outdir = data_dir / "modom_results"
    outdir.mkdir(parents=True, exist_ok=True)
    disp.to_csv(outdir / "modom_generator_dispatch.csv")
    flows.to_csv(outdir / "modom_branch_flows.csv")
    ens.to_csv(outdir / "modom_bus_ens.csv")
    factors.to_csv(outdir / "nodal_factors.csv", index_label="bus_id_modom")

    return {
        "outdir": str(outdir),
        "periods": n,
        "generators": disp.shape[1],
        "branches": flows.shape[1],
        "ens_buses": ens.shape[1],
        "ens_total_mwh": round(float(ens.to_numpy(dtype=float).sum()), 3),
        "nodal_factors_retiro": int(factors["factor_retiro"].notna().sum()),
    }

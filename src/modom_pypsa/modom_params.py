"""Ingesta de los parámetros del **MILP del MODOM** desde el workbook GAMS.

Complementa la capa canónica con lo que hace falta para reconstruir el unit
commitment y las reservas del MODOM en PyPSA (antes solo teníamos el despacho ya
resuelto). Lee tres hojas de entrada del `.xlsm`:

- ``e_datgen`` (TABLE DATGEN, indexado por generador): parámetros de commitment por
  unidad — rampas ``RS``/``RB`` (§7.7), tiempos ``TARR``/``TPAR`` (§7.8–7.9), tiempo
  mínimo de operación ``TMO`` y de enfriamiento ``TMPA`` (§7.10), número máximo de
  arranques ``NAMX`` (§7.11.2), rendimiento hidráulico ``RENDH`` (§7.18), servicios
  auxiliares ``SSAA`` (§7.17), márgenes ``MRPF``/``MRSF`` (§7.4–7.6) y estados
  iniciales.
- ``e_hidro`` (varias sub-tablas): niveles de embalse ``DAT_EMB``, aportes ``DAT_AP``
  y extracciones ``DAT_EX`` por período, nivel final objetivo ``DAT_NF`` y el mapeo
  generador→embalse ``DAT_HI`` (§7.18).
- ``e_opcn`` (Parameters GAMS ``/valor/``): constantes globales — ``CENS`` (costo de
  ENS), ``CVER`` (vertimiento), ``CVRRF`` (violación de reserva), ``PORS`` (fracción
  de reserva RRPF/RRSF), ``PORCPERD`` (pérdidas), ``SBASE``.

Todos los índices de período usan el **día 1** (períodos 1..24 → ``h_01..h_24``),
consistente con el resto del proyecto (48 períodos = 2 días; se usa el primero).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DAY1_PERIODS = list(range(1, 25))

# Columnas de TABLE DATGEN (e_datgen), en orden. La col 0 es el id del generador.
DATGEN_COLS = [
    "YN", "PMX", "PMN", "CVP", "TCG", "SSAA", "MRPF", "MRSF", "FACTORA", "H_P",
    "PGN", "BASE", "RS", "RB", "TARR", "TPAR", "TMO", "TMPA", "RENDH", "TIF",
    "RFA_INI", "ARR_INI", "ACC_INI", "PAR_INI", "HOC", "NAMX", "PGINI",
]


def _snapshot_id(period: int) -> str:
    return f"h_{period:02d}"


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load(xlsm_path: Path, sheet: str) -> list[list]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsm_path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


def _cell(row: list, idx: int):
    return row[idx] if idx < len(row) else None


# --------------------------------------------------------------------------- #
#  e_datgen  — parámetros de commitment por generador
# --------------------------------------------------------------------------- #
def parse_datgen(xlsm_path: Path) -> pd.DataFrame:
    """DataFrame indexado por ``generator_id`` con las columnas de DATGEN_COLS."""
    rows = _load(xlsm_path, "e_datgen")
    # localizar la fila-cabecera (contiene 'YN' en la columna 1)
    hdr = next(i for i, r in enumerate(rows) if str(_cell(r, 1) or "").strip() == "YN")
    out = []
    for r in rows[hdr + 1:]:
        gid = str(_cell(r, 0) or "").strip()
        if not gid or gid in (";",) or gid.upper().startswith("TABLE"):
            break
        rec = {"generator_id": gid}
        for j, col in enumerate(DATGEN_COLS, start=1):
            rec[col] = _num(_cell(r, j))
        out.append(rec)
    return pd.DataFrame(out).set_index("generator_id")


# --------------------------------------------------------------------------- #
#  e_opcn  — constantes globales del modelo
# --------------------------------------------------------------------------- #
def parse_opcn(xlsm_path: Path) -> dict[str, float]:
    """Extrae los ``Parameters`` GAMS con forma ``NOMBRE ... /valor/``.

    Devuelve, entre otros: CENS, CVER, SBASE, PORS (=RRPF=RRSF), CVRRF, PORCPERD.
    El token ``eps`` de GAMS (≈0) se mapea a un valor mínimo positivo.
    """
    rows = _load(xlsm_path, "e_opcn")
    params: dict[str, float] = {}
    for r in rows:
        name = str(_cell(r, 0) or "").strip().lstrip("*").strip()
        if not name or " " in name:
            # buscar el valor /.../ en cualquier celda de la fila
            pass
        # el valor está en alguna celda con forma '/x/'
        val = None
        for c in r:
            s = str(c or "").strip()
            if s.startswith("/") and s.endswith("/") and len(s) > 2:
                inner = s[1:-1].strip()
                if inner.lower() in ("eps",):
                    val = 1e-3
                else:
                    val = _num(inner)
                break
        key = str(_cell(r, 0) or "").strip().lstrip("*").strip()
        if key and val is not None and " " not in key:
            params[key] = val
    return params


# --------------------------------------------------------------------------- #
#  e_hidro  — embalses (varias sub-tablas)
# --------------------------------------------------------------------------- #
def parse_hidro(xlsm_path: Path) -> dict[str, pd.DataFrame]:
    """Devuelve las sub-tablas de e_hidro como DataFrames.

    Claves: ``reservoirs`` (DAT_EMB), ``inflow`` (DAT_AP), ``extract`` (DAT_EX),
    ``final_level`` (DAT_NF), ``gen_reservoir`` (DAT_HI, largo: generator_id, reservoir_id).
    Los períodos se recortan al día 1.
    """
    rows = _load(xlsm_path, "e_hidro")

    # localizar el inicio de cada TABLE por su nombre
    def find_table(tag: str) -> int:
        for i, r in enumerate(rows):
            joined = " ".join(str(c or "") for c in r)
            if joined.strip().startswith("TABLE") and tag in joined:
                return i
        return -1

    def read_block(start: int, header_offset: int = 1):
        """Filas (id + valores) desde la cabecera hasta la primera fila vacía/nueva tabla."""
        header = rows[start + header_offset]
        data = []
        for r in rows[start + header_offset + 1:]:
            rid = str(_cell(r, 0) or "").strip()
            if not rid or rid.upper().startswith("TABLE") or rid.startswith("e_") or rid == ";":
                break
            data.append(r)
        return header, data

    out: dict[str, pd.DataFrame] = {}

    # DAT_EMB: nivel_min, nivel_max, nivel_ini, nivel_fin, vertmax, vertmin
    i = find_table("DAT_EMB")
    if i >= 0:
        _, data = read_block(i, header_offset=2)  # cabecera 'nivel_min...' 2 filas abajo
        recs = []
        for r in data:
            recs.append({
                "reservoir_id": str(_cell(r, 0)).strip(),
                "nivel_min": _num(_cell(r, 1)), "nivel_max": _num(_cell(r, 2)),
                "nivel_ini": _num(_cell(r, 3)), "nivel_fin": _num(_cell(r, 4)),
                "vertmax": _num(_cell(r, 5)), "vertmin": _num(_cell(r, 6)),
            })
        out["reservoirs"] = pd.DataFrame(recs)

    # DAT_AP / DAT_EX: por período (pd001.. -> día 1)
    for tag, key in (("DAT_AP", "inflow"), ("DAT_EX", "extract")):
        i = find_table(tag)
        if i < 0:
            continue
        _, data = read_block(i, header_offset=1)
        recs = []
        for r in data:
            rid = str(_cell(r, 0)).strip()
            for p in DAY1_PERIODS:
                v = _num(_cell(r, p))  # col p = período p (col 0 es el id)
                recs.append({"reservoir_id": rid, "snapshot_id": _snapshot_id(p),
                             "value_hm3": v if v is not None else 0.0})
        out[key] = pd.DataFrame(recs)

    # DAT_NF: nivel final objetivo (columnas 24 y 48). Usamos la de 24 (fin del día 1).
    i = find_table("DAT_NF")
    if i >= 0:
        _, data = read_block(i, header_offset=1)
        recs = []
        for r in data:
            recs.append({"reservoir_id": str(_cell(r, 0)).strip(),
                         "nivel_fin_24": _num(_cell(r, 1))})
        out["final_level"] = pd.DataFrame(recs)

    # DAT_HI: matriz generador x embalse -> largo (generator_id, reservoir_id)
    i = find_table("DAT_HI")
    if i >= 0:
        header = rows[i + 1]
        reservoirs = [str(c).strip() for c in header[1:] if c not in (None, "")]
        recs = []
        for r in rows[i + 2:]:
            gid = str(_cell(r, 0) or "").strip()
            if gid.upper().startswith("TABLE") or gid.startswith("e_") or gid == ";":
                break
            if not gid:
                continue  # fila en blanco entre cabecera y datos: saltar, no terminar
            for k, res in enumerate(reservoirs, start=1):
                if _num(_cell(r, k)):
                    recs.append({"generator_id": gid, "reservoir_id": res})
        out["gen_reservoir"] = pd.DataFrame(recs)

    return out


# --------------------------------------------------------------------------- #
#  Persistencia canónica
# --------------------------------------------------------------------------- #
def export_params(xlsm_path: Path, outdir: Path) -> dict[str, object]:
    """Escribe los CSV canónicos de commitment, opciones e hidro. Devuelve un resumen."""
    datgen = parse_datgen(xlsm_path)
    opcn = parse_opcn(xlsm_path)
    hidro = parse_hidro(xlsm_path)

    commit_dir = outdir / "commitment"
    hydro_dir = outdir / "hydro"
    commit_dir.mkdir(parents=True, exist_ok=True)
    hydro_dir.mkdir(parents=True, exist_ok=True)

    datgen.to_csv(commit_dir / "gen_params.csv")
    pd.DataFrame([opcn]).to_csv(commit_dir / "model_options.csv", index=False)
    for key, df in hidro.items():
        df.to_csv(hydro_dir / f"{key}.csv", index=False)

    return {
        "generators": int(len(datgen)),
        "with_ramp": int(((datgen["RS"].fillna(0) > 0) | (datgen["RB"].fillna(0) > 0)).sum()),
        "with_namx": int((datgen["NAMX"].fillna(0) > 0).sum()),
        "options": opcn,
        "reservoirs": int(len(hidro.get("reservoirs", []))),
        "hydro_units": int(len(hidro.get("gen_reservoir", []))),
    }

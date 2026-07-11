"""Ingesta de los **flowgates** del MODOM desde la hoja `e_fgate` del workbook.

En MODOM la seguridad N-1 NO se modela con un SCLOPF genérico, sino con *flowgates*:
interfaces críticas con un límite derateado, expresadas como combinación lineal de
flujos de rama:  `Σ coef·flujo  ≤  FLGTMAX(fg)`.

La hoja `e_fgate` tiene dos tablas GAMS:

- `TABLE FGATE(ni,nf,cc,fg)` — miembros de cada flowgate y su coeficiente. Columnas:
  `ni` (col 0), `nf` (col 2), `cc` (col 4) y el coeficiente en la columna del flowgate
  activo (fg1≈col 6, fg2≈col 7, fg3≈col 8). Termina en `;`.
- `TABLE FLGTMAX(fg,n)` — límite por flowgate y período (1..48). Fila por flowgate,
  columnas 2..49 = períodos 1..48. Usamos el **día 1** (períodos 1..24 → `h_01..h_24`).

Cada miembro `(ni, nf, cc)` mapea a la rama PyPSA `{ni}__{nf}__{cc}` (o su inversa).
`orient` es +1 si el flujo PyPSA `p0` (orientado bus0→bus1) ya va en el sentido ni→nf,
o −1 si hay que invertirlo, de modo que `signed_coeff = coefficient × orient` se aplica
directo sobre `p0`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Día 1 del MODOM = primeras 24h (los 48 períodos son 2 días; usamos el primero).
DAY1_PERIODS = list(range(1, 25))
# Columnas de coeficiente por flowgate en TABLE FGATE.
FG_COEF_COL = {"fg1": 6, "fg2": 7, "fg3": 8}
# La columna del período n en TABLE FLGTMAX es n + 1 (período 1 -> col 2).
FLGTMAX_PERIOD_COL_OFFSET = 1


def _snapshot_id(period: int) -> str:
    return f"h_{period:02d}"


def _branch_lookup(branch_components_dir: Path) -> dict[str, dict[str, str]]:
    """name -> {bus0, bus1, kind} para líneas y transformadores v1."""
    lookup: dict[str, dict[str, str]] = {}
    for fname, kind in (("lines_v1.csv", "line"), ("transformers_v1.csv", "transformer")):
        path = branch_components_dir / fname
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for _, r in df.iterrows():
            lookup[r["name"]] = {"bus0": r["bus0"], "bus1": r["bus1"], "kind": kind}
    return lookup


def parse_e_fgate(xlsm_path: Path) -> tuple[list[dict], dict[str, dict[int, float]]]:
    """Devuelve `(members, limits)` crudos de la hoja `e_fgate`.

    `members`: lista de {flowgate_id, ni, nf, cc, coefficient}.
    `limits`:  {flowgate_id: {period: fmax_mw}} para los 48 períodos.
    """
    import openpyxl

    wb = openpyxl.load_workbook(xlsm_path, read_only=True, data_only=True)
    ws = wb["e_fgate"]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    def cell(row: list, idx: int):
        return row[idx] if idx < len(row) else None

    members: list[dict] = []
    limits: dict[str, dict[int, float]] = {}

    mode: str | None = None
    for row in rows:
        head = str(cell(row, 0) or "").strip()
        tag = str(cell(row, 2) or "").strip()
        if head == "TABLE" and tag == "FGATE":
            mode = "fgate"
            continue
        if head == "TABLE" and tag == "FLGTMAX":
            mode = "flgtmax"
            continue
        if head == ";":
            mode = None
            continue
        if mode == "fgate":
            ni, nf, cc = cell(row, 0), cell(row, 2), cell(row, 4)
            if not (ni and nf and cc):
                continue  # fila de cabecera (fg1/fg2) u hoja vacía
            for fg, col in FG_COEF_COL.items():
                v = cell(row, col)
                if v is None or v == "":
                    continue
                members.append({
                    "flowgate_id": fg,
                    "ni": str(ni).strip(),
                    "nf": str(nf).strip(),
                    "cc": str(cc).strip(),
                    "coefficient": float(v),
                })
        elif mode == "flgtmax":
            fg = head
            if not fg.startswith("fg"):
                continue  # fila de cabecera de períodos
            per: dict[int, float] = {}
            for p in range(1, 49):
                v = cell(row, p + FLGTMAX_PERIOD_COL_OFFSET)
                if v is not None and v != "":
                    per[p] = float(v)
            if per:
                limits[fg] = per
    return members, limits


def resolve_members(members: list[dict], branch_lookup: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Añade `branch_name, orient, branch_exists, branch_kind` a cada miembro.

    `orient` = +1 si la rama PyPSA está como ni→nf (p0 ya en ese sentido), −1 si invertida.
    """
    out = []
    for m in members:
        ni, nf, cc = m["ni"], m["nf"], m["cc"]
        direct = f"{ni}__{nf}__{cc}"
        inverse = f"{nf}__{ni}__{cc}"
        name, orient, kind, exists = direct, 1, "", False
        if direct in branch_lookup:
            name, orient, exists = direct, 1, True
            kind = branch_lookup[direct]["kind"]
        elif inverse in branch_lookup:
            name, orient, exists = inverse, -1, True
            kind = branch_lookup[inverse]["kind"]
        out.append({
            "flowgate_id": m["flowgate_id"],
            "branch_name": name,
            "ni": ni, "nf": nf, "cc": cc,
            "coefficient": m["coefficient"],
            "orient": orient,
            "branch_exists": int(exists),
            "branch_kind": kind,
        })
    return pd.DataFrame(out)


def build_limits_table(limits: dict[str, dict[int, float]]) -> pd.DataFrame:
    """Aplana `{fg: {period: fmax}}` a filas (flowgate_id, snapshot_id, fmax_mw) del día 1."""
    rows = []
    for fg, per in limits.items():
        for p in DAY1_PERIODS:
            if p in per:
                rows.append({
                    "flowgate_id": fg,
                    "snapshot_id": _snapshot_id(p),
                    "fmax_mw": per[p],
                })
    return pd.DataFrame(rows)


def export_flowgates(
    xlsm_path: Path,
    outdir: Path,
    branch_components_dir: Path,
) -> dict[str, object]:
    """Parsea `e_fgate`, resuelve ramas y escribe los dos CSV canónicos.

    Solo se conservan flowgates con miembros Y límite (descarta fg3, vacío).
    """
    members_raw, limits_raw = parse_e_fgate(xlsm_path)
    lookup = _branch_lookup(branch_components_dir)

    members_df = resolve_members(members_raw, lookup)
    limits_df = build_limits_table(limits_raw)

    # Conservar solo flowgates con miembros y con límite definido.
    active = sorted(set(members_df["flowgate_id"]) & set(limits_df["flowgate_id"]))
    members_df = members_df[members_df["flowgate_id"].isin(active)].reset_index(drop=True)
    limits_df = limits_df[limits_df["flowgate_id"].isin(active)].reset_index(drop=True)

    outdir.mkdir(parents=True, exist_ok=True)
    members_path = outdir / "flowgate_members.csv"
    limits_path = outdir / "flowgate_limits.csv"
    members_df.to_csv(members_path, index=False)
    limits_df.to_csv(limits_path, index=False)

    missing = members_df[members_df["branch_exists"] == 0]
    return {
        "members_path": str(members_path),
        "limits_path": str(limits_path),
        "flowgates": active,
        "counts": {
            fg: int((members_df["flowgate_id"] == fg).sum()) for fg in active
        },
        "limits_mw": {
            fg: sorted(set(limits_df.loc[limits_df["flowgate_id"] == fg, "fmax_mw"]))
            for fg in active
        },
        "missing_branches": missing[["flowgate_id", "branch_name"]].to_dict("records"),
    }

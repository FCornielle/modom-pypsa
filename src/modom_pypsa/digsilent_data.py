"""Extrae los parámetros reactivos de red desde el export de DIgSILENT.

`data/external/digsilent 2023.xlsx` es un export de elementos de PowerFactory que
contiene lo que NINGÚN workbook del OC trae: R/X en ohmios + carga de línea, el
inventario completo de shunts (capacitores y reactores) con su MVAr, el control
OLTC de los transformadores (regula tensión a una consigna), y los límites de Q
de los generadores. Esto es lo que necesita el flujo AC para converger en 24h.

Los terminales vienen en código Z (`ZAANDE`); mapean a nuestras barras W (`WAANDE`)
por intercambio del primer carácter (cobertura ~78%). El export es de 2023 (la red
es estable año a año; puede faltar algún elemento nuevo).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .xlsm import XlsmReader

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = REPO_ROOT / "data" / "external" / "digsilent 2023.xlsx"
DEFAULT_OUTDIR = REPO_ROOT / "data" / "external" / "digsilent"
F_HZ = 60.0


def zw(z: object) -> str:
    """Código de terminal DIgSILENT (Z...) -> barra del modelo (W...)."""
    s = str(z).strip()
    return "W" + s[1:] if s[:1].upper() == "Z" else s


def _num(v: object) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return float("nan")


def _sheet(reader: XlsmReader, name: str) -> tuple[list[str], list[list[str]]]:
    m = reader.read_sheet_matrix(name)
    return [str(c).strip() for c in m[0]], m[1:]


def _col(headers: list[str], *names: str) -> int:
    """Índice de columna por encabezado: match exacto primero, luego subcadena."""
    low = [h.lower() for h in headers]
    for nm in names:
        if nm.lower() in low:
            return low.index(nm.lower())
    for i, h in enumerate(low):
        for nm in names:
            if nm.lower() in h:
                return i
    return -1


def extract_lines(reader: XlsmReader) -> pd.DataFrame:
    """Líneas: barras (Z→W), R/X (ohm), longitud, corriente de carga Ice (A)."""
    h, rows = _sheet(reader, "basic data line")
    ci, cj = _col(h, "Terminal i"), _col(h, "Terminal j")
    cr, cx = _col(h, "R1"), _col(h, "X1")
    cl, cice = _col(h, "Length"), _col(h, "Ice")
    coos = _col(h, "Out of Service")
    out = []
    for r in rows:
        def g(c):
            return r[c] if 0 <= c < len(r) else ""
        bi, bj = zw(g(ci)), zw(g(cj))
        if not bi.startswith("W") or not bj.startswith("W"):
            continue
        out.append({
            "bus_i": bi, "bus_j": bj,
            "r_ohm": _num(g(cr)), "x_ohm": _num(g(cx)),
            "length_km": _num(g(cl)), "ice_a": _num(g(cice)),
            "out_of_service": str(g(coos)).strip(),
            "name": str(g(0)).strip(),
        })
    return pd.DataFrame(out)


def extract_shunts(reader: XlsmReader) -> pd.DataFrame:
    """Shunts: barra (Z→W), MVAr con signo pandapower (capacitor<0, reactor>0)."""
    h, rows = _sheet(reader, "basic data shunt")
    ct = _col(h, "Terminal")
    cq = _col(h, "Qact")
    ccap, cind = _col(h, "C:Reac.Pow"), _col(h, "L:Reac.Pow")
    out = []
    for r in rows:
        def g(c):
            return r[c] if 0 <= c < len(r) else ""
        bus = zw(g(ct))
        if not bus.startswith("W"):
            continue
        name = str(g(0))
        qact = _num(g(cq))
        # tipo por NOMBRE primero (capacitor/reactor); de lo contrario por C vs L
        nl = name.lower()
        if "reactor" in nl:
            is_reactor = True
        elif "capacitor" in nl or "capacit" in nl:
            is_reactor = False
        else:
            cap, ind = _num(g(ccap)), _num(g(cind))
            is_reactor = (ind == ind and ind > 0 and not (cap == cap and cap > 0))
        # signo pandapower: capacitor inyecta reactivo (q<0); reactor absorbe (q>0)
        q = (abs(qact) if is_reactor else -abs(qact)) if qact == qact else 0.0
        if abs(q) > 1e-9:
            out.append({"bus": bus, "q_mvar": q, "name": name.strip(),
                        "kind": "reactor" if is_reactor else "capacitor"})
    return pd.DataFrame(out)


def extract_trafo_oltc(reader: XlsmReader) -> pd.DataFrame:
    """OLTC: une 'basic'(barras HV/LV) y 'loadflow'(control) de trafos 2 dev. por Name."""
    hb, rb = _sheet(reader, "basic data tranf 2 winding")
    chv, clv = _col(hb, "HV-Side"), _col(hb, "LV-Side")
    basic = {}
    for r in rb:
        nm = str(r[0]).strip()
        hv = zw(r[chv]) if 0 <= chv < len(r) else ""
        lv = zw(r[clv]) if 0 <= clv < len(r) else ""
        basic[nm] = (hv, lv)
    hl, rl = _sheet(reader, "Loadflow Transf 2 winding")
    ccm, cset = _col(hl, "Control Mode"), _col(hl, "Voltage Setpoint")
    cnode, ctap = _col(hl, "Controlled Node"), _col(hl, "Tap Changer")
    out = []
    for r in rl:
        def g(c):
            return r[c] if 0 <= c < len(r) else ""
        nm = str(g(0)).strip()
        hv, lv = basic.get(nm, ("", ""))
        cm = str(g(ccm)).strip().upper()
        vset = _num(g(cset))
        if cm == "V" and vset == vset and vset > 0:
            out.append({"name": nm, "hv_bus": hv, "lv_bus": lv,
                        "v_setpoint": vset, "controlled_node": zw(g(cnode))})
    return pd.DataFrame(out)


def export_digsilent_data(xlsx: Path = DEFAULT_XLSX,
                          outdir: Path = DEFAULT_OUTDIR) -> dict[str, object]:
    reader = XlsmReader(xlsx)
    lines = extract_lines(reader)
    shunts = extract_shunts(reader)
    oltc = extract_trafo_oltc(reader)
    outdir.mkdir(parents=True, exist_ok=True)
    lines.to_csv(outdir / "dg_lines.csv", index=False)
    shunts.to_csv(outdir / "dg_shunts.csv", index=False)
    oltc.to_csv(outdir / "dg_trafo_oltc.csv", index=False)
    return {
        "lines": len(lines), "shunts": len(shunts),
        "shunt_mvar_cap": round(float(-shunts.loc[shunts.q_mvar < 0, "q_mvar"].sum()), 1) if len(shunts) else 0,
        "shunt_mvar_reactor": round(float(shunts.loc[shunts.q_mvar > 0, "q_mvar"].sum()), 1) if len(shunts) else 0,
        "oltc_trafos": len(oltc),
        "outdir": str(outdir),
    }

#!/usr/bin/env python3
"""Extrae los puntos SMC del SENI (con lat/lon) desde el Power BI público del OC.

El Organismo Coordinador publica en su web un mapa "Ubicación" con ~555 puntos de
medición comercial (SMC), cada uno con latitud, longitud, nombre del punto, tipo
(RETIRO / CENTRAL / UNR / GENERACION), tensión y agente. Ese mapa es un reporte
Power BI "publish-to-web"; su API anónima de datos exige el handshake de sesión que
hace el navegador, así que aquí usamos Playwright (Chromium real).

Flujo (pensado para re-ejecutarse cuando el OC actualice los puntos):

1. (auto) Descubrir el reporte: cargar la página del OC y leer el iframe de
   `app.powerbi.com/view?r=<token>`. Así el flujo NO depende de un token fijo;
   si el OC publica un token nuevo, se detecta solo.
2. Abrir el reporte y navegar sus páginas (`Page navigation`), priorizando la del
   mapa (MAPAS / Ubicación).
3. Interceptar las respuestas `querydata` (traen las filas del visual).
4. Decodificar el formato comprimido de Power BI (ValueDicts + máscaras R/Ø).
5. Detectar la tabla con coordenadas (lat ~17..20, lon ~-72..-68 = R. Dominicana)
   y escribir un CSV normalizado.

Requisitos (una sola vez en el entorno local):

    .venv\\Scripts\\python -m pip install playwright
    .venv\\Scripts\\python -m playwright install chromium

Uso:

    .venv\\Scripts\\python scripts/scrape_oc_smc.py                 # auto-descubre
    .venv\\Scripts\\python scripts/scrape_oc_smc.py --headed         # ver el navegador
    .venv\\Scripts\\python scripts/scrape_oc_smc.py --token <r=...>  # forzar un reporte

Salidas:
    data/external/oc_smc_points.csv        (normalizado: lat,lon,punto,tipo,tension,agente)
    data/external/oc_smc_points_raw.csv    (columnas crudas tal cual del Power BI)
    data/external/raw_pbi/querydata_*.json (respuestas crudas, para auditar)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "external"
RAW_DIR = OUT_DIR / "raw_pbi"

# Página del OC donde vive el mapa. Constante (no depende del token del reporte).
OC_PAGE_URL = (
    "https://www.oc.do/Informes/Administraci%C3%B3n-del-MEM/"
    "Sistema-de-Medici%C3%B3n-Comercial"
)

# Token conocido del reporte con el mapa de puntos (se intenta primero; si falla,
# el flujo lo vuelve a descubrir desde la página del OC).
KNOWN_MAP_TOKEN = (
    "eyJrIjoiMDJjMzkxY2EtMzI1OS00MjkwLTg1YTUtZTMwYzc4YTllOGFiIiwidCI6ImQwMDQwNThk"
    "LThlN2QtNGMzYy05ZmRmLTRjYmM2NWQxOWQyNiIsImMiOjJ9"
)

# Rango geográfico de la República Dominicana (para detectar lat/lon).
LAT_MIN, LAT_MAX = 17.0, 20.5
LON_MIN, LON_MAX = -72.5, -68.0


# --------------------------------------------------------------------------- #
# Decodificación del formato `querydata` de Power BI
# --------------------------------------------------------------------------- #
def decode_data_shape(ds: dict) -> tuple[list[str], list[list]]:
    """Decodifica un bloque `DS` de un querydata de Power BI a filas planas.

    Maneja `ValueDicts` (texto como índice a diccionario), la máscara `R` (el
    valor se repite de la fila anterior) y la máscara `Ø` (valor nulo).
    """
    value_dicts = ds.get("ValueDicts", {})
    ph = ds.get("PH") or ds.get("SH") or []
    dm0: list = []
    for block in ph:
        for key, val in block.items():
            if key.startswith("DM"):
                dm0 = val
                break
        if dm0:
            break

    columns: list[dict] = []
    rows: list[list] = []
    prev: list = []
    for entry in dm0:
        if "S" in entry:  # metadata de columnas (primera fila del shape)
            columns = entry["S"]
            prev = [None] * len(columns)
        c_values = entry.get("C", [])
        repeat_mask = entry.get("R", 0)
        null_mask = entry.get("Ø", 0)
        row: list = [None] * len(columns)
        ci = 0
        for i in range(len(columns)):
            if null_mask & (1 << i):
                row[i] = None
                continue
            if repeat_mask & (1 << i):
                row[i] = prev[i] if i < len(prev) else None
                continue
            if ci >= len(c_values):
                row[i] = None
                continue
            value = c_values[ci]
            ci += 1
            dn = columns[i].get("DN")
            if dn and isinstance(value, int):
                pool = value_dicts.get(dn, [])
                value = pool[value] if 0 <= value < len(pool) else value
            row[i] = value
        prev = row
        rows.append(row)

    colnames = [c.get("N", f"c{i}") for i, c in enumerate(columns)]
    return colnames, rows


def parse_querydata(payload: dict) -> list[dict]:
    """Devuelve las tablas decodificadas con nombres de columna legibles."""
    tables: list[dict] = []
    for result in payload.get("results", []):
        data = (((result or {}).get("result") or {}).get("data")) or {}
        select = data.get("descriptor", {}).get("Select", [])
        name_by_token = {s.get("Value"): s.get("Name", s.get("Value")) for s in select}
        for ds in data.get("dsr", {}).get("DS", []):
            tokens, rows = decode_data_shape(ds)
            headers = [name_by_token.get(t, t) for t in tokens]
            tables.append({"headers": headers, "rows": rows})
    return tables


def _to_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)[A-Za-z]*\s*", value)
        if m:
            return float(m.group(1))
    return None


def looks_geographic(headers: list[str], rows: list[list]) -> bool:
    if re.search(r"lat|lon|long|coord|gps", " ".join(map(str, headers)), re.I):
        return True
    for row in rows[:30]:
        nums = [v for v in (_to_float(c) for c in row) if v is not None]
        if any(LAT_MIN <= v <= LAT_MAX for v in nums) and any(
            LON_MIN <= v <= LON_MAX for v in nums
        ):
            return True
    return False


def normalize_table(headers: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    """Mapea las columnas crudas del Power BI a nombres estables para el join."""
    idx: dict[str, int] = {}
    for i, h in enumerate(headers):
        hl = str(h).lower()
        if "lat" in hl and "lat" not in idx:
            idx["lat"] = i
        elif ("lon" in hl or "long" in hl) and "lon" not in idx:
            idx["lon"] = i
        elif ("punto" in hl or "nombre" in hl) and "punto" not in idx:
            idx["punto"] = i
        elif "tipo" in hl and "tipo" not in idx:
            idx["tipo"] = i
        elif ("tension" in hl or "tensión" in hl or "kv" in hl) and "tension" not in idx:
            idx["tension"] = i
        elif ("agente" in hl or "empresa" in hl) and "agente" not in idx:
            idx["agente"] = i

    # Respaldo: si no se identificó lat/lon por nombre, ubicarlas por rango.
    if "lat" not in idx or "lon" not in idx:
        for i in range(len(headers)):
            vals = [_to_float(r[i]) for r in rows[:30] if i < len(r)]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            if "lat" not in idx and all(LAT_MIN <= v <= LAT_MAX for v in vals):
                idx["lat"] = i
            elif "lon" not in idx and all(LON_MIN <= v <= LON_MAX for v in vals):
                idx["lon"] = i

    fields = ["lat", "lon", "punto", "tipo", "tension", "agente"]
    out_headers = [f for f in fields if f in idx]
    out_rows = []
    for r in rows:
        out_rows.append(
            [
                (_to_float(r[idx[f]]) if f in ("lat", "lon") else r[idx[f]])
                if idx[f] < len(r)
                else None
                for f in out_headers
            ]
        )
    return out_headers, out_rows


# --------------------------------------------------------------------------- #
# Navegación con Playwright
# --------------------------------------------------------------------------- #
def discover_tokens(page) -> list[str]:
    """Carga la página del OC y devuelve los tokens `r=` de los iframes Power BI."""
    print(f"Descubriendo reporte desde: {OC_PAGE_URL}")
    page.goto(OC_PAGE_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(8_000)
    tokens: list[str] = []
    seen: set[str] = set()

    def collect() -> None:
        for fr in page.frames:
            m = re.search(r"app\.powerbi\.com/view\?r=([\w%-]+)", fr.url)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                tokens.append(m.group(1))

    collect()
    for label in ["Ubicación", "Monitoreo", "SMC Habilitados"]:
        try:
            el = page.get_by_text(label, exact=False).first
            if el.count() and el.is_visible():
                el.click(timeout=4_000)
                page.wait_for_timeout(5_000)
                collect()
        except Exception:
            continue
    print(f"  tokens descubiertos: {len(tokens)}")
    return tokens


def scrape_token(page, token: str, soak_ms: int) -> list[dict]:
    """Abre un reporte, navega sus páginas y captura las respuestas `querydata`."""
    captured: list[dict] = []

    def on_response(response):
        if "querydata" not in response.url:
            return
        try:
            body = response.json()
        except Exception:
            return
        captured.append(body)
        (RAW_DIR / f"querydata_{len(captured):02d}.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  [capturado] querydata #{len(captured)}")

    page.on("response", on_response)
    embed_url = "https://app.powerbi.com/view?r=" + token
    print(f"Abriendo reporte: {embed_url}")
    page.goto(embed_url, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(soak_ms)

    nav = page.locator("div[aria-label^='Page navigation']")
    try:
        count = nav.count()
    except Exception:
        count = 0
    names = []
    for i in range(count):
        try:
            names.append((nav.nth(i).inner_text(timeout=1_000) or "").strip())
        except Exception:
            names.append("")
    if names:
        print(f"  páginas: {names}")
    order = sorted(range(count), key=lambda i: 0 if re.search(r"mapa|ubic", names[i], re.I) else 1)
    for i in order:
        try:
            nav.nth(i).click(timeout=6_000)
            print(f"  -> página '{names[i] or i}'")
            page.wait_for_timeout(soak_ms)
        except Exception:
            pass

    for label in ["RETIROS", "INYECCIONES"]:
        try:
            bm = page.locator("div[aria-label^='Bookmark']", has_text=label).first
            if bm.count():
                bm.click(timeout=5_000)
                page.wait_for_timeout(soak_ms)
        except Exception:
            continue

    page.wait_for_timeout(soak_ms)
    page.remove_listener("response", on_response)
    return captured


def best_geographic_table(captured: list[dict]) -> tuple[list[str], list[list]]:
    headers: list[str] = []
    rows: list[list] = []
    for body in captured:
        for table in parse_querydata(body):
            if table["rows"] and looks_geographic(table["headers"], table["rows"]):
                if len(table["rows"]) > len(rows):
                    headers, rows = table["headers"], table["rows"]
    return headers, rows


# --------------------------------------------------------------------------- #
def run(headed: bool, soak_ms: int, token: str | None, discover: bool) -> int:
    from playwright.sync_api import sync_playwright

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        # Orden de intento: token explícito > token conocido > auto-descubierto.
        candidates: list[str] = []
        if token:
            candidates = [token]
        else:
            if not discover:
                candidates.append(KNOWN_MAP_TOKEN)

        headers: list[str] = []
        rows: list[list] = []
        for tok in candidates:
            headers, rows = best_geographic_table(scrape_token(page, tok, soak_ms))
            if rows:
                break

        if not rows and not token:
            # Auto-reparación: descubrir tokens desde la página del OC y probarlos.
            for tok in discover_tokens(page):
                if tok in candidates:
                    continue
                headers, rows = best_geographic_table(scrape_token(page, tok, soak_ms))
                if rows:
                    break

        browser.close()

    if not rows:
        print(
            "\nNo se encontró una tabla con lat/lon. Revisa data/external/raw_pbi/*.json "
            "(o prueba --headed y súbele a --soak)."
        )
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # CSV crudo (columnas tal cual del Power BI, por trazabilidad).
    (OUT_DIR / "oc_smc_points_raw.csv").write_text(
        "\n".join(
            [",".join(map(str, headers))]
            + [",".join("" if c is None else str(c) for c in r) for r in rows]
        ),
        encoding="utf-8",
    )
    # CSV normalizado para el join.
    n_headers, n_rows = normalize_table(headers, rows)
    out_csv = OUT_DIR / "oc_smc_points.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(n_headers)
        writer.writerows(n_rows)
    print(f"\nOK -> {out_csv}  ({len(n_rows)} puntos)")
    print(f"     columnas normalizadas: {n_headers}")
    print(f"     columnas crudas      : {headers}")
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--headed", action="store_true", help="Mostrar la ventana del navegador.")
    ap.add_argument("--soak", type=int, default=15_000, help="ms de espera por etapa.")
    ap.add_argument("--token", default=None, help="Forzar un token `r=...` específico.")
    ap.add_argument(
        "--discover",
        action="store_true",
        help="Ignorar el token conocido y descubrirlo desde la página del OC.",
    )
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        run(headed=args.headed, soak_ms=args.soak, token=args.token, discover=args.discover)
    )

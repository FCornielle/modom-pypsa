# Fuentes de datos del proyecto (guía única para el agente)

Catálogo **homologado** de todas las fuentes que alimentan el modelo y la plataforma.
Cada fuente sigue el mismo formato: **origen · cadencia · dónde guardar · qué alimenta ·
cómo incorporar (extractor + estado) · llaves de cruce**.

> **Para el agente (Grace):** cuando el usuario lo indique —o cuando haya publicación
> nueva— (1) descarga/ubica el archivo, (2) guárdalo en la ruta canónica de abajo
> respetando el nombre del OC, (3) corre el extractor indicado, (4) **no inventes
> valores**: si falta un archivo o un dato, deja el paso pendiente y avísalo. Las
> coordenadas reales del OC y los datos del MODOM **nunca** se sobrescriben con
> estimaciones.

## Convención de carpetas (destino canónico)

```
data/raw/                              # 1  Caso MODOM (.xlsm)  — núcleo
data/external/oc_smc/                  # 2  Puntos SMC del mapa Power BI (generado)
data/external/transacciones/           # 3  PDF transacciones económicas (mensual)
data/external/unifilar/                # 4  Unifilar SENI (PDF, mensual)
data/external/plano/                   # 5  Plano geográfico (PDF, mensual)
data/external/programacion_seni/       # 6  PDD/PSD/VEROPE (diario/semanal)
  ├─ diaria/  semanal/  verope/  misc/
data/external/digsilent/               # 7  Export de elementos DIgSILENT (a pedido)
```

> Nota: algunos archivos se subieron antes en rutas sueltas (p.ej. `data/05. UNIFILAR…`,
> `data/external/PDD 11-06-26/`). El destino canónico es el de arriba; al reincorporar,
> moverlos ahí.

## Tabla resumen

| # | Fuente | Cadencia | Guardar en | Alimenta | Extractor / estado |
|---|--------|----------|------------|----------|--------------------|
| 1 | **Caso MODOM** (`.xlsm`) | diario/mensual | `data/raw/` | capa canónica + despacho + red (núcleo) | pipeline `scripts/build_*.py` · **operativo** |
| 2 | **Mapa SMC del OC** (Power BI) | ocasional | `data/external/oc_smc/` (gen.) | coords lat/lon de barras → mapa | `scrape_oc_smc.py` + `join_smc_coordinates.py` · **operativo** |
| 3 | **PDF transacciones** (`OC-GC-07-IMTE*`) | mensual | `data/external/transacciones/` | puente PUNTO→ID SMC→barra (validar coords) | manual · **sin extractor** |
| 4 | **Unifilar SENI** (PDF) | mensual | `data/external/unifilar/` | combustible por central (hecho); impedancias trafo/línea (futuro) | listas curadas en `dashboard.classify_fuel` · **parcial** |
| 5 | **Plano geográfico** (PDF) | mensual | `data/external/plano/` | rescata coords de barras "en el mar" (IDW) | `extract_plano_coords.py` · **operativo** |
| 6 | **Programación del SENI** (PDD/PSD/VEROPE) | diario/semanal | `data/external/programacion_seni/` | CVP declarado + combustible, caso vigente, embalses | `build_declared_cvp.py` (a crear)… · **parcial** |
| 7 | **Export DIgSILENT** (`.xlsx`) | a pedido | `data/external/digsilent/` | reactivo de red (R/X+carga, shunts, OLTC, Q gen) → AC | `build_digsilent_data.py` · **parcial (2023)** |

---

## 1. Caso MODOM (`.xlsm`) — núcleo
- **Origen:** workbook diario del SENI (exportado de PowerFactory/DIgSILENT por el OC).
- **Cadencia:** un caso por día de operación (también versiones mensuales).
- **Guardar en:** `data/raw/MODOM_DIARIO_<dd-mm-aaaa>_V###.xlsm`.
- **Alimenta:** TODA la capa canónica (barras, ramas, generadores, demanda, snapshots),
  el despacho PyPSA, y la verdad de referencia (`S_DESPACHOM`, `FLUJO_ACTIVA`, `P_ENS`…).
- **Cómo incorporar:** flujo del README §"Flujo completo de recarga" (inventory →
  build_snapshots/buses/branches/generators/loads/gen_time_series → build_pypsa_network
  → build_modom_results → validate_against_modom).
- **Llaves:** barras `W…`, generador `G3…`, 48 periodos (usar día 1 = primeros 24).

## 2. Mapa SMC del OC (Power BI) — coordenadas
- **Origen:** reporte público "Ubicación" del OC (no es archivo; se **scrapea**).
- **Cadencia:** cambia poco; correr de vez en cuando.
- **Guardar en:** se **genera** `data/external/oc_smc/oc_smc_points.csv`.
- **Alimenta:** coords lat/lon de las barras → mapa del dashboard.
- **Cómo incorporar:** `scripts/scrape_oc_smc.py` (Playwright) → `scripts/join_smc_coordinates.py`.
  Detalle en [`docs/oc_smc_coordinates.md`](./oc_smc_coordinates.md).
- **Llaves:** `PUNTO` → barra por nombre (exact/fuzzy); ID SMC `3303-ABCOF-T01` → `WABCOF`.

## 3. PDF de transacciones económicas — auxiliar de coordenadas
- **Origen:** informe mensual del OC (`OC-GC-07-IMTE-*.pdf`).
- **Cadencia:** mensual.
- **Guardar en:** `data/external/transacciones/`.
- **Alimenta:** puente `PUNTO → ID SMC → barra` (Tabla 19) para validar/ampliar el cruce.
- **Cómo incorporar:** hoy **manual** (ningún script lo consume todavía).
- **Llaves:** token central del ID SMC = código de barra.

## 4. Unifilar del SENI (PDF) — combustible (e impedancias futuras)
- **Origen:** diagrama unifilar mensual del OC (`*UNIFILAR SENI*.pdf`).
- **Cadencia:** mensual.
- **Guardar en:** `data/external/unifilar/`.
- **Alimenta:** **combustible por central** (ya usado en `dashboard.classify_fuel`); a
  futuro Ucc%+MVA de trafos y longitud+conductor de líneas (mejora de impedancias).
- **Cómo incorporar:** hoy las listas de combustible están curadas en el código; las
  impedancias son trabajo futuro.
- **Llaves:** nombre de central.

## 5. Plano geográfico de transmisión (PDF) — rescate de coordenadas
- **Origen:** plano mensual del OC (vectorial, `*Plano*Lineas*.pdf`).
- **Cadencia:** mensual.
- **Guardar en:** `data/external/plano/`.
- **Alimenta:** coords de barras sin punto SMC (las "en el mar") por **IDW local**.
- **Cómo incorporar:** `scripts/extract_plano_coords.py` (corre **después** de
  `join_smc_coordinates.py`). Detalle en [`docs/oc_smc_coordinates.md`](./oc_smc_coordinates.md).
- **Llaves:** etiqueta del plano → barra por tokens del nombre. **Nunca** pisa coords reales.

## 6. Programación del SENI (PDD/PSD/VEROPE) — feed diario/semanal
- **Origen:** [OC → Operación → Programación del SENI](https://www.oc.do/Informes/Operación-del-SENI/Programación-del-SENI).
- **Cadencia:** diaria (PDD) / semanal (PSD, VEROPE).
- **Guardar en:** `data/external/programacion_seni/{diaria,semanal,verope,misc}/`.
- **Alimenta:** CVP declarado + combustible oficial (VEROPE), caso operativo vigente +
  validación diaria (PDD), niveles de embalse para hidro (PSD).
- **Cómo incorporar:** ver el detalle completo en
  [`docs/oc_programacion_seni.md`](./oc_programacion_seni.md).
- **Llaves:** `generator_id` (`G3…`), barras `W…`. **No** trae red → no desbloquea el AC.

## 7. Export de DIgSILENT (`.xlsx`) — reactivo de red (para el AC)
- **Origen:** modelo PowerFactory del OC (pedir un **export de elementos**; o el `.pfd`
  nativo, que es binario y solo se abre con PowerFactory).
- **Cadencia:** a pedido (idealmente la versión completa y vigente).
- **Guardar en:** `data/external/digsilent/` (el `.pfd` se ignora en git por tamaño).
- **Alimenta:** R/X + carga de línea, inventario de shunts (cap/reactor), control OLTC,
  límites de Q de generadores → el **flujo AC de 24 h**.
- **Cómo incorporar:** `scripts/build_digsilent_data.py` (mapea terminales `Z…`→barras `W…`).
- **Estado:** el export 2023 cubre solo 114/592 líneas → **falta el export completo y
  vigente** para reconstruir la red con impedancias autoritativas. Llaves: `Z→W`.

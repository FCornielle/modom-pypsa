# Estado del proyecto modom-pypsa

Documento de continuidad: qué hay, cómo encaja y qué falta. Para detalle por componente
ver los otros `docs/*.md` (canonical_schema, pypsa_network, validation_harness,
digsilent_export_spec, fuentes_datos, oc_programacion_seni, etc.).

## Objetivo
Reproducir, lo más fiel posible, el operativo diario del SENI (Rep. Dominicana) que el
**OC** publica con **MODOM** (GAMS = UC + despacho DC con factores de pérdidas y flowgates;
**DIgSILENT/PowerFactory** = flujo AC). Lo hacemos con **PyPSA** (DC) + **pandapower** (AC),
auditable en una plataforma web, para luego correr escenarios (agregar/quitar elementos).

## Arquitectura (4 capas)

### 1. Capa canónica MODOM — `data/processed/**`
Tablas limpias derivadas del workbook MODOM por `scripts/build_*.py`:
`buses/buses.csv` (717 barras), `generators/generators.csv`, `branches/`,
`loads_time_series/`, `snapshots/`, `generator_availability/`, `renewable_profiles/`,
`pypsa_branch_components/{lines_v1,transformers_v1}.csv`, y la verdad-terreno MODOM en
`modom_results/` (`modom_generator_dispatch`, `modom_bus_voltage`, `modom_branch_flows`,
`nodal_factors`, `modom_bus_ens`, reactiva, shunts). VEROPE: `external/programacion_seni/
verope/declared_cvp.csv`.

### 2. Despacho DC — `pypsa_network.py`
`build_network(use_modom_commitment=True, min_sync_fraction=0.0)` →
`solve_network` (HiGHS). LP de costo mínimo (Σ CVP·p) por barra en por-unidad:
- **Commitment tomado del MODOM** (no se re-decide): unidades que el OC despachó quedan ON
  con su Pmin; el resto OFF. VRE topada por pronóstico (`renewable_profiles`).
- **Factores de nodo** del MODOM aplicados a la demanda (`effective_load = load×factor_retiro`).
- **CVP declarado VEROPE** como override.
- Holguras: `unserved` (cara) y `dump` (sobre-generación) mantienen el LP factible.
- **Flowgates del MODOM** (`e_fgate`) impuestos como restricción dura simétrica
  `-FLGTMAX ≤ Σ coef·flujo ≤ FLGTMAX` (`_flowgate_constraint`); es la representación
  N-1 fiel al OC. Opcional: si faltan las tablas, la red corre sin flowgates.
- `min_sync_fraction` (regulación de frecuencia) y `regulation_floor`/
  `effective_nodal_prices` existen como infraestructura (default off).
Caso base en `results/pypsa_basecase/` (genera `scripts/run_dispatch_basecase.py`).

### 2b. MILP completo del MODOM — `pypsa_milp.py`
`build_milp_network()` + `solve_milp()` **re-deciden el commitment** (a diferencia de 2, que
lo toma fijo). Reconstruye las familias de ecuaciones del MODOM que antes se tomaban como
entrada, con los parámetros reales del workbook (ingeridos por `modom_params.py` +
`scripts/build_modom_params.py` → `data/processed/commitment/` y `hydro/`):
- **Commitment binario** (`committable`): costos de arranque (proxy, `C_ARR` no tabulado),
  `min_up_time` (TARR; TMO vacío en el workbook), `min_down_time` (TMPA/TPAR), rampas RS/RB
  donde se declaran, estado inicial ACC_INI, nº máx de arranques NAMX (eq. 1, 3–4, 16–24).
- **Reservas RPF/RSF co-optimizadas** (`_reserve_constraint`): headroom `P+r≤Pmax·u`, tope de
  margen `r≤MR·u`, requisito del sistema `Σr+ξ≥PORS·ΣP` (PORS=3%) con holgura penalizada a
  CVRRF=2e6 (eq. 7–15). Márgenes de e_datgen (MRPF 69 uds, MRSF 40 uds).
- **Servicios auxiliares** (eq. 33): `SSA=PMX·SSAA` como consumo fijo por barra.
- **Embalses** (eq. 34–36): estructura de tope de energía diaria; el workbook no puebla
  RENDH/aportes, así que la hidro se acota por disponibilidad (documentado).
- Reutiliza flujo DC, límites térmicos y **flowgates** de la capa 2.
Resuelve en ~30 s (HiGHS, 2267 binarias, gap 2%). Resultados en `results/pypsa_milp/`
(`scripts/run_milp.py`). **Validación vs MODOM**: total del sistema por hora err. 0.5%
(casi exacto), despacho por unidad R²≈0.82 — más bajo que el commitment-fijo (0.94) porque
el MILP re-optimiza libremente y el commitment real del OC embebe contratos/must-run que no
están en las ecuaciones publicadas. **Hallazgo: reproducir las ecuaciones ≠ reproducir el
despacho exacto.** Los dos modelos son complementarios (2 = fiel al despacho; 2b = fiel a
las ecuaciones). Precios: el MILP no da duales → usar `effective_nodal_prices` (como en 2).

### 3. Verificación AC — `ac_digsilent.py` + `ac_inject.py`
- `build_from_digsilent(export_dir)`: arma la red pandapower NATIVA desde el export
  DIgSILENT `salida_PDD_*` (terminales fusionadas por interruptores cerrados + jumpers
  via union-find; líneas/trafos por PATH de terminal; gens síncronos como PV agregados,
  VRE como PQ, slack = Punta Catalina). Guarda `for_by_bus`, `forname_to_bus`,
  `fors_by_bus` (cruce W-code, recuperado de `for_name` + `loc_name` + Z→W de subestación).
- `inject_modom_dispatch`: inyecta un despacho (MODOM o PyPSA) por `for_name`; conserva las
  consignas de tensión, escala carga, y rellena la demanda no-cruzada con la del export
  escalada → balance fiel a la demanda MODOM (slack físico).
- `run_ac_modom(export, hour, gen_disp=None)`: build → inject → poda islas → `runpp` →
  agrega V/ángulo y cargabilidad a las 717 barras MODOM. **Converge 24/24.**
- Cobertura del cruce: gen ~95%, carga ~81% (resto: W-codes no presentes en el export).
- Export vigente: `data/external/salida_PDD_30_09_2025_20260613_022117` (inputs-only;
  no trae el flujo resuelto → validación por convergencia + tensiones realistas, no número
  a número). Spec para pedir uno mejor: `docs/digsilent_export_spec.md`.

### 4. Lazo iterativo DC↔AC→MODOM (Fase 3.4) — `iterative.py` + `loss_factors.py`
Reproduce GAMS↔PowerFactory: PyPSA despacha → AC mide pérdidas → se re-estiman los
**factores de nodo** (`update_loss_factors`: escala la forma espacial del MODOM a las
pérdidas AC) → re-despacha, hasta `max|Δfactor|<tol`. Una corrida = 24h (matriz factores
hora×barra; 1 solve PyPSA + 24 AC por iteración externa). `scripts/run_iterative.py --all`
(~5-8 min). Persiste en `results/runs/<run_id>/` (manifest, iterations, ac_bus_voltages,
ac_branch_loading, summary_by_hour, dispatch_dc, nodal_prices, loss_factors_final) —
**gitignored**.

## Plataforma web — `src/modom_pypsa/webapp/`
FastAPI + Jinja + HTMX, diseño "GridLab" (tema claro, sidebar, `static/gridlab.css`).
Levantar: `uvicorn modom_pypsa.webapp.app:app --app-dir src` → http://localhost:8000.
- **`app.py`**: rutas. **`data_access.py`**: lee corridas de `results/runs/` (+
  `ensure_seed_runs` envuelve `data/processed/ac_modom` si no hay corridas).
  **`charts.py`**: figuras Plotly + `network_map_div` (mapa animado: líneas por nivel de
  tensión con leyenda toggle, barras por métrica, scroll-zoom) + `anim_controller` (JS
  propio: loop 24→01, pausa, valor sobre la línea vertical) + `modom_mix_div`,
  `modom_flows_anim_div`, `voltage_profile_anim_div`, `loading_bars_anim_div`,
  `dc_vs_ac_div`, `convergence_div`, `series_line_div`.
- **Fuente de la pestaña MODOM·PDD**: el **último PDD publicado por el OC** ingerido en
  `data/processed/pdd/<fecha>/` (`scripts/build_pdd_case.py`, parser `pdd.py`). El `/` toma
  el más reciente (sin selector); fallback al workbook `modom_results/` si no hay PDD. El PDD
  trae despacho (G3-codes), demanda (`DEMANDA DEL SENI`), factores de nodo (W-codes),
  tensiones p.u. (~28 barras monitoreadas) y cargabilidad % por línea (etiqueta Z nativa).
- **Páginas**: `MODOM·PDD` (`/`, landing: KPIs + despacho por tecnología + mapa de costo
  por barra + curva de costo con selector de barra (default Palamara) + mapa de tensiones
  + cargabilidad por rama, todo 24h animado) · `PyPSA·Modelo` (`/pypsa`: mezcla, precio LP,
  líneas) · `Pandapower·Modelo AC` (`/ac`: mapa por métrica tensión/costo/ΔvsMODOM +
  perfil + cargabilidad + convergencia del lazo + DC-vs-AC) · `Auditoría` (`/audit`: por
  equipo, serie 24h) · `Metodología` (`/metodologia`: ecuaciones MODOM vs nuestras, MathJax).

## Pricing (fidelidad)
El **precio de energía** del LP es ~0 a mediodía (excedente VRE gratis): correcto para un
modelo energético, pero NO implica operación 100% renovable — la síncrona corre por
regulación de frecuencia (la PV no la da). El **costo por barra fiel al MODOM** =
`mc_sistema(hora) × factor_nodo(barra)`, donde `mc_sistema` = CVP de la unidad síncrona
flexible (0<p<Pmax) más cara del despacho MODOM. Réplica exacta de los precios MODOM
requiere co-optimizar reservas (pendiente).

## Estado
- ✅ Capa canónica; despacho DC fiel (commitment + factores + CVP); validación vs MODOM
  (`validation.py`, R² despacho ~0.94).
- ✅ AC convergente sobre la red real; inyección por `for_name`; agregación a 717 barras.
- ✅ Lazo iterativo 24h; costo por barra fiel al MODOM.
- ✅ Plataforma web completa (5 páginas) con mapas animados sincronizados.
- ✅ **Flowgates (seguridad N-1 fiel al MODOM)**: la hoja `e_fgate` define 2 flowgates
  activos (fg1 ≤ 200 MW, 7 ramas; fg2 ≤ 670 MW, 3 ramas; fg3 vacío). En MODOM la N-1 se
  codifica como flowgates (interfaces críticas con límite derateado), no como SCLOPF.
  Ingesta: `scripts/build_flowgates.py` → `data/processed/flowgates/` (parser en
  `flowgates.py`). En el LP se imponen como restricción dura simétrica
  `-FLGTMAX ≤ Σ coef·flujo ≤ FLGTMAX` (`_flowgate_constraint` en `pypsa_network.py`).
  En el caso base no muerden (fg1 máx 82%, fg2 45%); utilización visible en la pestaña
  PyPSA·Modelo (`flowgate_utilization_by_snapshot.csv`).

## Cobertura de ecuaciones (QA vs. transcripción oficial)
El mapeo ecuación-por-ecuación MODOM → PyPSA vive en la pestaña **Metodología**
(`webapp/templates/metodologia.html`) y se deriva de la transcripción oficial
`docs/programacion_corto_plazo_modom_transcripcion.md` (V16, §6–§7). Resumen:
- ✅ **Replicado** en el LP/AC: objetivo térmico + déficit (§6.1), límites de generación
  (§7.3), flujo DC y límites térmicos (§7.13.1–2), **flowgates** (§7.13.3), balance nodal
  (§7.15), PNS total (§7.16), flujo AC de verificación (§8.3).
- ➖ **Tomado fijo del MODOM** (no re-optimizado): commitment y sus transiciones (§7.1),
  arranque/parada (§6.1), rampas (§7.7), tiempos mínimos y nº de arranques (§7.8–7.11),
  enclavamiento (§7.12), pérdidas incrementales → vía factor de nodo + lazo AC (§7.14).
- ❌ **No modelado aún**: potencia variable en arranque/parada (§7.2), reservas RPF/RSF/AGC
  co-optimizadas (§7.4–7.6), servicios auxiliares (§7.17), embalses hidroeléctricos (§7.18),
  vertimiento (§6.1).

## Pendiente
- **Integrar el MILP (2b) en la plataforma web** (hoy solo por script/API).
- **Embalses hidroeléctricos completos (§7.18)**: requiere RENDH/aportes que este workbook no
  puebla (DAT_AP vacío) — pedir un caso con esos datos para el balance hídrico real.
- **Enclavamiento (§7.12)**: no hay tabla ENCLAV en el workbook; ingerir si aparece.
- **Precios del MILP**: exponer `effective_nodal_prices` (el MILP no da duales directos).
- **Validación cuantitativa AC**: pedir un export DIgSILENT con el flujo EJECUTADO
  (tensiones resueltas) para comparar barra a barra; el actual es inputs-only.
- Mejorar cobertura del crosswalk de W-codes (tensiones MODOM solo cubren 406/717 barras).
- (Opción futura) **SCLOPF N-1 explícito (LODF)** sobre el núcleo mallado (isla de 668
  barras, excluyendo los 519 puentes radiales) como verificación cruzada de los flowgates.
- (Opción futura) correr proyectos/escenarios con overrides (quitar/añadir equipos).

## Git
Rama `main` (todo integrado y pusheado a `origin`). Ramas históricas:
`feat/phase3-ac-pandapower`, `feat/webapp-gridlab` (ya mergeadas). 49 tests verdes.

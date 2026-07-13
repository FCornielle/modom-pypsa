# modom-pypsa

Reproduce el **operativo diario del SENI** (Rep. Dominicana) que el Organismo Coordinador
(OC) publica con **MODOM** — un MILP en GAMS (unit commitment + despacho DC con factores de
pérdidas y flowgates) verificado con flujo AC en DIgSILENT. Lo reconstruimos con **PyPSA**
(despacho DC) + **pandapower** (verificación AC), auditable en una **plataforma web**.
Primero fiel al MODOM; luego, base para correr escenarios.

> **Principio.** PyPSA y pandapower **corren solos y producen sus propios resultados**. Del
> MODOM tomamos **condiciones iniciales** (commitment, disponibilidad, factores de nodo, CVP,
> flowgates) como *entradas* — no sus corridas como *salidas*. El resultado oficial del OC
> (el **PDD**) es solo referencia, en su propia pestaña.

## Arquitectura — 4 capas (flujo de datos)

| # | Capa | Módulo | Qué hace |
|---|---|---|---|
| 1 | **Canónica MODOM** | `scripts/build_*.py` → `data/processed/**` | Tablas limpias (buses, generators, branches, loads, snapshots, flowgates, `modom_results/*`) desde el workbook MODOM. |
| 2a | **Despacho DC (commitment fijo)** | `pypsa_network.py` | LP de costo mínimo (HiGHS) **dentro del commitment del MODOM**, demanda con factores de nodo, **flowgates como restricción dura** (N-1). Fiel al despacho por unidad (R²≈0.94). Caso base → `results/pypsa_basecase/`. |
| 2b | **MILP completo** | `pypsa_milp.py` | **Re-decide el commitment**: binarios, costos de arranque, tiempos, rampas y **reservas RPF/RSF co-optimizadas** (eq. 1, 3–24, 33 del MODOM). Parámetros de `e_datgen/e_opcn/e_hidro` (`build_modom_params.py`). Resuelve en ~30 s; total del sistema exacto (0.5%), mezcla por unidad diverge (el commitment del OC embebe contratos/must-run fuera de las ecuaciones). → `results/pypsa_milp/`. |
| 3 | **Verificación AC** | `ac_digsilent.py` + `ac_inject.py` | Arma la red real del export DIgSILENT, inyecta NUESTRO despacho por `for_name`, agrega V/cargabilidad a las 717 barras MODOM. Converge 24/24. |
| 4 | **Lazo DC↔AC→MODOM** | `iterative.py` + `loss_factors.py` | Re-estima los factores de nodo desde las pérdidas AC y re-despacha hasta estabilizar (24 h). Persiste en `results/runs/<run_id>/` (gitignored). |

**Ecuaciones.** El mapeo ecuación-por-ecuación MODOM → PyPSA (qué se replica, qué se toma
fijo del MODOM, qué falta) está en la pestaña **Metodología** de la web y se deriva de la
transcripción oficial [`docs/programacion_corto_plazo_modom_transcripcion.md`](./docs/programacion_corto_plazo_modom_transcripcion.md).

## Plataforma web (FastAPI + Jinja + HTMX)

```bash
.venv/Scripts/python.exe -m pip install -e ".[web,pypsa,ac,dev]"   # una vez
.venv/Scripts/python.exe -m uvicorn modom_pypsa.webapp.app:app --app-dir src
# http://localhost:8000
```

Pestañas: **MODOM·PDD** (resultado oficial del día, animado 24 h) · **PyPSA·Modelo**
(despacho DC, commitment fijo) · **Optimizador MILP** (MILP completo: configura las
*consideraciones* —reservas, PORS, flowgates, mín. síncrono—, corre el optimizador en
background y explora el mapa de costo + heatmap de commitment) · **Pandapower·Modelo AC**
(verificación AC + lazo) · **Auditoría** · **Metodología** (37 ecuaciones + cobertura).

## Conceptos clave

- **Pricing.** El precio de energía del LP cae a ~0 a mediodía (excedente solar gratis): real
  para un modelo energético, **no** implica operación 100 % renovable — la térmica/hidro corre
  por regulación de frecuencia (la PV no la da). El **costo por barra fiel al MODOM** = costo
  marginal síncrono × factor de nodo.
- **Flowgates (N-1).** En MODOM la seguridad N-1 se codifica como flowgates (interfaces
  críticas con límite derateado), no como SCLOPF. Se ingieren de `e_fgate`
  (`scripts/build_flowgates.py`) y se imponen como restricción dura del LP.
- **`for_name`** = código MODOM en cada elemento DIgSILENT = llave de cruce.
- **48 períodos MODOM = 2 días**; se usa el **día 1** (primeras 24 h).

## Entorno (Windows)

- Python del proyecto: **`.venv\Scripts\python.exe`** (3.11). Antepón `PYTHONIOENCODING=utf-8`.
- Tests: `.venv\Scripts\python.exe -m pytest -q` (los de AC/iterativo se saltan si falta el
  export DIgSILENT en `data/external/`).

## Actualizar datos

- **Caso nuevo del MODOM** (`.xlsm` en `data/raw/`): correr la cadena `scripts/build_*.py`
  → `build_pypsa_network.py`. Orden y fuentes en [`docs/fuentes_datos.md`](./docs/fuentes_datos.md).
- **PDD del día** (alimenta MODOM·PDD): `scripts/build_pdd_case.py --xlsx <PDD.xlsx>`
  → `data/processed/pdd/<fecha>/`; la pestaña toma el más reciente. Ver
  [`docs/oc_programacion_seni.md`](./docs/oc_programacion_seni.md).

## Estado

Hecho: capa canónica, despacho DC fiel (commitment + factores + CVP VEROPE + **flowgates**),
**MILP completo del MODOM** (unit commitment + reservas co-optimizadas, eq. 1–33), AC
convergente, lazo iterativo 24 h, plataforma web (5 páginas). Pendiente: embalses con
RENDH/aportes (§7.18), enclavamiento (§7.12), integrar el MILP en la web, validación
cuantitativa AC. Detalle en [`docs/ESTADO_PROYECTO.md`](./docs/ESTADO_PROYECTO.md).

## Disclaimer

Workflow de ingeniería en desarrollo activo. Las salidas son artefactos analíticos
reproducibles, no conclusiones operativas, regulatorias o de mercado finales.

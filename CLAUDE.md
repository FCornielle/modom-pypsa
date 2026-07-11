# modom-pypsa — orientación

Reproduce el operativo diario del SENI (RD) que el OC corre con **MODOM** (GAMS +
DIgSILENT), usando **PyPSA** (despacho DC) + **pandapower** (verificación AC), con una
plataforma web para auditarlo. Fiel al MODOM; luego sirve para correr escenarios.

## Entorno (Windows)
- Python del proyecto: **`.venv\Scripts\python.exe`** (3.11). El `python` del sistema es
  3.8 (no sirve). Antepón `PYTHONIOENCODING=utf-8` en los comandos.
- Instalar: `.venv\Scripts\python.exe -m pip install -e ".[web,pypsa,ac,dev]"`.
- Tests: `.venv\Scripts\python.exe -m pytest -q` (49 pasan; los de AC/iterativo se
  saltan si falta el export DIgSILENT en `data/external/`).

## Las cuatro capas (flujo de datos)
1. **Capa canónica MODOM** → `data/processed/**` (buses, generators, branches, loads,
   snapshots, `modom_results/*`). Se arma con `scripts/build_*.py` desde el workbook MODOM.
2. **Despacho DC (PyPSA)** → `pypsa_network.py` (`build_network`, `solve_network`).
   LP por mérito DENTRO del commitment del MODOM; demanda con factores de nodo; holgura
   `unserved`/`dump`. Caso base en `results/pypsa_basecase/`.
3. **Verificación AC (pandapower)** → `ac_digsilent.py` (arma la red real desde el export
   DIgSILENT `salida_PDD_*`) + `ac_inject.py` (inyecta NUESTRO despacho por `for_name` y
   agrega V/cargabilidad a las 717 barras MODOM). **Converge 24/24.**
4. **Lazo iterativo DC↔AC→MODOM** (Fase 3.4) → `iterative.py` + `loss_factors.py`.
   Re-estima factores de nodo desde las pérdidas AC y re-despacha hasta estabilizar.
   Una corrida = 24h. Persiste en `results/runs/<run_id>/` (gitignored).

## Plataforma web (FastAPI + Jinja + HTMX) — `src/modom_pypsa/webapp/`
Levantar: `.venv\Scripts\python.exe -m uvicorn modom_pypsa.webapp.app:app --app-dir src`
(http://localhost:8000). Menú: **MODOM·PDD** (resultados oficiales del día) ·
**PyPSA·Modelo** (despacho DC) · **Pandapower·Modelo AC** (verificación AC + auditoría del
lazo) · **Auditoría** (por equipo) · **Metodología** (ecuaciones MODOM vs nuestras).
- `app.py` rutas, `data_access.py` lee corridas, `charts.py` figuras Plotly (mapas
  animados con controlador JS propio: loop, pausa, valor sobre la línea).
- **MODOM·PDD se alimenta del último PDD publicado** ingerido en `data/processed/pdd/<fecha>/`
  (`scripts/build_pdd_case.py` --xlsx <PDD.xlsx>; parser `pdd.py`). El `/` toma el más
  reciente, sin selector; fallback al workbook si no hay PDD. El PDD trae despacho, demanda,
  factores de nodo, tensiones p.u. y cargabilidad por línea (hoja `Analisis_Electrico`).
- Generar la corrida del día: `.venv\Scripts\python.exe scripts/run_iterative.py --all`.

## Pricing (importante)
El precio de energía del LP cae a ~0 a mediodía (excedente solar gratis) — es real para un
modelo puramente energético, NO significa que el sistema opere solo con renovables (la
térmica/hidro debe correr por regulación de frecuencia, que la PV no da). El **costo por
barra fiel al MODOM** = costo marginal del despacho MODOM × factor de nodo. Ver
`docs/ESTADO_PROYECTO.md` y la pestaña Metodología.

## Convenciones
- `for_name` = código MODOM en cada elemento DIgSILENT (barras `W…`, gens `G…`) = LLAVE de
  cruce. Cobertura del cruce ~70-95% (divergencias de W-code; hay crosswalk parcial por
  `loc_name`/subestación).
- 48 períodos del MODOM = 2 días de 24h; se usa el **día 1** (primeras 24h).
- Commit/push solo cuando el usuario lo pide; rama por defecto `main`. Mensajes de commit
  terminan con `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Estado y pendientes
Hecho: capa canónica, despacho DC fiel (commitment+factores+CVP VEROPE), AC convergente,
lazo iterativo 24h, plataforma web completa, **flowgates (seguridad N-1 fiel al MODOM:
fg1≤200MW, fg2≤670MW desde `e_fgate`, restricción dura en el LP)**. Pendiente: reservas
co-optimizadas, SCLOPF N-1 explícito (verificación cruzada de los flowgates), validación
cuantitativa contra un export DIgSILENT con el flujo ejecutado (hoy el export es solo
inputs). Detalle completo en **`docs/ESTADO_PROYECTO.md`**.

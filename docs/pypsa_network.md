# PyPSA network v1

Primer constructor real de `pypsa.Network()` desde la capa canónica
(`src/modom_pypsa/pypsa_network.py`, CLI `scripts/build_pypsa_network.py`).

Es un **despacho económico con restricciones de red linealizado** (LOPF): impone
balance nodal, ley de tensiones de Kirchhoff (KVL) sobre los ciclos de la red y
límites térmicos de rama. No es todavía un flujo de potencia AC.

## Decisiones de modelado v1

### Base por-unidad (`v_nom = 1.0`)

Las impedancias de MODOM (`r`, `x` en `e_datred`, exportadas como `r_pu_hint`,
`x_pu_hint`) ya están en por-unidad. En un LOPF linealizado los flujos dependen
solo de reactancias **relativas**: multiplicar todas las reactancias por una
constante no cambia el reparto de flujos (las restricciones KVL son homogéneas en
`x`). Por eso:

- todas las barras usan `v_nom = 1.0`,
- `x_pu_hint` se usa directamente como reactancia de PyPSA,
- los transformadores quedan 1:1, que es lo correcto en por-unidad.

Beneficio adicional: las barras terminal de generador sin `v_nom_kv` (ver
[`buses.md`](./buses.md)) no causan ningún problema, porque su tensión nominal no
interviene. El `v_nom_kv` real se conserva como columna de metadato
(`n.buses["v_nom_kv"]`) para coloreado y mapas.

### Ramas

Líneas y transformadores se añaden como componentes `Line` con su `r`/`x` en
por-unidad y `s_nom` igual al límite térmico (`fmax_mw`). La columna
`branch_kind` (`line` / `transformer`) preserva la distinción para el dashboard.
La reactancia se acota a un mínimo (`1e-5`) para que KVL sea resoluble.

### Generadores

- `p_nom` = capacidad estática efectiva (`effective_pmax_mw`) o disponibilidad
  máxima observada; `0` si la unidad está deshabilitada.
- `p_max_pu` por snapshot desde `generator_availability` (`available_mw / p_nom`).
- `marginal_cost` = `effective_cvp` (con respaldo a `cvp` y luego un costo alto si
  ambos faltan).
- `p_min` **no** se impone todavía, igual que en el despacho copperplate v1.
- `carrier` = `technology_group` (para agregación por tecnología).

### Demanda

Nodal, por snapshot, desde `loads_time_series` (`p_set_mw` por barra).

### Holgura (energía no suministrada)

Un generador `unserved` muy caro (`marginal_cost = 1e6`) por barra con demanda
garantiza factibilidad incluso con islas o congestión, y entrega un KPI directo de
energía no suministrada por nodo.

## Salidas (`results/pypsa_basecase/`)

- `generation_by_snapshot.csv` — potencia por generador y snapshot
- `load_by_snapshot.csv` — demanda por barra y snapshot
- `line_flows_by_snapshot.csv` — flujo `p0` por rama y snapshot
- `line_loading_by_snapshot.csv` — `|flujo| / s_nom` por rama y snapshot
- `nodal_prices_by_snapshot.csv` — precio marginal nodal por snapshot
- `pypsa_basecase_summary.json` — resumen agregado (servido, no servido, despacho
  por tecnología, congestión)

## Limitaciones explícitas

- LOPF linealizado, no flujo AC; sin tensiones ni reactivos.
- Unidades de impedancia provisionales; la energía no suministrada es una señal
  analítica, no una conclusión operativa final.
- Semántica de tap de transformadores aún pendiente (los transformadores se tratan
  como impedancia serie).
- `renewable_profiles` todavía no se usa como recorte específico de VRE; la
  disponibilidad de `generator_availability` es la única fuente de tope por ahora.

## Ejecución

```bash
pip install -e .[pypsa]
python3 scripts/build_pypsa_network.py            # construye, resuelve y exporta
python3 scripts/build_pypsa_network.py --no-solve  # solo construye y reporta
```

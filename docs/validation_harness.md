# Arnés de validación: fidelidad de PyPSA vs MODOM

Mide **objetivamente** qué tan cerca queda nuestro despacho del que el OC realmente
publica en el MODOM. Es el cimiento del esfuerzo de fidelidad: cada mejora (Fases 1,
2, 3...) se juzga por cuánto sube el **score de fidelidad**, no por opinión.

## Verdad de referencia: lo que el propio MODOM calcula

`scripts/build_modom_results.py` (módulo `modom_pypsa.modom_results`) extrae del
workbook las hojas de **resultados** del MODOM (GAMS + DIgSILENT) y las guarda en
`data/processed/modom_results/`:

| CSV | Hoja MODOM | Contenido | Llave |
|---|---|---|---|
| `modom_generator_dispatch.csv` | `S_DESPACHOM` | despacho activo MW por generador y periodo | `generator_id` (140/140) |
| `modom_branch_flows.csv` | `FLUJO_ACTIVA` | flujo activo MW por rama y periodo | `bus0\|bus1\|circuito` |
| `modom_bus_ens.csv` | `P_ENS` | energía no servida MW por barra y periodo | barra (código W) |

Eje temporal: el MODOM trae 48 periodos (2 días); se toman los **primeros 24** (día 1),
igual que el resto del pipeline.

```powershell
.\.venv\Scripts\python scripts\build_modom_results.py --xlsm data\raw\<caso>.xlsm
```

## Comparación

`scripts/validate_against_modom.py` (módulo `modom_pypsa.validation`) carga nuestros
resultados (`results/pypsa_basecase/`) y la verdad de referencia, alinea por
`generator_id`, por par de barras+circuito (normalizado: ignora orden y etiqueta
`L1`/`c1`) y por barra, y calcula:

- **Despacho por generador**: MAE, RMSE, sesgo, R², error relativo (por unidad/hora y
  total del sistema), más las 12 unidades más divergentes.
- **Flujos de rama**: sobre `|flujo|` (las convenciones de signo difieren).
- **ENS**: total nuestro vs MODOM.
- **`fidelity_score` 0–100** agregado (R² del despacho + cercanía del total del
  sistema + cercanía de flujos).

```powershell
.\.venv\Scripts\python scripts\validate_against_modom.py
# -> results/pypsa_basecase/fidelity_report.json + resumen por consola
```

## Línea base (modelo DC v1, caso plantilla V449)

| Métrica | Valor | Lectura |
|---|---|---|
| **Score de fidelidad** | **55.1 / 100** | punto de partida a mejorar |
| Despacho por unidad/hora | R² 0.74 · MAE 7.7 MW · err 32% | fidelidad media |
| Total del sistema | sesgo **−296 MW** · err 8.7% | despachamos menos: el MODOM cubre **pérdidas AC** que el DC ignora |
| Flujos de rama (528/988) | R² −0.98 · err 136% | **peor brecha**: impedancias `_hint` + `v_nom=1.0` distorsionan el reparto |
| ENS | 1031 vs 2865 MWh | el MODOM marca más déficit (revisar; el caso plantilla puede ser estresado) |

**Diagnóstico que deja la línea base:** la prioridad de fidelidad es la **red**
(impedancias reales + pérdidas + AC), no tanto la lógica de despacho. El sesgo de
−296 MW del total del sistema es consistente con pérdidas no modeladas.

> Nota: el caso `MODOM_DIARIO_dd-mm-yyyy_V449.xlsm` es una **plantilla**; sus
> resultados (sobre todo `P_ENS`) pueden no ser un caso operativo normal. Al cargar un
> caso real fechado, re-correr ambos scripts recalcula la línea base.

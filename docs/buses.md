# Buses

Este bloque implementa la primera versión canónica de `buses`.

## Fuentes usadas

- `MAPEO TODAS LAS BARRAS`: identidad principal de barra
- `e_datred`: evidencia de uso real de la barra dentro de la red

## Decisión operativa actual

La tabla `buses.csv` se construye como la unión de:

- barras presentes en `MAPEO TODAS LAS BARRAS`
- barras que aparecen en `e_datred` aunque no estén en el mapeo

Eso evita perder barras de la red por depender solo de la hoja de mapeo.

## Campos clave

- `bus_id_modom`
- `bus_name`
- `bus_id_legacy`
- `bus_name_legacy`
- `code_changed`
- `appears_in_mapping`
- `appears_in_e_datred`
- `e_datred_endpoint_count`
- `v_nom_kv`
- `v_nom_inference_method`
- `v_nom_confidence`
- `bus_origin`

## Limitación explícita

La cobertura entre `MAPEO TODAS LAS BARRAS` y `e_datred` no es completa.

Para `V449`, el bloque exporta también una auditoría:

- barras en `e_datred` no presentes en el mapeo
- barras del mapeo no vistas en `e_datred`
- barras cuyo `v_nom_kv` sigue sin poder inferirse de forma conservadora

## Regla actual para `v_nom_kv`

La inferencia actual es deliberadamente conservadora:

- `name_explicit`
  - si `bus_name` o `bus_name_legacy` contiene una tensión explícita (`345`,
    `230`, `138`, `69`, `34.5`, `13.8`, etc.), se usa ese valor
- `suffix_E_default`
  - si no hay tensión explícita y la barra termina en `E`, se asigna `138 kV`
- `suffix_F_default`
  - si no hay tensión explícita y la barra termina en `F`, se asigna `69 kV`
- `topology_line_consensus`
  - si la barra sigue sin tensión pero está unida por **línea** (`L...`) a barras
    con una única tensión conocida, se adopta esa tensión (`confidence = medium`).
    Es física real: una línea no cambia el nivel de tensión entre sus extremos.
- `topology_transformer_consensus`
  - consenso residual entre barras de sección (`C`/`D`) a través de transformador,
    `confidence = low`
- `unresolved`
  - barras `K`, `D`, `M` u otras ambiguas quedan pendientes

Eso permite avanzar con una capa de voltajes nominales útil sin inventar
semánticas débiles para barras de terminal o niveles especiales.

## Clasificación de rol de barra (`bus_role`)

Para distinguir una ausencia de `v_nom_kv` **esperada** de un hueco genuino, cada
barra recibe un `bus_role`:

- `generator_terminal`
  - el nombre contiene `TERMINAL` o `VIRTUAL`; son los bornes de baja tensión de
    los generadores detrás de su transformador elevador. Su `v_nom_kv` real es el
    nominal del generador, que `MODOM` no trae explícitamente. **No se inventa**;
    se documenta la ausencia.
- `network`
  - cualquier otra barra.

El resumen expone `unresolved_generator_terminal_count` y `unresolved_network_count`
para que el conteo de barras sin tensión sea interpretable y no un bloque opaco.

> Nota para PyPSA: las impedancias de `MODOM` (`r`, `x` en `e_datred`) ya están en
> por-unidad, por lo que un despacho/LOPF lineal resuelve aunque estas barras
> terminales no tengan `v_nom_kv`. El `v_nom` solo sería imprescindible para un
> flujo de potencia AC no lineal.

## Script

```bash
python3 scripts/build_buses.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/buses/buses.csv`
- `data/processed/buses/buses_reconciliation_summary.json`

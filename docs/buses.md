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
- `bus_origin`

## Limitación explícita

La cobertura entre `MAPEO TODAS LAS BARRAS` y `e_datred` no es completa.

Para `V449`, el bloque exporta también una auditoría:

- barras en `e_datred` no presentes en el mapeo
- barras del mapeo no vistas en `e_datred`

## Script

```bash
python3 scripts/build_buses.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/buses/buses.csv`
- `data/processed/buses/buses_reconciliation_summary.json`

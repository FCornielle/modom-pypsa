# Branches

Este bloque implementa la primera versión canónica de `branches`.

## Fuentes usadas

- `e_datred`: fuente principal de red serie
- `buses`: referencia para validar endpoints

## Decisión operativa actual

La tabla `branches.csv` se construye directamente desde `e_datred` y clasifica
cada activo como:

- `line`
- `transformer`

La clasificación se basa en el prefijo de `circuit_id`:

- `L*` -> `line`
- `T*` -> `transformer`

## Campos clave

- `branch_id`
- `from_bus`
- `to_bus`
- `circuit_id`
- `branch_type`
- `r_pu`
- `x_pu`
- `fmax_mw`
- `in_service_base`
- `closure_flag`

## Validaciones

El bloque exporta una auditoría con:

- referencias a barras no resueltas en `buses`
- colisiones de `branch_base_id`

Si `e_datred` repite la misma pareja `from_bus/to_bus/circuit_id`, el proyecto:

- conserva `branch_base_id` como clave topológica
- genera `branch_id` único con sufijo paralelo (`__p2`, `__p3`, ...)

## Script

```bash
python3 scripts/build_branches.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/branches/branches.csv`
- `data/processed/branches/branches_reconciliation_summary.json`

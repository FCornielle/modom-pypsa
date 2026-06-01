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
- `series_parameter_status`
- `thermal_limit_status`
- `closure_flag_is_binary`
- `operational_status`
- `pypsa_v1_component`
- `pypsa_v1_include`
- `tap_ratio_hint`
- `pypsa_v1_mapping_reason`

## Validaciones

El bloque exporta una auditoría con:

- referencias a barras no resueltas en `buses`
- colisiones de `branch_base_id`
- ramas sin parámetros serie utilizables
- ramas sin límite térmico positivo
- ramas con `closure_flag` no binario
- ramas fuera de servicio en el caso base

Si `e_datred` repite la misma pareja `from_bus/to_bus/circuit_id`, el proyecto:

- conserva `branch_base_id` como clave topológica
- genera `branch_id` único con sufijo paralelo (`__p2`, `__p3`, ...)

## Lectura operativa actual

La capa `branches` ya permite validar topología y límites base, pero todavía no
afirma que la red esté lista para un OPF de PyPSA.

Estado que sí queda trazable:

- `network_topology_ready`: hay ramas, los endpoints resuelven contra `buses` y
  el eje temporal base es coherente con la demanda
- `branch_series_data_ready`: `r_pu`, `x_pu`, `fmax_mw` y `closure_flag`
  pasan controles internos mínimos

Estado que sigue pendiente:

- `branch_units_confirmed_for_pypsa = false`

Eso significa que el proyecto ya puede detectar si la red está
estructuralmente completa, pero todavía no debe reclamar que las impedancias de
MODOM están convertidas o interpretadas de forma final para PyPSA.

## Hallazgo actual sobre `closure_flag`

En `V449` aparecen `10` ramas con `closure_flag` no binario. La evidencia del
catálogo apunta a que este campo no representa solo apertura/cierre:

- `7` casos son `transformer` con valores como `1.03`, `1.10`, `1.20`, `0.98`
  y se interpretan provisionalmente como `tap_ratio_like`
- `3` casos son `line`, pero siempre conectan barras con nombre `TAP ...`, por
  lo que se interpretan provisionalmente como `tap_link_like`

Conclusión operativa actual:

- no tratar `closure_flag` no binario como error de topología
- no traducir todavía esos valores a parámetros finales de PyPSA sin una regla
  explícita de MODOM

## Traducción v1 a PyPSA

La exportación ya deja una regla operativa explícita para la primera
construcción de red:

- `standard_branch`: entra a `PyPSA v1` como `line` o `transformer`
- `transformer_with_tap_ratio`: entra como `transformer` con `tap_ratio_hint`
- `excluded_auxiliary_tap_link`: no entra a `PyPSA v1` como rama serie normal
- `out_of_service_base_case`: queda fuera del caso base

En `V449`, la lectura actual deja:

- `6` transformadores candidatos a `tap_ratio_hint`
- `3` enlaces auxiliares `TAP` excluidos del modelo serie v1
- `1` rama con valor de control no binario pero fuera de servicio en el caso
  base

## Script

```bash
python3 scripts/build_branches.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/branches/branches.csv`
- `data/processed/branches/branches_reconciliation_summary.json`

# PyPSA Branch Components v1

Este bloque toma `branches.csv` y produce una traducción estructurada hacia
componentes de red para `PyPSA v1`.

## Objetivo

Hacer explícita la decisión de qué ramas de `MODOM` entran como:

- `line`
- `transformer`
- exclusiones justificadas de `PyPSA v1`

Sin este paso, la transición desde `branches` hacia la red de `PyPSA` queda
implícita y difícil de auditar.

## Entradas

- `data/processed/branches/branches.csv`
- `data/processed/buses/buses.csv`

## Salidas

- `data/processed/pypsa_branch_components/lines_v1.csv`
- `data/processed/pypsa_branch_components/transformers_v1.csv`
- `data/processed/pypsa_branch_components/excluded_branches_v1.csv`
- `data/processed/pypsa_branch_components/pypsa_branch_components_summary.json`

## Regla v1 actual

- `standard_branch`
  - entra como `line` o `transformer`
- `transformer_with_tap_ratio`
  - entra como `transformer`
  - conserva `tap_ratio_hint`
- `excluded_auxiliary_tap_link`
  - queda fuera del modelo serie `v1`
- `out_of_service_base_case`
  - queda fuera del caso base

## Campos exportados

### `lines_v1.csv`

- `name`
- `bus0`
- `bus1`
- `v_nom_bus0_kv`
- `v_nom_bus1_kv`
- `voltage_pair_status`
- `r_pu_hint`
- `x_pu_hint`
- `s_nom_mva_hint`
- `source_branch_id`
- `source_branch_type`
- `source_row_number`
- `notes`

### `transformers_v1.csv`

- todo lo anterior, más:
- `tap_ratio_hint`
- `has_tap_ratio_hint`
- `tap_side_hint`

### `excluded_branches_v1.csv`

- `branch_id`
- `branch_type`
- `from_bus`
- `to_bus`
- `pypsa_v1_component`
- `exclusion_reason`
- `closure_semantics_hint`
- `operational_status`
- `closure_flag`
- `tap_ratio_hint`
- `v_nom_bus0_kv`
- `v_nom_bus1_kv`
- `voltage_pair_status`

## Limitaciones importantes

- `r_pu_hint`, `x_pu_hint` y `s_nom_mva_hint` siguen siendo insumos
  provisionales; todavía no equivalen a una validación final de unidades para
  `PyPSA`
- `tap_side_hint` todavía no se infiere
- la exclusión de enlaces `TAP` es una decisión v1 conservadora

## Auditoría de consistencia eléctrica v1

La exportación ahora usa `v_nom_kv` de `buses` para marcar consistencia de nivel
de tensión:

- para `line`
  - `same_voltage_ok`
  - `line_voltage_mismatch`
  - `missing_bus_v_nom`
- para `transformer`
  - `different_voltage_ok`
  - `same_voltage_transformer_suspect`
  - `missing_bus_v_nom`

Esto no reemplaza una validación eléctrica completa, pero permite detectar
rápido si una rama serie está siendo exportada a un componente PyPSA que no
cuadra con los niveles nominales ya inferidos.

## Script

```bash
python3 scripts/build_pypsa_branch_components.py
```

# Generators

Este bloque implementa la primera versión canónica de `generators`.

## Fuentes usadas

- `e_datgen`: inventario técnico base
- `MAPEO CENTRALES DE GENERACION`: nombre y trazabilidad de código
- `Factores de Nodo (Inyección)`: fuente principal para `generador -> barra`
- `Centrales (Zonas)`: fallback para terminal eléctrica
- `Reporte de Disponibilidad`: respaldo de nombres

## Decisión operativa actual

El inventario base se toma del bloque primario de `e_datgen`, deteniéndose antes
de las secciones auxiliares repetidas de la hoja.

La resolución de `bus_id` se hace por niveles:

1. `Factores de Nodo (Inyección)`
2. `Centrales (Zonas)` si la barra existe en `buses`
3. inferencia explícitamente marcada por similitud de sitio, solo si deja una
   única barra candidata

## Campos clave

- `generator_id`
- `generator_name`
- `generator_id_legacy`
- `bus_id`
- `bus_resolution_method`
- `enabled_flag`
- `pmax_mw`
- `pmin_mw`
- `technology_group`
- `cvp`
- `pgn_mw`

## Validaciones

La auditoría exporta:

- cuántos generadores quedaron con barra resuelta
- cuántos quedaron sin resolver
- una muestra de casos sin barra

## Script

```bash
python3 scripts/build_generators.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/generators/generators.csv`
- `data/processed/generators/generators_reconciliation_summary.json`

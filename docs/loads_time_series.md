# Loads Time Series

Este bloque implementa la primera versión reproducible de `loads_time_series`
desde `PDemanda`.

## Fuentes usadas

- `PDemanda`: perfil operativo de demanda
- `DEMANDA SMC`: puente explícito `ID DIGSILENT -> IDBARRA`
- `e_datdem`: inventario auxiliar para auditar ids de carga

## Decisión operativa actual

El proyecto exporta dos niveles:

- `pdemanda_raw_long.csv`: expansión fiel de `PDemanda` a formato largo
- `loads_time_series.csv`: versión agregada por barra resuelta y bloque
- `smc_load_registry.csv`: registro de reconciliación desde `DEMANDA SMC`

## Regla de reconciliación aplicada

Evidencia del caso `V449`:

- `PDemanda` usa códigos tipo `ZADOMF-D1`
- `DEMANDA SMC` contiene `ID DIGSILENT` y `IDBARRA`
- `e_datdem` usa ids alineados con barra, por ejemplo `WADOMF`

Regla operativa aplicada, en este orden:

1. resolver `load_id_raw -> bus_id` desde `DEMANDA SMC`
2. si hay ambigüedad, preferir barra activa o compatible con `e_datdem`
3. usar la heurística `Z...-Dk -> W...` solo como respaldo

Para `V449`, esta reconciliación deja:

- `315` ids raw en `PDemanda`
- `281` cargas canónicas por barra
- traslape exacto `281/281` contra `e_datdem`

## Limitación explícita

`loads_time_series` todavía queda en eje temporal de `24` bloques horarios:

- `time_block_group = load_blocks_pdemanda_24h`
- `snapshot_id` queda vacío por ahora

Eso evita inventar una traducción falsa entre:

- `24` bloques de demanda
- `48` períodos de despacho

## Script

```bash
python3 scripts/build_loads_time_series.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/loads_time_series/pdemanda_raw_long.csv`
- `data/processed/loads_time_series/loads_time_series.csv`
- `data/processed/loads_time_series/smc_load_registry.csv`
- `data/processed/loads_time_series/loads_time_series_reconciliation_summary.json`

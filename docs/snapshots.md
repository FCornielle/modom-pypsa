# Snapshots

Este bloque implementa la primera versión ejecutable de la tabla canónica
`snapshots`.

## Fuente usada

- `e_sets`: horizonte de despacho del caso
- `PDemanda`: eje horario de demanda para detectar brechas temporales

## Decisión operativa actual

- la fila `N` de `e_sets` define el horizonte principal del caso
- en el caso `V449`, `N = 1*48`
- eso se expande a `pd001 ... pd048`

## Limitación explícita

`PDemanda` trae `24` bloques (`1 ... 24`), mientras `e_sets` declara `48`
períodos.

Por ahora el proyecto:

- exporta `snapshots.csv` con los `48` períodos de despacho
- exporta `snapshot_horizon_summary.json` para dejar trazada la diferencia
- no fuerza todavía una traducción falsa entre `48` y `24`

Eso es deliberado: la equivalencia exacta todavía requiere una decisión de
modelado documentada.

## Script

```bash
python3 scripts/build_snapshots.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salidas

- `data/processed/snapshots/snapshots.csv`
- `data/processed/snapshots/snapshot_horizon_summary.json`

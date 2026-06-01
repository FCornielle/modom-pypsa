# Inventario del workbook

El primer artefacto ejecutable del proyecto debe ser un inventario reproducible
del `.xlsm`.

## Objetivo

Exportar, de forma trazable:

- hojas disponibles
- dimensiones recortadas por hoja
- foco inicial sobre `e_sets`, `e_datred`, `e_datgen`, `e_datdem` y `PDemanda`
- fila de encabezado detectada para cada hoja foco
- primeras columnas útiles
- pequeñas muestras estructuradas para inspección rápida

## Script

El punto de entrada del proyecto es:

```bash
python3 scripts/inventory_modom_workbook.py \
  --xlsm /tmp/MODOM_DIARIO_dd-mm-yyyy_V449.xlsm
```

## Salida esperada

Se exportan estos artefactos:

- `data/processed/workbook_inventory/workbook_inventory.json`
- `data/processed/workbook_inventory/sheet_inventory.csv`
- `data/processed/workbook_inventory/focus_sheets/*.json`
- `data/processed/workbook_inventory/focus_sheets/*_preview.csv`

## Criterio de reproducibilidad

- lectura directa del XML interno del `.xlsm`, sin Excel ni macros
- inventario general apoyado en el rango `dimension` declarado por cada hoja
- hojas foco materializadas para detectar encabezados y extraer columnas útiles

## Convención horaria

Este proyecto asume explícitamente:

- `h_1` = intervalo `00:00-00:59`
- `h_24` = intervalo `23:00-23:59`

Las etiquetas horarias representan bloques de energía, no instantes puntuales.

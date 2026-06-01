# Primer mapeo real MODOM -> capa canónica

Este documento fija el primer mapeo concreto para las tablas iniciales del
proyecto usando evidencia ya existente en el workspace:

- script previo: `scripts/extract_modom_daily_xlsm.py`
- script previo: `scripts/normalize_modom_to_pypsa.py`
- salidas previas: `outputs/modom_daily/normalized_v449/*.csv`

## Alcance

Aquí se documenta el primer bloque mínimo:

- `snapshots`
- `buses`
- `branches`
- `generators`
- `loads_time_series`

## Limitación importante

El workbook `.xlsm` fuente no está guardado ahora mismo dentro del proyecto
nuevo. Por eso este mapeo se apoya en:

1. el código del extractor previo
2. las salidas normalizadas ya exportadas

Eso es suficiente para arrancar el diseño del pipeline, pero no reemplaza una
verificación final contra el `.xlsm` crudo cuando lo incorporemos al flujo del
proyecto.

## Evidencia confirmada

Del caso `v449` ya existen estas salidas:

- `buses.csv`: 534 filas
- `branches.csv`: 846 filas
- `generators.csv`: 570 filas
- `load_profiles.csv`: 394 filas

Además:

- `load_profiles` usa 24 períodos horarios
- `renewable_profiles`, `branch_flows` y `bus_voltages` usan 48 períodos

Eso implica que el proyecto debe modelar explícitamente la noción de horizonte y
no asumir que todas las hojas tienen la misma granularidad temporal.

## Tabla `snapshots`

### Fuente principal

- hoja `e_sets`

### Estado actual

- ya está identificada como la fuente correcta en el extractor previo
- todavía no existe una exportación canónica concreta para esta tabla en las
  salidas previas

### Diseño recomendado

Campos mínimos:

- `snapshot_id`
- `snapshot_order`
- `snapshot_label_modom`
- `time_block_group`
- `source_sheet`

### Nota técnica

Antes de construir series temporales en `PyPSA`, hay que resolver si el caso
debe usar:

- 24 snapshots,
- 48 snapshots,
- o una capa de traducción entre hojas de 24 y 48 bloques.

Ese punto no debe dejarse implícito.

## Tabla `buses`

### Fuentes

- hoja `MAPEO TODAS LAS BARRAS`
- apoyo futuro desde `e_datred`

### Extracción previa confirmada

La normalización previa produce estas columnas:

- `bus_old`
- `bus_old_name`
- `bus_new`
- `bus_new_name`
- `code_changed`

Ejemplo real:

- `bus_old = WLMI5K`
- `bus_old_name = TER LOS MINA 5`
- `bus_new = WTMI5K`
- `bus_new_name = TERMINAL LOS MINA 5`
- `code_changed = SI`

### Decisión canónica

Esta tabla debe convertirse a un inventario estable de barras con al menos:

- `bus_id_modom`
- `bus_name`
- `bus_id_legacy`
- `bus_name_legacy`
- `code_changed`
- `source_sheet`

### Comentario

El mapeo de barras no aporta todavía impedancias ni conectividad. Eso vendrá de
`e_datred`. Aquí la función principal es identidad y trazabilidad.

## Tabla `branches`

### Fuente

- hoja `e_datred`

### Extracción previa confirmada

La normalización previa produce estas columnas:

- `bus0`
- `bus0_dummy`
- `bus1`
- `bus1_dummy`
- `circuit`
- `asset_type_hint`
- `r_pu`
- `x_pu`
- `fmax_mw`
- `status`
- `closure_flag`

Ejemplo real:

- `bus0 = WHAINF`
- `bus1 = WHAIBF`
- `circuit = L1`
- `asset_type_hint = line`
- `r_pu = 0.0`
- `x_pu = 0.0001`
- `fmax_mw = 79.0`
- `status = 1`

### Decisión canónica

La tabla canónica mínima debería contener:

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
- `source_sheet`

### Comentario

Los campos `bus0_dummy` y `bus1_dummy` parecen auxiliares del modelo fuente y no
deberían pasar a la capa canónica salvo que luego se pruebe que tienen valor
eléctrico real.

## Tabla `generators`

### Fuentes

- hoja `e_datgen`
- apoyo de `MAPEO CENTRALES DE GENERACION`

### Extracción previa confirmada

La normalización previa produce estas columnas:

- `generator_code`
- `enabled_flag`
- `pmax_mw`
- `pmin_mw`
- `cvp`
- `technology_group`
- `ssaa`
- `mrpf`
- `mrsf`
- `factora`
- `heat_parameter`
- `pgn_mw`

Ejemplo real:

- `generator_code = G3TAVER1`
- `enabled_flag = 1`
- `pmax_mw = 48.0`
- `pmin_mw = 33.0`
- `technology_group = 2`
- `pgn_mw = 48.0`

### Decisión canónica

La tabla canónica mínima debería contener:

- `generator_id`
- `generator_name`
- `bus_id`
- `enabled_flag`
- `pmax_mw`
- `pmin_mw`
- `technology_group`
- `marginal_cost_hint`
- `heat_rate_hint`
- `availability_group_hint`
- `source_sheet`

### Comentario

Todavía falta unir de forma explícita:

- código de generador
- nombre legible
- nodo de conexión

Ese cruce probablemente requerirá usar también el mapeo de generación y revisar
mejor el contenido bruto de `e_datgen`.

## Tabla `loads_time_series`

### Fuentes

- hoja `PDemanda`
- posible apoyo de `e_datdem`

### Extracción previa confirmada

La normalización previa exporta una tabla ancha:

- `load_code`
- `h_1` ... `h_24`

Ejemplo real:

- `load_code = ZHNVAF-D1`
- `h_1 = 1.257653286`
- `h_24 = 1.308128857`

### Decisión canónica

La capa canónica no debe mantener esta tabla en formato ancho. Debe pasar a
formato largo:

- `load_id`
- `snapshot_id`
- `p_set_mw`
- `source_sheet`

### Regla de transformación

Cada fila ancha de `PDemanda` debe convertirse en múltiples filas:

- una por `load_id`
- una por `snapshot_id`

### Comentario

`e_datdem` probablemente contiene metadatos o estructura de la demanda, mientras
que `PDemanda` contiene el perfil operativo. Conviene no mezclar ambas funciones
en una sola tabla.

## Implicaciones directas para la implementación

### Confirmado

- ya existe una base útil para `buses`, `branches`, `generators` y `loads`
- el trabajo previo no se pierde; se puede reciclar como referencia
- el proyecto nuevo debe formalizar esos CSV como parte de una capa canónica más
  rigurosa

### Falta por verificar

- contenido exacto de `e_sets`
- correspondencia 24 vs 48 períodos
- relación explícita generador -> barra
- relación explícita carga -> barra
- diferencias entre nombres legibles y códigos operativos

## Siguiente paso recomendado

Implementar dentro del proyecto nuevo un inventario reproducible del workbook
que exporte:

1. hojas disponibles
2. dimensiones por hoja
3. filas de encabezado detectadas
4. primeras columnas útiles de `e_sets`, `e_datred`, `e_datgen`, `e_datdem` y
   `PDemanda`

Con eso el siguiente salto ya sería código del proyecto y no solo documentación.

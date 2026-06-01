# Series temporales de generación

Este bloque agrega dos tablas canónicas temporales ligadas a `snapshots`:

- `generator_availability`
- `renewable_profiles`

## Fuentes

### `generator_availability`

- hoja `Reporte de Disponibilidad`
- catálogo `generators`
- horizonte `snapshots`

Cada fila del reporte trae una unidad y `48` columnas horarias. La exportación
las lleva a formato largo con `snapshot_id = pd001..pd048`.

Campos principales:

- `generator_id`
- `snapshot_id`
- `available_mw`
- `static_pmax_mw`
- `available_pu`

Regla actual:

- solo se exportan ids que ya existen en la tabla canónica `generators`
- ids extra del reporte quedan auditados en el resumen

### `renewable_profiles`

- hoja `Pronostico Renovable`
- auditoría secundaria contra `Total Renovable`
- catálogo `generators`
- horizonte `snapshots`

Cada fila del pronóstico renovable también viene con `48` columnas horarias y
se exporta a formato largo.

Campos principales:

- `generator_id`
- `snapshot_id`
- `forecast_mw`
- `static_pmax_mw`
- `forecast_pu`

Reglas actuales:

- `Pronostico Renovable` es la fuente primaria del perfil renovable variable
- `Total Renovable` se usa como auditoría de cobertura, no como fuente canónica
- ids renovables ausentes del pronóstico quedan fuera de esta tabla y se reportan
  en el resumen

## Artefactos

### Disponibilidad

- `data/processed/generator_availability/generator_availability.csv`
- `data/processed/generator_availability/generator_availability_summary.json`

### Renovables

- `data/processed/renewable_profiles/renewable_profiles.csv`
- `data/processed/renewable_profiles/renewable_profiles_summary.json`

## Limitaciones actuales

- la demanda sigue teniendo un eje de `24` bloques, mientras estas series usan
  `48` períodos y sí coinciden con `snapshots`
- `available_pu` y `forecast_pu` se calculan contra `pmax_mw` estático de
  `e_datgen`; eso sirve como primera normalización, pero aún no representa toda
  la lógica operativa de MODOM
- `Total Renovable` contiene al menos un caso adicional frente a
  `Pronostico Renovable`; por ahora eso queda como señal de auditoría

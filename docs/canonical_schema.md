# Esquema canónico mínimo

Este documento fija la primera versión de la capa intermedia entre `MODOM` y
`PyPSA`.

La idea central es simple:

- `MODOM` es la fuente operativa
- el proyecto la transforma a tablas canónicas estables
- `PyPSA` consume esas tablas, no las hojas crudas del workbook

## Tablas mínimas

| Tabla | Propósito | Fuente MODOM | Uso en PyPSA |
| --- | --- | --- | --- |
| `snapshots` | Definir el horizonte temporal del caso | `e_sets` | `network.snapshots` |
| `buses` | Inventario estable de barras | `e_datred`, `MAPEO TODAS LAS BARRAS` | `network.buses` |
| `branches` | Red serie base: líneas y transformadores | `e_datred` | `network.lines`, `network.transformers` |
| `generators` | Catálogo de unidades y atributos base | `e_datgen`, `MAPEO CENTRALES DE GENERACION` | `network.generators`, `network.storage_units` |
| `loads_time_series` | Demanda por barra y período | `e_datdem`, `PDemanda` | `network.loads_t.p_set` |
| `generator_availability` | Disponibilidad y derates por unidad | `Reporte de Disponibilidad` | `network.generators_t.p_max_pu` |
| `renewable_profiles` | Perfiles renovables pronosticados | `Pronostico Renovable` | `network.generators_t.p_max_pu` |
| `branch_outages` | Cambios temporales de estado/capacidad de red | `e_modred`, `Mantenimientos Red Transmision` | Aplicación previa a cada snapshot |
| `hydro_units` | Catálogo hidráulico base | `e_hidro`, `e_datgen` | `network.storage_units` o `network.generators` |
| `hydro_time_series` | Condiciones hidráulicas por período | `e_hidro` | Inflows o restricciones energéticas |
| `modom_results_reference` | Resultados de referencia para validación | `S_FLUJO`, `VOLTAJE`, `S_FNODO`, `CMG` | Backtesting y comparación |

## Estado actual

- `workbook_inventory` ya existe como artefacto reproducible del `.xlsm`
- `snapshots` ya tiene una primera implementación ejecutable basada en `e_sets`
- `loads_time_series` ya tiene una primera implementación ejecutable basada en
  `PDemanda` y reconciliada con `DEMANDA SMC` + `e_datdem`
- `buses` ya tiene una primera implementación ejecutable basada en `MAPEO TODAS
  LAS BARRAS` y auditada contra `e_datred`
- `branches` ya tiene una primera implementación ejecutable basada en
  `e_datred` y validada contra `buses`
- `generators` ya tiene una primera implementación ejecutable basada en
  `e_datgen` y reconciliada con `Factores de Nodo (Inyección)`
- `generator_availability` y `renewable_profiles` ya tienen una primera
  implementación ejecutable ligada a `snapshots`
- la traducción entre `48` períodos de despacho y `24` bloques de demanda sigue
  pendiente y está documentada explícitamente

## Criterios de diseño

### 1. Separar estado base y estado temporal

- `buses`, `branches`, `generators` y `hydro_units` contienen el inventario base
- `loads_time_series`, `generator_availability`, `renewable_profiles`,
  `branch_outages` y `hydro_time_series` contienen la variación por período

Esto evita mezclar estructura con operación.

### 2. Usar granularidad explícita

Cada tabla debe tener una granularidad clara:

- por barra
- por activo
- por barra-período
- por activo-período

Eso importa porque `PyPSA` separa componentes estáticos y series temporales.

### 3. Mantener trazabilidad hacia MODOM

Cada tabla debe preservar, al menos:

- identificador original MODOM
- hoja de origen
- clave de mapeo hacia nombres normalizados

Sin eso, validar contra `MODOM` después se vuelve frágil.

## Alcance de esta primera versión

Este esquema no intenta cubrir todavía:

- reservas
- restricciones especiales de despacho
- detalles completos de costos no lineales
- lógica completa de embalses acoplados
- semántica completa de todos los `.gms`

La primera meta es construir una réplica operativa mínima y validable.

## Orden recomendado de implementación

1. `snapshots`
2. `buses`
3. `branches`
4. `generators`
5. `loads_time_series`
6. `generator_availability`
7. `renewable_profiles`
8. `branch_outages`
9. `modom_results_reference`
10. bloques hidráulicos

Ese orden reduce riesgo porque primero arma una red y una demanda válidas, y
después añade complejidad operativa.

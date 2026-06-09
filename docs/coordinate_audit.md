# Coordinate Audit

Fecha de auditoría inicial: 2026-06-07

## Objetivo

Separar:

- casos con error de ubicación **claro y corregible con alta certeza**;
- casos **sospechosos** que todavía requieren validación adicional antes de fijarlos.

## Método usado

1. Lectura del pipeline actual:
   - `src/modom_pypsa/smc_coordinates.py`
   - `src/modom_pypsa/plano_coordinates.py`
   - `scripts/extract_plano_coords.py`
   - `docs/oc_smc_coordinates.md`
2. Detección automática de pares conectados por transformador con distancias
   anómalas.
3. Priorización de errores donde:
   - dos barras del mismo patio/subestación quedaron separadas por decenas de km;
   - una barra con nombre claro quedó peor ubicada que su par transformador;
   - el `match` por nombre resolvió al bus equivocado con evidencia interna.

## Casos corregidos con alta certeza

Los siguientes casos quedaron en `data/external/coordinate_overrides.csv` y se
aplicaron sobre `data/external/buses_with_coords.csv` con `coord_source =
manual_override`.

### 1. Tavera

- `WTTA1K` → copiado a la coordenada de `WTAVBE`
- `WTTA2K` → copiado a la coordenada de `WTAVBE`

Razón:

- `WTTA1K` estaba en `18.794461, -70.35457` por `smc_match` contra el punto OC
  `ANIANA VARGAS 1`, lo que contradice el nombre del bus (`TERMINAL TAVERA 1`)
  y lo dejaba a ~70.8 km de `WTAVBE`.
- `WTTA2K` estaba en `19.32542, -69.97348` por `plano_idw`, a ~81.6 km de
  `WTAVBE`.
- Ambos deben compartir el patio/subestación de Tavera.

### 2. Las Damas

- `WLDAMK` → copiado a la coordenada de `WLDAMF`

Razón:

- mismo nombre de subestación en el par del transformador;
- la ubicación `plano_idw` lo dejaba a ~55.2 km de su barra asociada.

### 3. Barahona Carbón

- `WBCARK` → copiado a la coordenada de `WBARCE`

Razón:

- `TER BARAHONA CARBON` no puede quedar ~41.4 km de `BARAHONA CARBÓN 138`;
- el punto previo provenía de `plano_idw`.

### 4. Dajabón

- `WDAJAE` → copiado a la coordenada de `WTDAJK`

Razón:

- `WDAJAE` estaba por `inferred_topology` a ~20.6 km de `WTDAJK`;
- el punto `DAJABON` del OC quedó asociado a `WTDAJK`, que representa el mismo
  patio/subestación en términos geográficos.

### 5. El Naranjo

- `WNARAD` → copiado a la coordenada de `WNARAE`

Razón:

- `WNARAD` y `WNARAE` forman el par del transformador `WNARAD__WNARAE`;
- la diferencia previa era ~188.9 km, físicamente imposible para un mismo patio;
- fuentes públicas de ETED/MEM describen `El Naranjo` como subestación
  `345/138 kV`.

### 6. Julio Sauri

- `WJSAUD` → copiado a la coordenada de `WJSAUE`

Razón:

- `WJSAUD` y `WJSAUE` forman un par de transformador `345/138`;
- la diferencia previa era ~24.9 km;
- fuentes públicas describen a `Julio Sauri` como subestación de transmisión
  vinculada a 345 kV y 138 kV.

### 7. Guerra

- `WGUERE` → copiado a la coordenada de `WGUERF`
- `WGUERD` → copiado a la coordenada de `WGUERF`

Razón:

- el OC ubica `GUERRA` con match exacto en `WGUERF` (69 kV);
- `WGUERE` (138 kV) y `WGUERD` (345 kV) representan el mismo patio de
  subestación a distintos niveles de tensión;
- el 345/138 previo quedaba desplazado por propagación.

### 8. Bonao II / Bonao III

- `WBON2E` → movido al punto OC exacto `BONAO`
- `WBON2F` → movido al punto OC exacto `BONAO`
- `WBONAF` → movido al punto OC exacto `BONAO`
- `WBON3C` → movido al centroide del patio `Bonao III`
- `WBON3D` → movido al centroide del patio `Bonao III`
- `WBON3E` → movido al centroide del patio `Bonao III`

Razón:

- el punto PVDC `BONAO 3 138 kV` había quedado asignado a `WBON2E`, lo que
  colapsaba `Bonao II` y `Bonao III` en el mismo nodo geográfico;
- el punto `BONAO 3 345` contaminó por fuzzy match a `WBONAF`;
- `WBON3D` venía arrastrado hacia Quisqueya por un match incorrecto con
  unidades generadoras, y `WBON3C` heredó esa desviación por propagación;
- la evidencia combinada del OC y de la imagen satelital muestra dos patios
  adyacentes: `Bonao II` al suroeste y `Bonao III` (PVDC/ETED) al noreste;
- para `Bonao III` se tomó el centroide entre los puntos OC `BONAO 3 345`
  (`18.9096946, -70.3657865`) y `BONAO 3 138 kV`
  (`18.9103651, -70.3663102`), quedando la propuesta en
  `18.910030, -70.366048`.

## Casos sospechosos pendientes

Estos casos siguen necesitando revisión antes de fijarlos:

- `WCC21E` / `WCCA2F`
  - diferencia actual ~29.7 km
  - ambos vienen de `inferred_topology`

## Estado del entorno

- La capa de overrides ya está integrada en el pipeline.
- La regeneración completa del paso `plano_idw` no pudo correr en este entorno
  porque falta la dependencia `pdfplumber`.

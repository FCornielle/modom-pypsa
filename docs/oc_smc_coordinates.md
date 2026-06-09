# Coordenadas de puntos SMC del OC (mapa geográfico)

Flujo para obtener las **coordenadas (lat/lon) de los puntos de medición SMC** del
SENI desde el mapa público del Organismo Coordinador (OC) y prepararlas para el
mapa del dashboard. Está pensado para **re-ejecutarse** cuando el OC actualice o
añada puntos.

## Por qué existe este flujo

`MODOM` **no trae coordenadas geográficas** (es una exportación de
PowerFactory/DIgSILENT, no un GIS). Las únicas pistas internas son zona/área en
las hojas `Barras (Zonas)` y `Centrales (Zonas)`.

El OC sí publica un mapa con ~535 puntos SMC geolocalizados en:

> https://www.oc.do/Informes/Administración-del-MEM/Sistema-de-Medición-Comercial
> (pestaña **Ubicación**)

Ese mapa es un Power BI **"publish-to-web"**. Su API anónima de datos
(`querydata`) responde **403** a peticiones crudas (`urllib`/`requests`): Microsoft
exige el *handshake* de sesión que hace el JavaScript del navegador. Por eso el
flujo usa **Playwright** (Chromium real).

## Requisitos (una sola vez)

```powershell
.\.venv\Scripts\python -m pip install playwright
.\.venv\Scripts\python -m playwright install chromium
```

## Ejecutar

```powershell
.\.venv\Scripts\python scripts\scrape_oc_smc.py            # auto-descubre el reporte
.\.venv\Scripts\python scripts\scrape_oc_smc.py --headed    # ver el navegador (debug)
.\.venv\Scripts\python scripts\scrape_oc_smc.py --discover   # forzar re-descubrimiento
.\.venv\Scripts\python scripts\scrape_oc_smc.py --token <r=...>  # forzar un reporte
```

## Qué hace el script (`scripts/scrape_oc_smc.py`)

1. **Descubre el reporte** (auto-reparable): intenta primero el token conocido del
   reporte del mapa; si no produce coordenadas, **carga la página del OC y lee el
   `app.powerbi.com/view?r=<token>` de los iframes**. Así el flujo no se rompe si
   el OC cambia el token.
2. Abre el reporte y **navega sus páginas** (`div[aria-label^='Page navigation']`),
   priorizando la del mapa (MAPAS / Ubicación) y alternando bookmarks
   (RETIROS / INYECCIONES).
3. **Intercepta** las respuestas de red `querydata` (las filas del visual).
4. **Decodifica** el formato comprimido de Power BI: `ValueDicts` (texto por índice),
   máscara `R` (repetir valor de la fila anterior) y `Ø` (nulo).
5. **Detecta la tabla con coordenadas** por rango geográfico de RD
   (lat 17–20.5, lon −72.5 a −68) y **normaliza** las columnas.

## Salidas

- `data/external/oc_smc_points.csv` — normalizado, listo para el join:
  `lat, lon, punto, tipo, tension, agente`
  (TIPO ∈ {RETIRO, CENTRAL, UNR, GENERACION}).
- `data/external/oc_smc_points_raw.csv` — columnas crudas del Power BI
  (`Avg(SOCKETS.GPS_LAT_S)`, `SOCKETS.GPS_LONG_S`, `Min(Puntos_Suministro.PUNTO)`…),
  por trazabilidad.
- `data/external/raw_pbi/querydata_*.json` — respuestas crudas, para auditar o
  reajustar el parser.

Resultado de referencia: **535 puntos**, todos con lat/lon válidos de RD.

## Join al modelo de red (`scripts/join_smc_coordinates.py`)

El mapa del OC trae `PUNTO` (nombre), `AGENTE` y `TENSION`, pero **no** el código de
barra. El join resuelve el `PUNTO` a una barra por **nombre**, usando tres fuentes ya
presentes en la capa canónica:

- nombres de barra (`buses.csv`),
- nombres de generador (`generators.csv`),
- nombres de carga del registro SMC (`smc_load_registry.csv`, que trae
  `resolved_bus_id`).

Empareja en dos niveles: `exact` (nombre normalizado idéntico) y `fuzzy` (similitud
de tokens Jaccard ≥ 0.5). Si varios puntos del OC caen en la misma barra (p.ej.
turbinas `T1/T2` de un parque), las coordenadas se **promedian**.

```powershell
.\.venv\Scripts\python scripts\join_smc_coordinates.py
```

Salidas (en `data/external/`):

- `buses_with_coords.csv` — **todas** las barras con `lat,lon` donde hubo match,
  más `match_method`, `match_score`, `oc_point_count`, `oc_puntos`.
- `smc_point_matches.csv` — cada punto del OC con la barra emparejada y su score
  (para auditar los `fuzzy`).
- `smc_coordinates_summary.json` — cobertura.

Cobertura de referencia: **305 / 717 barras geolocalizadas** (las que tienen
inyección/retiro SMC), 431 / 535 puntos cruzados (194 `exact` + 237 `fuzzy`).

## Segunda fuente de coordenadas: el plano geográfico del OC

Muchas barras sin punto SMC quedaban con coordenada **inferida por topología**
(centroide de vecinos), que a veces cae "en el mar". `scripts/extract_plano_coords.py`
(módulo `modom_pypsa/plano_coordinates.py`) las rescata desde el **plano geográfico
mensual** del OC (`data/Plano RD Lineas Transmision *.pdf`, vectorial).

El plano es **semi-esquemático**, no una proyección cartográfica: un ajuste afín
global solo logra ~22 % de inliers (RMS 7.6 km) y las anclas de ciudad ~15 km. Por
eso se usa **interpolación local IDW (k=4)** anclada en las 305 barras `smc_match`
(emparejadas con etiquetas del plano por solape de tokens del nombre), con:

- **pool de anclas auto-depurado**: descarta anclas inconsistentes (etiquetas mal
  fusionadas o plantas nombradas como un pueblo pero ubicadas en otro sitio) por
  error leave-one-out > 18 km;
- **tope de cordura**: descarta predicciones que difieran del afín global > 40 km;
- **recorte** a la caja terrestre de RD.

Resultado: rescata **~40 barras** (`coord_source="plano_idw"`), precisión LOO
mediana ≈ 5.8 km / p90 ≈ 18 km. **Nunca** pisa las coordenadas reales `smc_match`.
Audita el emparejamiento en `data/external/plano_substation_matches.csv`.
Distribución final de `coord_source`: 305 `smc_match`, 333 `inferred_topology`,
40 `plano_idw`, 39 sin coordenada (no aparecen en el plano).

## Correcciones manuales auditadas

Para casos donde la heurística automática produce una ubicación claramente
incorrecta pero la identidad de la subestación sí está clara, el flujo puede
aplicar `data/external/coordinate_overrides.csv` al final del proceso.

Uso previsto:

- pares por transformador que deberían compartir patio/subestación y quedaron a
  decenas de km de distancia;
- terminales/generadores donde el match por nombre del punto SMC resolvió contra
  la planta correcta pero al bus equivocado;
- ajustes confirmados manualmente contra mapa/GIS antes de abrir un PR.

> Confianza: usa `match_method`/`match_score` para filtrar. Los `fuzzy` con score
> ≥ 0.9 son fiables; los de 0.5–0.7 conviene auditarlos (puede haber falsos
> positivos por nombres parecidos). El token central del ID SMC del informe del OC
> (`3303-`**`ABCOF`**`-T01` → bus `WABCOF`) sirve para validar/ampliar el cruce.

## Solución de problemas

- **No captura `querydata`**: corre con `--headed` y sube `--soak` (p.ej. `--soak 20000`).
- **Captura pero no halla lat/lon**: el mapa puede haberse movido de página; revisa
  `data/external/raw_pbi/*.json` (busca entidades `SOCKETS` / `Puntos_Suministro`).
- **Cambió el token del OC**: usa `--discover` (o deja el modo por defecto, que ya
  re-descubre al fallar).
- **Descarga de Chromium falla** (red inestable): reintenta
  `python -m playwright install chromium`.

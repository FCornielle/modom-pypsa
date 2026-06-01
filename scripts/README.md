# Scripts

Este directorio debe contener puntos de entrada pequenos y trazables.

Ejemplos futuros:

- `extract_modom_case.py`
- `build_canonical_tables.py`
- `validate_case.py`
- `build_pypsa_network.py`

Script ya implementado:

- `inventory_modom_workbook.py`
- `build_snapshots.py`
- `build_loads_time_series.py`
- `build_buses.py`
- `build_branches.py`
- `build_generators.py`
- `build_generator_time_series.py`
- `build_pypsa_branch_components.py`
- `build_pypsa_network.py` — arma y resuelve la red `pypsa.Network()` (LOPF lineal)
- `scrape_oc_smc.py` — extrae coordenadas de los puntos SMC del mapa Power BI del OC
  (Playwright). Flujo re-ejecutable; ver [`docs/oc_smc_coordinates.md`](../docs/oc_smc_coordinates.md)
- `join_smc_coordinates.py` — cruza esos puntos con las barras y genera
  `data/external/buses_with_coords.csv` (lat/lon por barra)

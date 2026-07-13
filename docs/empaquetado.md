# Empaquetado de la plataforma (instalable)

Objetivo: un instalable que se abre con doble-click, levanta el servidor local y abre el
navegador en el Optimizador — "abrir y hacer corridas", sin consola ni instalación de Python.

Punto de entrada: [`launch.py`](../launch.py) (arranca uvicorn + abre el navegador). Hoy se
usa con `run_webapp.bat`; el ejecutable lo envuelve.

## Enfoque recomendado (robusto para este stack)
El stack (PyPSA + HiGHS + pandapower + numpy/scipy) es **pesado y sensible** al empaquetado.
El camino más fiable es **PyInstaller en modo carpeta (`--onedir`)** envolviendo `launch.py`,
NO `--onefile` (que descomprime en temp y rompe con los solvers).

```bash
.venv/Scripts/python.exe -m pip install pyinstaller
.venv/Scripts/pyinstaller --onedir --name PlataformaMODOM ^
  --collect-all pypsa --collect-all linopy --collect-all highspy ^
  --collect-all pandapower --collect-all plotly ^
  --add-data "src/modom_pypsa/webapp/templates;modom_pypsa/webapp/templates" ^
  --add-data "src/modom_pypsa/webapp/static;modom_pypsa/webapp/static" ^
  --add-data "data/processed;data/processed" ^
  --add-data "data/raw;data/raw" ^
  --add-data "data/external;data/external" ^
  launch.py
```

- Los `--collect-all` incluyen binarios/datos de los paquetes científicos (HiGHS trae su
  solver, pandapower sus tablas). Verificar tras el build que `runpp` y `n.optimize` corren.
- Los datos (`data/`) y `results/` deben quedar **junto al ejecutable** (escribibles): las
  corridas se guardan en `results/`, así que esa carpeta no puede ir dentro del bundle de solo
  lectura. Configurar rutas relativas al ejecutable si se detecta `sys.frozen`.
- Tamaño esperado: ~700 MB – 1.2 GB (numpy/scipy/pandas/pypsa/pandapower). Es normal.

## Alternativa más simple (menos frágil)
Un instalador (Inno Setup / NSIS) que empaquete **el proyecto + un Python embebido/venv** y
un acceso directo que ejecute `python launch.py`. Evita los problemas de PyInstaller con los
solvers, a cambio de shippear el intérprete. Recomendado si el `--onedir` da guerra con HiGHS.

## Versionado
La "versión" de la plataforma = fecha/serial del MODOM cargado (se muestra en la cabecera del
Optimizador: `MODOM V449 · datos cargados … · último PDD …`). Al cargar un MODOM nuevo, la
plataforma toma sus valores como defaults y la versión se actualiza sola.

## Checklist antes de empaquetar
- [ ] `pytest -q` verde.
- [ ] `launch.py` abre el Optimizador y una corrida termina OK.
- [ ] La verificación AC corre (requiere el export DIgSILENT en `data/external/`).
- [ ] `results/` es escribible junto al ejecutable (historial de corridas).

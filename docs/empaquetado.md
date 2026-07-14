# Empaquetado — app de escritorio (.exe)

La plataforma se distribuye como una **app de escritorio de Windows**: doble-click en
`PlataformaMODOM.exe`, arranca el servidor local y abre una **ventana de aplicación** de
Microsoft Edge en modo `--app` (sin barra de navegador, con su icono en la barra de tareas).
Cerrar la ventana detiene el servidor. **No requiere Python instalado.**

## Cómo se construye (probado)
```bash
.venv/Scripts/python.exe build_app.py
```
Eso ejecuta PyInstaller (`PlataformaMODOM.spec`, modo carpeta/onedir) y luego copia los datos
junto al ejecutable. Produce:
```
dist/PlataformaMODOM/
├─ PlataformaMODOM.exe        ← doble-click
├─ _internal/                 ← Python + libs (numpy, scipy, pypsa, HiGHS, pandapower…)
├─ data/                      ← processed / raw (workbook) / external (export DIgSILENT)
└─ results/                   ← corridas (escribible; el historial se guarda aquí)
```
Para distribuir: comprimir la carpeta `dist/PlataformaMODOM/` (o hacer un instalador, ver
abajo). Corre en cualquier **Windows 10/11 x64**; para Mac/Linux se rehace el build en cada SO.

## Decisiones de diseño (por qué así)
- **Ventana con Edge `--app`, no pywebview.** pywebview en un bundle PyInstaller falla al
  cargar `Python.Runtime.dll` (pythonnet/.NET) — es frágil. Edge/Chrome en modo app dan una
  ventana chromeless robusta y sin dependencias .NET (`desktop.py`).
- **Rutas `frozen-aware` (`paths.py`).** En el .exe, `APP_ROOT` = carpeta del ejecutable, así
  `data/` y `results/` viven junto al .exe (escribibles, actualizables) y no dentro del bundle.
- **onedir, no onefile.** `--onefile` descomprime en temp y rompe con los solvers; onedir es
  fiable.
- **matplotlib incluido**: PyPSA lo importa; sin él el solve falla (`No module named matplotlib`).

## Verificado
- El .exe arranca (servidor 200), corre el **MILP (HiGHS)** y la **verificación AC
  (pandapower)** de punta a punta, guarda escenarios y archiva corridas por fecha.
- Tamaño ~1 GB (stack científico); se puede bajar con UPX/`--strip` y más `excludes`.

## Instalador (opcional, para distribución pulida)
Envolver `dist/PlataformaMODOM/` con **Inno Setup**: instala en `Archivos de programa`, crea
acceso directo en el menú Inicio y escritorio, e icono. Alternativa más liviana: instalador
con Python embebido que ejecute `launch.py` (más fácil de actualizar datos del MODOM).

## Versionado
La versión de la plataforma = fecha/serial del MODOM cargado (cabecera del Optimizador:
`MODOM V449 · datos cargados … · último PDD …`). Para actualizar datos, reemplazar los
archivos en `data/` junto al .exe; la app toma esos valores como defaults.

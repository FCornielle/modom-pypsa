# PyInstaller spec — Plataforma MODOM (app de escritorio, modo carpeta/onedir).
# Build:  .venv\Scripts\pyinstaller PlataformaMODOM.spec --noconfirm
# Los datos escribibles (data/, results/) se copian JUNTO al .exe tras el build (build_exe.py),
# no dentro del bundle: la app los resuelve por paths.APP_ROOT = carpeta del .exe.

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# stack científico + web: binarios (solver HiGHS, scipy) y datos de paquete
for pkg in ("pypsa", "linopy", "highspy", "pandapower", "plotly", "xarray",
            "uvicorn", "starlette", "fastapi", "jinja2", "pandas", "scipy",
            "numpy", "openpyxl", "networkx", "anyio", "click",
            "h11", "multipart", "matplotlib"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# plantillas y estáticos del webapp (van DENTRO del bundle, son de solo lectura)
datas += [
    ("src/modom_pypsa/webapp/templates", "modom_pypsa/webapp/templates"),
    ("src/modom_pypsa/webapp/static", "modom_pypsa/webapp/static"),
]
hiddenimports += collect_submodules("modom_pypsa")
hiddenimports += ["modom_pypsa.webapp.app", "uvicorn.logging",
                  "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                  "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]

a = Analysis(
    ["desktop.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "pytest", "IPython", "notebook",
              "webview", "clr", "pythonnet", "clr_loader"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PlataformaMODOM",
    console=False,  # app de escritorio: sin consola (los errores de solve salen en la UI)
    icon="src/modom_pypsa/webapp/static/app.ico" if __import__("os").path.exists(
        "src/modom_pypsa/webapp/static/app.ico") else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PlataformaMODOM")

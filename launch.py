"""Lanzador de la plataforma MODOM (abrir y correr).

Arranca el servidor local (FastAPI + uvicorn) y abre el navegador en el Optimizador.
Es el punto de entrada del futuro ejecutable instalable: doble-click → plataforma abierta.

Uso:
    .venv/Scripts/python.exe launch.py            # abre en http://127.0.0.1:8000
    .venv/Scripts/python.exe launch.py --port 8123 --no-browser
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent
SRC = REPO / "src"


def _open_browser(url: str, delay: float = 1.5) -> None:
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    args = ap.parse_args()

    # permite ejecutar tanto desde el repo (src/ en el path) como empaquetado
    if SRC.exists() and str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    import uvicorn

    url = f"http://{args.host}:{args.port}/"
    print(f"  Plataforma MODOM  →  {url}")
    print("  (cierra esta ventana para detener el servidor)")
    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    uvicorn.run("modom_pypsa.webapp.app:app", host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()

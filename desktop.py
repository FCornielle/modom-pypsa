"""Aplicación de escritorio — Plataforma MODOM.

Arranca el servidor local (FastAPI/uvicorn) en un hilo y abre la plataforma en una
**ventana de aplicación** de Microsoft Edge / Chrome (modo `--app`): sin barra de
navegador, con su propio icono en la barra de tareas — se ve y se usa como una app
nativa, sin dependencias frágiles (.NET/pythonnet). Cerrar la ventana detiene el servidor.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
TITLE = "Plataforma MODOM"


def _wait_server(host: str, port: int, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _find_browser() -> str | None:
    """Ruta a Edge o Chrome para abrir en modo aplicación (ventana sin barra)."""
    import shutil

    for name in ("msedge", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return next((c for c in candidates if os.path.exists(c)), None)


def _ensure_std_streams() -> None:
    """En una app sin consola (console=False), sys.stdout/stderr son None y varias libs
    fallan (uvicorn: `sys.stdout.isatty()`). Se redirigen a un sumidero seguro."""
    devnull = open(os.devnull, "w")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = devnull
    if sys.stderr is None:
        sys.stderr = devnull


def main() -> None:
    _ensure_std_streams()
    if not getattr(sys, "frozen", False):
        src = Path(__file__).resolve().parent / "src"
        if src.exists() and str(src) not in sys.path:
            sys.path.insert(0, str(src))

    import uvicorn

    config = uvicorn.Config("modom_pypsa.webapp.app:app", host=HOST, port=PORT,
                            log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    _wait_server(HOST, PORT)

    url = f"http://{HOST}:{PORT}/"
    browser = _find_browser()
    if browser:
        profile = Path(tempfile.gettempdir()) / "PlataformaMODOM_profile"
        proc = subprocess.Popen([
            browser, f"--app={url}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check",
            f"--window-size=1440,920",
        ])
        proc.wait()  # bloquea hasta que el usuario cierra la ventana de la app
    else:
        import webbrowser
        webbrowser.open(url)
        try:
            while True:  # sin Edge/Chrome: navegador normal + mantener vivo el server
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    server.should_exit = True


if __name__ == "__main__":
    main()

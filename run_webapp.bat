@echo off
REM ============================================================
REM  GridLab SENI - lanzador de la plataforma web (puerto 8000)
REM  Doble clic en este archivo o ejecutarlo desde la consola.
REM ============================================================
cd /d "%~dp0"

echo Liberando el puerto 8000 si quedo un servidor anterior...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo.
echo Levantando la plataforma en http://localhost:8000
echo (cierra esta ventana o pulsa Ctrl+C para detenerla)
echo.

set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m uvicorn modom_pypsa.webapp.app:app --app-dir src --port 8000

echo.
echo El servidor se detuvo. Pulsa una tecla para cerrar.
pause >nul

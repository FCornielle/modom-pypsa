@echo off
REM ============================================================
REM  Plataforma MODOM - abrir y correr (puerto 8000)
REM  Doble clic en este archivo: levanta el servidor y abre el navegador.
REM ============================================================
cd /d "%~dp0"

echo Liberando el puerto 8000 si quedo un servidor anterior...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

echo.
echo Abriendo la plataforma MODOM en http://localhost:8000
echo (cierra esta ventana o pulsa Ctrl+C para detenerla)
echo.

set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" launch.py --port 8000

echo.
echo El servidor se detuvo. Pulsa una tecla para cerrar.
pause >nul

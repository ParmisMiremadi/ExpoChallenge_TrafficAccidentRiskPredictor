@echo off
REM TraffiQ - double-click to launch, then open http://127.0.0.1:5000
cd /d "%~dp0"

REM Prefer the bundled project virtual-env; fall back to system Python.
set "VENV=..\webapp\backend\data\venv\Scripts\python.exe"
if exist "%VENV%" (
    "%VENV%" run.py
) else (
    python run.py
)

echo.
echo Server stopped. Press any key to close this window.
pause >nul

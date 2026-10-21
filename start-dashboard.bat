@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%niche_finder\Scripts\python.exe"
set "VITE_CMD=%PROJECT_ROOT%nichescope-phase9\node_modules\.bin\vite.cmd"

if not exist "%PYTHON_EXE%" (
    echo Could not find the project's Python environment:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%VITE_CMD%" (
    echo Could not find Vite. Check that nichescope-phase9 dependencies are installed:
    echo %VITE_CMD%
    pause
    exit /b 1
)

powershell.exe -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    start "NicheScope API" /D "%PROJECT_ROOT%" powershell.exe -NoExit -Command "& '%PYTHON_EXE%' -m uvicorn src.storage.backend.main:app --host 127.0.0.1 --port 8000"
    timeout /t 3 /nobreak >nul
)

powershell.exe -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000/' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    start "NicheScope Dashboard" /D "%PROJECT_ROOT%nichescope-phase9" powershell.exe -NoExit -Command "& '.\node_modules\.bin\vite.cmd' --host 127.0.0.1 --open"
) else (
    start "" "http://127.0.0.1:3000/"
)

endlocal

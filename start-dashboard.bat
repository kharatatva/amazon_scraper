@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "FRONTEND_DIR=%PROJECT_ROOT%nichescope-phase9"
set "VITE_CMD=%FRONTEND_DIR%\node_modules\.bin\vite.cmd"
cd /d "%PROJECT_ROOT%"

if not exist "%PYTHON_EXE%" (
    where py >nul 2>&1
    if not errorlevel 1 (
        echo Creating the project Python 3.13 environment...
        py -3.13 -m venv "%PROJECT_ROOT%.venv"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 goto missing_python
        python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) else 1)"
        if errorlevel 1 goto wrong_python
        echo Creating the project Python environment...
        python -m venv "%PROJECT_ROOT%.venv"
    )
    if errorlevel 1 goto setup_failed
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) else 1)"
if errorlevel 1 goto wrong_python

"%PYTHON_EXE%" -c "import bs4, playwright, playwright_stealth, fastapi, requests, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Installing required Python packages...
    "%PYTHON_EXE%" -m pip install -r "%PROJECT_ROOT%requirements.txt"
    if errorlevel 1 goto setup_failed
)

where node >nul 2>&1
if errorlevel 1 goto missing_node
node -e "const [major,minor]=process.versions.node.split('.').map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)"
if errorlevel 1 goto wrong_node

if not exist "%VITE_CMD%" goto install_frontend
call "%VITE_CMD%" --version >nul 2>&1
if errorlevel 1 goto install_frontend
goto frontend_ready

:install_frontend
where corepack >nul 2>&1
if not errorlevel 1 (
    echo Installing dashboard packages with the project-pinned Corepack pnpm...
    pushd "%FRONTEND_DIR%"
    call corepack pnpm install --frozen-lockfile
    if errorlevel 1 (
        where pnpm >nul 2>&1
        if errorlevel 1 goto setup_failed
        echo Corepack could not install packages. Retrying with the available pnpm command...
        call pnpm install --frozen-lockfile
        if errorlevel 1 goto setup_failed
    )
    popd
) else (
    where pnpm >nul 2>&1
    if errorlevel 1 goto missing_pnpm
    echo Installing dashboard packages with pnpm...
    pushd "%FRONTEND_DIR%"
    call pnpm install --frozen-lockfile
    if errorlevel 1 goto setup_failed
    popd
)

:frontend_ready

powershell.exe -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/environment' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    start "NicheScope API" /D "%PROJECT_ROOT%" "%PYTHON_EXE%" -m uvicorn src.storage.backend.main:app --host 127.0.0.1 --port 8000
    powershell.exe -NoProfile -Command "$until=(Get-Date).AddSeconds(30); do { try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/environment' -TimeoutSec 2 | Out-Null; exit 0 } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $until); exit 1"
    if errorlevel 1 goto api_start_failed
)

powershell.exe -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000/' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    start "NicheScope Dashboard" /D "%FRONTEND_DIR%" cmd.exe /k node node_modules\vite\bin\vite.js --host 127.0.0.1
    powershell.exe -NoProfile -Command "$until=(Get-Date).AddSeconds(20); do { try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000/' -TimeoutSec 2 | Out-Null; exit 0 } catch {}; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $until); exit 1"
    if errorlevel 1 goto dashboard_start_failed
)

start "" "http://127.0.0.1:3000/"
exit /b 0

:api_start_failed
echo The API did not start. Review the NicheScope API window for the error.
goto failed

:dashboard_start_failed
echo The dashboard did not start. Review the NicheScope Dashboard window for the error.
goto failed

:missing_python
echo Python 3.13 is required. Install Python 3.13 and try again.
goto failed

:wrong_python
echo The project requires Python 3.13. Select a supported Python installation and try again.
goto failed

:missing_node
echo Node.js 20.19+ or 22.12+ is required for the dashboard. Install Node.js and try again.
goto failed

:wrong_node
echo The dashboard requires Node.js 20.19+ or 22.12+. Upgrade Node.js and try again.
goto failed

:missing_pnpm
echo pnpm or Node.js Corepack is required to install dashboard packages.
goto failed

:setup_failed
echo Automatic setup did not complete. Check the message above and run this launcher again.

:failed
pause
exit /b 1

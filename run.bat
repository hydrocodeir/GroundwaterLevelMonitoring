@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD (
  where python3 >nul 2>nul
  if not errorlevel 1 (
    python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python3"
  )
)

if not defined PYTHON_CMD (
  echo Python 3.11 or newer was not found.
  echo Install Python from https://www.python.org/downloads/windows/ and enable "Add python.exe to PATH".
  echo Then close this window and run run.bat again.
  pause
  exit /b 1
)

if not exist ".venv-win\Scripts\python.exe" (
  echo Creating Windows virtual environment with %PYTHON_CMD%...
  %PYTHON_CMD% -m venv .venv-win
  if errorlevel 1 (
    echo Failed to create .venv-win.
    pause
    exit /b 1
  )
  call ".venv-win\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
  )
  call ".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
  )
)

if not exist ".venv-win\Scripts\python.exe" (
  echo The virtual environment was not created correctly.
  pause
  exit /b 1
)

set "APP_PORT=8228"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="APP_PORT" set "APP_PORT=%%B"
  )
)

echo Starting dashboard at http://127.0.0.1:%APP_PORT%
call ".venv-win\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %APP_PORT%
pause

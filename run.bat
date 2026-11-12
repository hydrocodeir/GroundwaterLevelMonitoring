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

call ".venv-win\Scripts\python.exe" scripts\launch_dashboard.py %*
set "DASHBOARD_EXIT_CODE=%errorlevel%"
if not "%DASHBOARD_EXIT_CODE%"=="0" pause
exit /b %DASHBOARD_EXIT_CODE%

@echo off
cd /d "%~dp0"

if not exist ".venv-win\Scripts\python.exe" (
  py -3 -m venv .venv-win
  call ".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
)

call ".venv-win\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8228
pause

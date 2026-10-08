@echo off
rem MiliastraGME console - normal (non-elevated) launch: view status, edit params.
rem inject / restore / rollback raise a UAC prompt from inside the UI.
rem ASCII-only on purpose so it works regardless of the console code page.
setlocal
cd /d "%~dp0"

set "PY="
where pythonw >nul 2>nul && set "PY=pythonw"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [!] Python not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

start "" %PY% "%~dp0gui\app.py"
exit /b 0

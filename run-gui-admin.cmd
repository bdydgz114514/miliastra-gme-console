@echo off
rem MiliastraGME Console - launch the GUI with administrator rights (one UAC prompt).
rem After this, inject / restore / rollback inside the UI will not ask again.
rem ASCII-only on purpose so it works regardless of the console code page.
setlocal
cd /d "%~dp0"

rem --- locate pythonw.exe ---
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for %%v in (313 312 311 310) do (
  if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python%%v\pythonw.exe"
)
if not defined PYW if exist "C:\Python312\pythonw.exe" set "PYW=C:\Python312\pythonw.exe"

if not defined PYW (
  echo.
  echo [!] pythonw.exe not found. Install Python 3.10+ and add it to PATH.
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0gui\app.py" (
  echo.
  echo [!] gui\app.py not found next to this script.
  echo.
  pause
  exit /b 1
)

set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"

%PS% -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PYW%' -ArgumentList '\"%~dp0gui\app.py\"' -WorkingDirectory '%~dp0' -Verb RunAs"
if errorlevel 1 (
  echo.
  echo [!] Elevation failed or was cancelled. Try running this file as administrator.
  echo.
  pause
  exit /b 1
)
exit /b 0

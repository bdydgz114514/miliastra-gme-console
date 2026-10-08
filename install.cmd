@echo off
chcp 65001 >nul
rem ============================================================
rem  MiliastraGME 控制台 - 安装脚本
rem  用法：双击本文件，或在命令行执行 install.cmd
rem ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   MiliastraGME 控制台 - 安装
echo ============================================================
echo.

rem ---------- 1. 找 Python ----------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY for %%v in (313 312 311 310) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
)
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"

if not defined PY (
  echo [x] 没有找到 Python。
  echo.
  echo     请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
  echo     安装时务必勾选 "Add python.exe to PATH"。
  echo.
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('"%PY%" --version 2^>^&1') do set "PYVER=%%v"
echo [1/4] 找到 Python %PYVER%
echo        %PY%

rem ---------- 2. 检查版本 >= 3.10 ----------
"%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo [x] Python 版本过低，需要 3.10 或更高。当前：%PYVER%
  echo.
  pause
  exit /b 1
)
echo [2/4] Python 版本符合要求

rem ---------- 3. 安装 PySide6 ----------
echo [3/4] 检查 PySide6 ...
"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo        未安装，正在安装（可能需要几分钟）...
  "%PY%" -m pip install --upgrade pip >nul 2>nul
  "%PY%" -m pip install PySide6
  if errorlevel 1 (
    echo.
    echo [x] PySide6 安装失败。
    echo     可以试试国内镜像：
    echo       "%PY%" -m pip install PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
  )
  echo        PySide6 安装完成
) else (
  echo        PySide6 已安装
)

rem ---------- 4. 自检 ----------
echo [4/4] 运行自检 ...
echo.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PY%" "gui\app.py" --check
if errorlevel 1 (
  echo.
  echo [!] 自检未通过。请把上面的输出发给开发者。
  echo.
  pause
  exit /b 1
)

rem ---------- 可选：桌面快捷方式 ----------
echo.
set /p MAKELNK="要创建桌面快捷方式吗？(Y/N) "
if /i "%MAKELNK%"=="Y" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "make_shortcuts.ps1"
)

echo.
echo ============================================================
echo   安装完成
echo ============================================================
echo.
echo   下一步：
echo     1. 双击 run-gui-admin.cmd 打开控制台（会弹一次管理员授权）
echo     2. 点「探测游戏目录」
echo     3. 点「关闭全部音频处理」
echo     4. 进一次游戏语音场景，回到界面点「刷新状态」
echo.
echo   完整教程见 TUTORIAL.md
echo.
pause
endlocal

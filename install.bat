@echo off
setlocal EnableDelayedExpansion
title SysMon Installer
color 0B

echo.
echo  ===========================================
echo   SysMon Overlay  ^|  Installer
echo  ===========================================
echo.

:: ─── Locate Python ─────────────────────────────────────────────────────────
echo  [1/5] Locating Python...

set PYTHON=
set PYTHONW=

:: Try py launcher first (most reliable on Windows)
where py >nul 2>&1
if !errorlevel! == 0 (
    for /f "tokens=*" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON=%%i
)

:: Fall back to python / python3 on PATH
if not defined PYTHON (
    where python >nul 2>&1
    if !errorlevel! == 0 (
        for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON=%%i
    )
)
if not defined PYTHON (
    where python3 >nul 2>&1
    if !errorlevel! == 0 (
        for /f "tokens=*" %%i in ('python3 -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON=%%i
    )
)

if not defined PYTHON (
    echo.
    echo  [ERROR] Python was not found on this system.
    echo.
    echo  Please install Python 3.9 or newer from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, check:
    echo    [x] Add Python to PATH
    echo.
    pause
    exit /b 1
)

:: Derive pythonw.exe from python.exe path
for %%i in ("!PYTHON!") do set PYDIR=%%~dpi
set PYTHONW=!PYDIR!pythonw.exe
if not exist "!PYTHONW!" set PYTHONW=!PYTHON!

:: Check version >= 3.9
for /f "tokens=*" %%i in ('"!PYTHON!" -c "import sys; print(sys.version_info >= (3,9))"') do set PYOK=%%i
if "!PYOK!" == "False" (
    echo.
    echo  [ERROR] Python 3.9 or newer is required.
    for /f "tokens=*" %%i in ('"!PYTHON!" --version') do echo  Found: %%i
    echo.
    echo  Download Python 3.9+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('"!PYTHON!" --version') do set PYVER=%%i
echo  Found: !PYVER! at !PYTHON!

:: ─── Ensure pip is available ────────────────────────────────────────────────
echo.
echo  [2/5] Checking pip...

"!PYTHON!" -m pip --version >nul 2>&1
if !errorlevel! neq 0 (
    echo  pip not found. Bootstrapping via ensurepip...
    "!PYTHON!" -m ensurepip --upgrade
    if !errorlevel! neq 0 (
        echo  [ERROR] Could not install pip. Check your Python installation.
        pause
        exit /b 1
    )
)

"!PYTHON!" -m pip install --upgrade pip --quiet
echo  pip OK.

:: ─── Remove old pynvml if present ──────────────────────────────────────────
echo.
echo  [3/5] Removing deprecated pynvml (if installed)...

"!PYTHON!" -m pip show pynvml >nul 2>&1
if !errorlevel! == 0 (
    echo  Found deprecated pynvml - uninstalling...
    "!PYTHON!" -m pip uninstall pynvml -y --quiet
    echo  Removed pynvml.
) else (
    echo  pynvml not present, skipping.
)

:: ─── Install dependencies ───────────────────────────────────────────────────
echo.
echo  [4/5] Installing dependencies...
echo.

"!PYTHON!" -m pip install -r "%~dp0requirements.txt" --quiet --progress-bar on

if !errorlevel! neq 0 (
    echo.
    echo  [ERROR] Dependency installation failed.
    echo  Try running this script as Administrator, or check your internet connection.
    pause
    exit /b 1
)

echo.
echo  Dependencies installed:
"!PYTHON!" -m pip show psutil        | findstr "Name Version"
"!PYTHON!" -m pip show nvidia-ml-py  | findstr "Name Version"

:: ─── Write launch script with correct Python path ──────────────────────────
echo.
echo  [5/5] Writing launcher...

(
    echo @echo off
    echo cd /d "%%~dp0"
    echo "!PYTHONW!" sysmon.py
) > "%~dp0run_sysmon.bat"

echo  Launcher written: run_sysmon.bat

:: ─── Optional: Desktop shortcut ─────────────────────────────────────────────
echo.
set /p SHORTCUT="  Create a Desktop shortcut? [Y/N]: "
if /i "!SHORTCUT!" == "Y" (
    set DESKTOP=%USERPROFILE%\Desktop
    set SCRIPT_DIR=%~dp0
    set SCRIPT_DIR=!SCRIPT_DIR:~0,-1!

    powershell -NoProfile -Command ^
        "$ws = New-Object -ComObject WScript.Shell; ^
         $s  = $ws.CreateShortcut('!DESKTOP!\SysMon.lnk'); ^
         $s.TargetPath       = '!SCRIPT_DIR!\run_sysmon.bat'; ^
         $s.WorkingDirectory = '!SCRIPT_DIR!'; ^
         $s.WindowStyle      = 7; ^
         $s.Description      = 'SysMon System Monitor Overlay'; ^
         $s.Save()"

    if exist "!DESKTOP!\SysMon.lnk" (
        echo  Desktop shortcut created.
    ) else (
        echo  [WARN] Shortcut creation failed ^(non-critical^).
    )
)

:: ─── Optional: Start with Windows ───────────────────────────────────────────
echo.
set /p STARTUP="  Launch SysMon automatically at Windows startup? [Y/N]: "
if /i "!STARTUP!" == "Y" (
    set SCRIPT_DIR=%~dp0
    set SCRIPT_DIR=!SCRIPT_DIR:~0,-1!
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
        /v "SysMon" ^
        /t REG_SZ ^
        /d "\"!SCRIPT_DIR!\run_sysmon.bat\"" ^
        /f >nul 2>&1
    if !errorlevel! == 0 (
        echo  Startup entry added. SysMon will launch on next login.
    ) else (
        echo  [WARN] Could not write startup registry key ^(non-critical^).
    )
)

:: ─── Done ───────────────────────────────────────────────────────────────────
echo.
echo  ===========================================
echo   Installation complete.
echo  ===========================================
echo.
echo  Run SysMon:     double-click run_sysmon.bat
echo  Uninstall deps: pip uninstall psutil nvidia-ml-py
echo.

set /p LAUNCH="  Launch SysMon now? [Y/N]: "
if /i "!LAUNCH!" == "Y" (
    start "" "!PYTHONW!" "%~dp0sysmon.py"
)

endlocal
exit /b 0

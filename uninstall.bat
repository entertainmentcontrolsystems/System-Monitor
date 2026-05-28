@echo off
setlocal EnableDelayedExpansion
title SysMon Uninstaller
color 0C

echo.
echo  ===========================================
echo   SysMon Overlay  ^|  Uninstaller
echo  ===========================================
echo.
set /p CONFIRM="  Remove SysMon startup entry and pip packages? [Y/N]: "
if /i not "!CONFIRM!" == "Y" (
    echo  Cancelled.
    pause
    exit /b 0
)

echo.
echo  Removing startup registry entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "SysMon" /f >nul 2>&1
if !errorlevel! == 0 (echo  Startup entry removed.) else (echo  No startup entry found.)

echo.
echo  Removing Desktop shortcut...
if exist "%USERPROFILE%\Desktop\SysMon.lnk" (
    del "%USERPROFILE%\Desktop\SysMon.lnk"
    echo  Shortcut removed.
) else (
    echo  No shortcut found.
)

echo.
echo  Removing pip packages...
python -m pip uninstall psutil nvidia-ml-py -y 2>nul
if !errorlevel! == 0 (echo  Packages removed.) else (echo  [WARN] Could not remove packages - Python may not be on PATH.)

echo.
echo  Done. You can delete this folder manually.
echo.
pause
endlocal

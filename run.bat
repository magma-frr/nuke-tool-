@echo off
setlocal enabledelayedexpansion
title Magma Suite
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 goto nopython

rem --- kill any previous instance so the port is released ---
powershell -NoProfile -WindowStyle Hidden -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and $_.CommandLine -like '*nuke.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
ping -n 2 127.0.0.1 >nul 2>&1

rem --- dependencies (silent, every run) ---
python -m pip install --quiet --disable-pip-version-check --no-input -r "requirements.txt" >nul 2>&1

where pythonw >nul 2>&1
if errorlevel 1 goto visible

start "" pythonw "nuke.py"

rem --- confirm the process actually came up ---
powershell -NoProfile -WindowStyle Hidden -Command "$ok=$false; 1..20 | ForEach-Object { if (-not $ok) { Start-Sleep -Milliseconds 400; $p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and $_.CommandLine -like '*nuke.py*' }; if ($p) { $ok=$true } } }; if ($ok) { exit 0 } else { exit 1 }"
if errorlevel 1 goto visible

echo.
echo   Magma Suite started. Browser should open in a moment.
echo   If it does not, run this file again.
echo.
timeout /t 3 /nobreak >nul 2>&1
goto :eof

:visible
echo.
echo   Starting in console mode so errors stay on screen...
echo.
python "nuke.py"
echo.
echo   Process exited.
pause
goto :eof

:nopython
echo Python not found. Install Python 3.10+ and add it to PATH.
pause

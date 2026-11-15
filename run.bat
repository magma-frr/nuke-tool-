@echo off
title Discord Nuke Tool
cd /d "%~dp0"
python nuke.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Script crashed with error code %errorlevel%
    echo.
    pause
) else (
    pause
)

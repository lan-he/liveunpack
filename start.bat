@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 live_export.py
) else (
  python live_export.py
)
if errorlevel 1 pause

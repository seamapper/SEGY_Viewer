@echo off
echo Building SEGY GUI Viewer executable...
echo ================================================

cd /d "%~dp0"

python build_segy_gui.py

echo.
echo Build process completed.
pause





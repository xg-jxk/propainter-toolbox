@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo  Installing ProPainter toolbox ... this may take 10-20 minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
echo.
pause

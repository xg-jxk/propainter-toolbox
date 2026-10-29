@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo  [!] .venv not found. Run setup.cmd first.
  pause
  exit /b 1
)
if "%~1"=="" goto usage

set "SC=%~2"
if "%SC%"=="" set "SC=2"

"%PY%" "%~dp0tools\sr_upscale.py" --video "%~1" --scale %SC%
echo.
pause
exit /b

:usage
echo.
echo  Usage:
echo     sr-upscale.cmd "D:\video\a.mp4"       2x
echo     sr-upscale.cmd "D:\video\a.mp4" 3     3x
echo.
pause
exit /b

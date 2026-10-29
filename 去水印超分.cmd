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

echo.
echo  step 1: remove watermark    step 2: upscale %SC%x
echo.
"%PY%" "%~dp0tools\pipeline.py" --video "%~1" --scale %SC%
echo.
pause
exit /b

:usage
echo.
echo  Usage:
echo     wm-and-upscale.cmd "D:\video\a.mp4"        remove watermark + 2x
echo     wm-and-upscale.cmd "D:\video\a.mp4" 3      remove watermark + 3x
echo.
pause
exit /b

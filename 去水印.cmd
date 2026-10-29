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

rem 2nd arg optional: watermark box x,y,w,h ; empty = auto detect
set "RECT=%~2"
if not "%~3"=="" set "RECT=%RECT%,%~3"
if not "%~4"=="" set "RECT=%RECT%,%~4"
if not "%~5"=="" set "RECT=%RECT%,%~5"

if "%RECT%"=="" (
  echo  [auto] detecting watermark ...
  "%PY%" "%~dp0tools\wm_remove.py" --video "%~1" --auto
) else (
  "%PY%" "%~dp0tools\wm_remove.py" --video "%~1" --rect "%RECT%"
)
echo.
pause
exit /b

:usage
echo.
echo  Usage:
echo     wm-remove.cmd "D:\video\a.mp4"                 auto detect
echo     wm-remove.cmd "D:\video\a.mp4" "x,y,w,h"       manual box
echo.
pause
exit /b

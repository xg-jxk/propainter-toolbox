@echo off
chcp 65001 >nul
setlocal
call "%~dp0env.cmd"

if not exist "%PY%" (
  echo  [!] 找不到 .venv，请先双击 setup.cmd 安装。
  pause
  exit /b 1
)
if "%~1"=="" goto usage

set "SC=%~2"
if "%SC%"=="" set "SC=2"

echo.
echo  step 1: 区域修复    step 2: 超分 %SC%x
echo.
"%PY%" "%~dp0tools\pipeline.py" --video "%~1" --scale %SC% %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo  [X] 处理失败，退出码 %RC%。加 --log-file "D:\pp.log" 可把日志存下来。
pause
exit /b %RC%

:usage
echo.
echo  Usage:
echo     修复超分.cmd "D:\video\a.mp4"                        区域修复 + 2x
echo     修复超分.cmd "D:\video\a.mp4" 3                       3x
echo     修复超分.cmd "D:\video\a.mp4" 2 --rect 1314,918,320,120
echo.
echo  其它可透传的参数: --rect --denoise --padding --crf --intermediate-crf
echo                    --encoder --workdir --log-file --keep
echo.
echo  仅限处理你拥有版权或已获授权的视频，详见 TERMS.md
echo.
pause
exit /b 1

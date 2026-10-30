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

rem 额外参数原样透传：
rem   区域修复.cmd "a.mp4"                             自动定位浅色角标（默认）
rem   区域修复.cmd "a.mp4" --rect 1314,918,320,120      手动指定区域
rem   区域修复.cmd "a.mp4" --auto --dry-run             只看检测结果
if "%~2"=="" (
  "%PY%" "%~dp0tools\region_repair.py" --video "%~1" --auto
) else (
  "%PY%" "%~dp0tools\region_repair.py" --video "%~1" %2 %3 %4 %5 %6 %7 %8 %9
)
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo  [X] 处理失败，退出码 %RC%。加 --log-file "D:\pp.log" 可把日志存下来。
pause
exit /b %RC%

:usage
echo.
echo  Usage:
echo     区域修复.cmd "D:\video\a.mp4"                        自动定位
echo     区域修复.cmd "D:\video\a.mp4" --rect 1314,918,320,120
echo     区域修复.cmd "D:\video\a.mp4" --auto --dry-run       只看检测结果
echo     区域修复.cmd "D:\video\a.mp4" --mask D:\masks        逐帧掩码
echo.
echo  其它可透传的参数: --padding --subvideo --neighbor --ref-stride --mask-dilation
echo                    --crf --encoder --workdir --log-file --keep
echo.
echo  仅限处理你拥有版权或已获授权的视频，详见 TERMS.md
echo.
pause
exit /b 1

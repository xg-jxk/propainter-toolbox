@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo.
echo  Installing ProPainter toolbox ... this may take 10-20 minutes.
echo  日志: %~dp0setup.log
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo  [OK] 安装完成。可以双击 去水印.cmd / 超分.cmd / 去水印超分.cmd 了。
) else (
  echo  [X] 安装失败，退出码 %RC%。
  echo      ^-^> 先看 %~dp0setup.log 末尾的报错。
  echo      ^-^> 修好后重新双击 setup.cmd 即可续装（已完成的步骤会跳过）。
  echo      ^-^> 国内网络慢可换成: setup.cmd -Mirror https://pypi.tuna.tsinghua.edu.cn/simple
)
echo.
pause
exit /b %RC%

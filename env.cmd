@echo off
rem ---------------------------------------------------------------------------
rem  由 *.cmd 通过 call 引入，统一环境变量。
rem  调用方必须先 setlocal（本文件不改代码页，避免影响调用方的输出）。
rem ---------------------------------------------------------------------------
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PY=%~dp0.venv\Scripts\python.exe"

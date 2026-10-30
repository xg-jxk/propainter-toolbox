# -*- coding: utf-8 -*-
# 一键打包桌面应用：装 PyInstaller → 生成 exe → 把运行时脚本复制到 dist
#
# 用法：  powershell -NoProfile -ExecutionPolicy Bypass -File build\make.ps1
#         powershell ... -File build\make.ps1 -SkipInstall   # 已装过 PyInstaller
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    throw "找不到 .venv：先运行 setup.cmd 准备运行环境"
}

if (-not $SkipInstall) {
    Write-Host "[build] 安装 PyInstaller ..." -ForegroundColor Cyan
    & $py -m pip install --disable-pip-version-check --no-cache-dir pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }
}

Write-Host "[build] 生成 exe ..." -ForegroundColor Cyan
& $py -m PyInstaller "build\app.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

$dist = Join-Path $Root "dist\ProPainterToolbox"
if (-not (Test-Path -LiteralPath $dist)) { throw "没有产出 dist\ProPainterToolbox" }

# GUI 只是外壳：真正的推理仍然调用这里的脚本和 .venv
# 注意：不要整目录复制 tools/，里面还有 tools/python（便携解释器）和 tools/realcugan（45MB）
$runtimeDirs = @("pplib", "model", "core", "utils", "RAFT", "configs")
foreach ($d in $runtimeDirs) {
    $src = Join-Path $Root $d
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $dist -Recurse -Force }
}

# tools 只复制四个脚本，且必须落在 dist\tools\ 里（cmd 脚本按 tools\xxx.py 调用）
$toolsDst = Join-Path $dist "tools"
New-Item -ItemType Directory -Force -Path $toolsDst | Out-Null
foreach ($f in @("common.py", "wm_remove.py", "sr_upscale.py", "pipeline.py")) {
    Copy-Item -LiteralPath (Join-Path $Root "tools\$f") -Destination $toolsDst -Force
}

$plainFiles = @(
    "inference_propainter.py", "requirements.txt", "requirements-dev.txt",
    "setup.ps1", "setup.cmd", "env.cmd",
    "去水印.cmd", "超分.cmd", "去水印超分.cmd",
    "README.md", "LICENSE", "LICENSE-MIT.txt", "THIRD_PARTY.md"
)
foreach ($f in $plainFiles) {
    $src = Join-Path $Root $f
    if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $dist -Force }
}

$exe = Join-Path $dist "ProPainterToolbox.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "exe 没有生成：$exe" }
$size = [math]::Round(((Get-ChildItem -LiteralPath $dist -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host ""
Write-Host "[build] 完成：$dist" -ForegroundColor Green
Write-Host "[build] 目录体积：$size MB（不含 .venv / weights，首次启动会引导在线安装）" -ForegroundColor Green
Write-Host "[build] 双击 ProPainterToolbox.exe 即可运行" -ForegroundColor Green

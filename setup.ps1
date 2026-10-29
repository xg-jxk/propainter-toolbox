# -*- coding: utf-8 -*-
<#
  ProPainter 工具箱 - 一键安装（Windows / PowerShell 5.1+）
    1. 找 Python（没有就自动下载便携版，不污染系统）
    2. 建 .venv
    3. 装 PyTorch（有 N 卡用 CUDA 版，否则 CPU 版）与依赖
    4. 下载 ProPainter 权重（约 190 MB）
    5. 下载 Real-CUGAN 超分工具（约 45 MB）
#>
param(
    [string]$Torch = "auto",   # auto | cu121 | cpu
    [string]$Mirror = ""       # 例如 https://pypi.tuna.tsinghua.edu.cn/simple
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

function Say($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }

function Get-File($url, $out) {
    # 先直连（30s 超时），失败再走镜像（300s）；GitHub 在国内经常卡住
    $ProgressPreference = "SilentlyContinue"
    $tries = @(@{ u = $url; t = 300 }, @{ u = "https://gh-proxy.com/$url"; t = 300 })
    foreach ($x in $tries) {
        try {
            if (Test-Path $out) { Remove-Item $out -Force -ErrorAction SilentlyContinue }
            Invoke-WebRequest -Uri $x.u -OutFile $out -UseBasicParsing -TimeoutSec $x.t
            if ((Test-Path $out) -and ((Get-Item $out).Length -gt 1MB)) { return }
        } catch { }
    }
    throw "下载失败：$url"
}

function Try-Python($cmd) {
    try {
        $exe = & cmd /c "$cmd -c ""import sys;print(sys.executable)""" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $exe) { return $null }
        $min = & cmd /c "$cmd -c ""import sys;print(sys.version_info[1])""" 2>$null
        if ([int]$min -ge 9 -and [int]$min -le 12) { return $exe.Trim() }
    } catch { }
    return $null
}

# ---------- 1. 找 Python ----------
Say "查找 Python ..."
$pyExe = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    $pyExe = Try-Python $cand
    if ($pyExe) { break }
}
if (-not $pyExe) {
    $globs = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
               "C:\Python3*\python.exe",
               "$env:ProgramFiles\Python3*\python.exe")
    foreach ($g in $globs) {
        foreach ($f in (Get-ChildItem $g -ErrorAction SilentlyContinue)) {
            $m = & $f.FullName -c "import sys;print(sys.version_info[1])" 2>$null
            if ($LASTEXITCODE -eq 0 -and [int]$m -ge 9 -and [int]$m -le 12) { $pyExe = $f.FullName; break }
        }
        if ($pyExe) { break }
    }
}
if (-not $pyExe) {
    Say "系统里没有 Python，下载便携版 3.11（约 30 MB，只放在 tools\python 下）..."
    $pyDir = Join-Path $Root "tools\python"
    $stub = Join-Path $pyDir "python.exe"
    if (-not (Test-Path $stub)) {
        $tgz = Join-Path $env:TEMP "py311.tgz"
        Get-File "https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9+20240726-x86_64-pc-windows-msvc-shared-install_only.tar.gz" $tgz
        New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
        & tar -xzf $tgz -C $pyDir --strip-components=1
        Remove-Item $tgz -Force -ErrorAction SilentlyContinue
    }
    $pyExe = $stub
}
$verLine = & $pyExe -V
Say "使用 $verLine  ($pyExe)"

# ---------- 2. 建虚拟环境 ----------
$venv = Join-Path $Root ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Say "创建虚拟环境 .venv ..."
    & $pyExe -m venv $venv
    if (-not (Test-Path $vpy)) { throw "虚拟环境创建失败" }
} else {
    Say "已存在 .venv，跳过创建"
}
& $vpy -m pip install --upgrade pip -q

# ---------- 3. 装 PyTorch ----------
$hasNv = $false
try { & nvidia-smi -L | Out-Null; $hasNv = ($LASTEXITCODE -eq 0) } catch { }
if ($Torch -eq "auto") { $Torch = if ($hasNv) { "cu121" } else { "cpu" } }
Say "PyTorch: $Torch  (NVIDIA 显卡: $hasNv)"
$idx = "https://download.pytorch.org/whl/" + $Torch
Say "安装 PyTorch（约 2.4 GB，请耐心等）..."
& $vpy -m pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url $idx
if ($LASTEXITCODE -ne 0) { throw "PyTorch 安装失败" }

Say "安装其它依赖 ..."
if ($Mirror) { & $vpy -m pip install -r requirements.txt -i $Mirror }
else { & $vpy -m pip install -r requirements.txt }

# ---------- 4. 下载权重 ----------
$wdir = Join-Path $Root "weights"
New-Item -ItemType Directory -Force -Path $wdir | Out-Null
$base = "https://github.com/sczhou/ProPainter/releases/download/v0.1.0"
foreach ($f in @("raft-things.pth", "recurrent_flow_completion.pth", "ProPainter.pth")) {
    $dst = Join-Path $wdir $f
    if ((Test-Path $dst) -and ((Get-Item $dst).Length -gt 1MB)) { Say "已有 $f"; continue }
    Say "下载 $f ..."
    Get-File "$base/$f" $dst
}

# ---------- 5. Real-CUGAN ----------
$cugan = Join-Path $Root "tools\realcugan"
if (-not (Test-Path (Join-Path $cugan "realcugan-ncnn-vulkan.exe"))) {
    Say "下载 Real-CUGAN ..."
    $zip = Join-Path $env:TEMP "realcugan.zip"
    Get-File "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip" $zip
    $tmp = Join-Path $Root "tools\_tmp"
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force -Path $cugan | Out-Null
    Copy-Item (Join-Path $tmp "realcugan-ncnn-vulkan-20220728-windows\*") $cugan -Recurse -Force
    Remove-Item $tmp -Recurse -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
} else { Say "已有 Real-CUGAN" }

# ---------- 6. 自检 ----------
Say "自检 ..."
& $vpy -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "自检失败：torch 无法导入" }
& $vpy -c "import cv2, scipy, imageio; print('deps ok')"
Say "完成。可以双击 去水印.cmd / 超分.cmd / 去水印超分.cmd 了。"
if (-not $hasNv) { Say "提示：没有 NVIDIA 显卡，去水印会非常慢，建议只用超分。" }

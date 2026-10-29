# -*- coding: utf-8 -*-
<#
  ProPainter 工具箱 - 一键安装（Windows / PowerShell）
  做四件事：
    1. 建 .venv 虚拟环境
    2. 装 PyTorch（有 N 卡装 CUDA 版，没 N 卡装 CPU 版）与依赖
    3. 下载 ProPainter 权重（约 190 MB）
    4. 下载 Real-CUGAN 超分工具（约 45 MB）
#>
param(
    [string]$Torch = "auto",   # auto | cu121 | cpu
    [string]$Mirror = ""       # 例如 https://pypi.tuna.tsinghua.edu.cn/simple
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }

# ---------- 1. 找 Python ----------
Say "查找 Python ..."
$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    try {
        $out = & cmd /c "$cand -c ""import sys;print(sys.version_info[0],sys.version_info[1],sys.executable)""" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $p = $out -split " "
            if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 9 -and [int]$p[1] -le 12) { $py = $cand; break }
        }
    } catch {}
}
if (-not $py) {
    # 兜底：常见安装位置
    $cands = @()
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue
    $cands += Get-ChildItem "C:\Python3*\python.exe" -ErrorAction SilentlyContinue
    $cands += Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue
    foreach ($c in $cands) {
        $v = & $c.FullName -c "import sys;print(sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [int]$v -ge 9 -and [int]$v -le 12) { $py = "`"$($c.FullName)`""; break }
    }
}
if (-not $py) { throw "没找到 Python 3.9~3.12，请先安装：https://www.python.org/downloads/" }
$verLine = & cmd /c "$py -V"
Say "使用 $verLine"

# ---------- 2. 建虚拟环境 ----------
$venv = Join-Path $Root ".venv"
$vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $vpy)) {
    Say "创建虚拟环境 .venv ..."
    & cmd /c "$py -m venv ""$venv"""
    if (-not (Test-Path $vpy)) { throw "虚拟环境创建失败" }
} else {
    Say "已存在 .venv，跳过创建"
}
& cmd /c """$vpy"" -m pip install --upgrade pip -q"

# ---------- 3. 选 PyTorch 版本 ----------
$hasNv = $false
try { & nvidia-smi -L | Out-Null; $hasNv = ($LASTEXITCODE -eq 0) } catch {}
if ($Torch -eq "auto") { $Torch = if ($hasNv) { "cu121" } else { "cpu" } }
Say "PyTorch 目标: $Torch（检测到 NVIDIA: $hasNv）"

$idx = "https://download.pytorch.org/whl/" + $Torch
Say "安装 PyTorch（约 2.5 GB，请耐心等）..."
& cmd /c """$vpy"" -m pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url ""$idx"""
if ($LASTEXITCODE -ne 0) { throw "PyTorch 安装失败" }

Say "安装其它依赖 ..."
$pipArgs = "-r requirements.txt"
if ($Mirror) { $pipArgs += " -i $Mirror" }
& cmd /c """$vpy"" -m pip install $pipArgs"

# ---------- 4. 下载权重 ----------
$wdir = Join-Path $Root "weights"
New-Item -ItemType Directory -Force -Path $wdir | Out-Null
$base = "https://github.com/sczhou/ProPainter/releases/download/v0.1.0"
foreach ($f in @("raft-things.pth", "recurrent_flow_completion.pth", "ProPainter.pth")) {
    $dst = Join-Path $wdir $f
    if ((Test-Path $dst) -and ((Get-Item $dst).Length -gt 1MB)) { Say "已有 $f"; continue }
    Say "下载 $f ..."
    try { Invoke-WebRequest -Uri "$base/$f" -OutFile $dst -UseBasicParsing }
    catch {
        Say "直连失败，改用镜像 ..."
        Invoke-WebRequest -Uri "https://gh-proxy.com/$base/$f" -OutFile $dst -UseBasicParsing
    }
}

# ---------- 5. 下载 Real-CUGAN ----------
$cugan = Join-Path $Root "tools\realcugan"
if (-not (Test-Path (Join-Path $cugan "realcugan-ncnn-vulkan.exe"))) {
    Say "下载 Real-CUGAN ..."
    $zip = Join-Path $env:TEMP "realcugan.zip"
    $url = "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip"
    try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing }
    catch {
        Say "直连失败，改用镜像 ..."
        Invoke-WebRequest -Uri "https://gh-proxy.com/$url" -OutFile $zip -UseBasicParsing
    }
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Root "tools\_tmp") -Force
    New-Item -ItemType Directory -Force -Path $cugan | Out-Null
    Copy-Item (Join-Path $Root "tools\_tmp\realcugan-ncnn-vulkan-20220728-windows\*") $cugan -Recurse -Force
    Remove-Item (Join-Path $Root "tools\_tmp") -Recurse -Force
    Remove-Item $zip -Force
} else { Say "已有 Real-CUGAN" }

# ---------- 6. 自检 ----------
Say "自检 ..."
& cmd /c """$vpy"" -c ""import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"""
if ($LASTEXITCODE -ne 0) { throw "自检失败：torch 无法导入" }
Say "完成。可以双击 去水印.cmd / 超分.cmd / 去水印超分.cmd 了。"
if (-not $hasNv) { Say "提示：没有 NVIDIA 显卡，去水印推理会非常慢（CPU），建议只用超分。" }

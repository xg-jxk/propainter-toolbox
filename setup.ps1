# -*- coding: utf-8 -*-
<#
  ProPainter 工具箱 - 一键安装（Windows / PowerShell 5.1+）
    1. 预检：磁盘空间 / Python / NVIDIA 驱动版本
    2. 找 Python（没有就自动下载便携版，不污染系统）
    3. 建 .venv
    4. 装 PyTorch（有 N 卡用 CUDA 版，否则 CPU 版）与依赖
    5. 下载 ProPainter 权重（约 190 MB）
    6. 下载 Real-CUGAN 超分工具（约 45 MB）
    7. 自检

  说明：
    - 任何一步失败都会以非 0 退出码结束，并把完整过程写进 setup.log；
      修好后重新运行即可续装（已完成的步骤会自动跳过）。
    - 重复运行是安全的：.venv / 权重 / Real-CUGAN 都有存在性检查。
#>
param(
    [string]$Torch = "auto",   # auto | cu121 | cpu
    [string]$Mirror = "",      # 例如 https://pypi.tuna.tsinghua.edu.cn/simple
    [switch]$Force             # 忽略"已存在"判断，强制重装依赖与权重
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

$LogPath = Join-Path $Root "setup.log"
$script:Logging = $false
$script:Vpy = $null
$script:HasCurl = $false

function Say($m) { Write-Host "[setup] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn ] $m" -ForegroundColor Yellow }

function Fail($m) { throw $m }

# ---------------------------------------------------------------- 基础工具

function Start-Log {
    if ($script:Logging) { return }
    try {
        if (Test-Path -LiteralPath $LogPath) {
            Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
        }
        Start-Transcript -Path $LogPath -Force | Out-Null
        $script:Logging = $true
    } catch { }
}

function Stop-Log {
    if (-not $script:Logging) { return }
    try { Stop-Transcript | Out-Null } catch { }
    $script:Logging = $false
}

function Get-FreeGB($path) {
    try {
        $item = Get-Item -LiteralPath $path
        if ($item -and $item.PSDrive) { return [math]::Round($item.PSDrive.Free / 1GB, 1) }
    } catch { }
    return $null
}

function Test-Curl {
    try {
        $null = & curl.exe --version 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# 取远端的真实大小，用来校验"已有文件是否完整"。拿不到就返回 0 走兜底值。
function Get-RemoteSize($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -Method Head -MaximumRedirection 5 -UseBasicParsing -TimeoutSec 30
        $len = $r.Headers['Content-Length']
        if ($len -is [array]) { $len = $len[0] }
        if ($len) { return [int64]$len }
    } catch { }
    return [int64]0
}

# 下载：直连 → 两个镜像，每源重试 2 次；先写 .part，校验大小后再落盘，
# 避免"半截文件被下次运行当成已下载"（这是旧版最坑的地方）。
function Get-File($url, $out, [int64]$minBytes = 1048576) {
    $part = "$out.part"
    $sources = @($url, "https://gh-proxy.com/$url", "https://ghfast.top/$url")
    foreach ($u in $sources) {
        for ($i = 1; $i -le 2; $i++) {
            if (Test-Path -LiteralPath $part) {
                Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
            }
            $code = 1
            try {
                if ($script:HasCurl) {
                    & curl.exe -fL --retry 2 --retry-delay 2 --connect-timeout 20 --max-time 3600 -o $part $u
                    $code = $LASTEXITCODE
                } else {
                    Invoke-WebRequest -Uri $u -OutFile $part -UseBasicParsing -TimeoutSec 1200
                    $code = 0
                }
            } catch {
                $code = 1
            }
            if ($code -eq 0 -and (Test-Path -LiteralPath $part)) {
                $size = (Get-Item -LiteralPath $part).Length
                if ($size -ge $minBytes) {
                    Move-Item -LiteralPath $part -Destination $out -Force
                    return
                }
                Warn "    文件过小（$([math]::Round($size / 1MB, 1)) MB），视为失败"
            }
            Warn "    第 $i 次下载失败，准备换源/重试 ..."
            Start-Sleep -Seconds 2
        }
    }
    if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue }
    Fail "下载失败：$url"
}

function Step-Pip([string[]]$argv, [string]$what) {
    Say $what
    $full = @("-m", "pip", "install", "--disable-pip-version-check", "--no-input") + $argv
    & $script:Vpy @full
    if ($LASTEXITCODE -ne 0) {
        Fail "$what 失败（pip 退出码 $LASTEXITCODE）。可加 -Mirror 换源后重试"
    }
}

function Test-PythonExe($exe) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $null }
    try {
        $v = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return ([string]$v).Trim() }
    } catch { }
    return $null
}

# ---------------------------------------------------------------- 主流程

Start-Log
$exitCode = 0
try {

# ---------------------------------------------------------------- 预检

Say "预检 ..."
$freeGB = Get-FreeGB $Root
if ($null -ne $freeGB) {
    if ($freeGB -lt 4) {
        Fail "磁盘剩余空间只有 $freeGB GB，装不下（约需 7-8 GB）。清理后重试。"
    } elseif ($freeGB -lt 8) {
        Warn "磁盘剩余 $freeGB GB，装完后可能偏紧（建议 8 GB 以上）。"
    } else {
        Say "磁盘剩余 $freeGB GB"
    }
}

$script:HasCurl = Test-Curl
if (-not $script:HasCurl) { Warn "未找到 curl.exe，改用 Invoke-WebRequest（大文件更容易卡住）" }

# NVIDIA 驱动：有卡不等于能用 cu121，驱动太老会 import torch 就失败
$hasNv = $false
$drv = $null
$drvOK = $false
try {
    $ErrorActionPreference = "Continue"
    $o = & nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -and $o) {
        $drv = ([string]($o | Select-Object -First 1)).Trim()
        $hasNv = $true
        $num = [double]($drv.Split(".")[0] + "." + $drv.Split(".")[1])
        $drvOK = ($num -ge 527.41)
    }
} catch {
    $ErrorActionPreference = "Stop"
}

if ($hasNv) {
    Say "检测到 NVIDIA 显卡，驱动 $drv"
    if (-not $drvOK) {
        Warn "驱动版本 $drv 低于 cu121 要求的 527.41，将改用 CPU 版（建议升级驱动后重跑）"
    }
} else {
    Say "未检测到可用的 NVIDIA 显卡，使用 CPU 版"
}

if ($Torch -notin @("auto", "cu121", "cpu")) { Fail "-Torch 只能是 auto / cu121 / cpu" }

# ---------------------------------------------------------------- 1. Python

Say "查找 Python ..."
$pyExe = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "py -3.9", "python")) {
    $exe = $null
    try {
        $exe = & cmd /c "$cand -c ""import sys;print(sys.executable)""" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $exe) { $exe = $null }
    } catch { $exe = $null }
    if ($exe) {
        $ver = Test-PythonExe (([string]$exe).Trim())
        if ($ver) { $pyExe = ([string]$exe).Trim(); break }
    }
}

if (-not $pyExe) {
    $globs = @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
               "C:\Python3*\python.exe",
               "$env:ProgramFiles\Python3*\python.exe")
    foreach ($g in $globs) {
        foreach ($f in (Get-ChildItem $g -ErrorAction SilentlyContinue)) {
            if (Test-PythonExe $f.FullName) { $pyExe = $f.FullName; break }
        }
        if ($pyExe) { break }
    }
}

if (-not $pyExe) {
    $pyDir = Join-Path $Root "tools\python"
    $stub = Join-Path $pyDir "python.exe"
    if (-not (Test-PythonExe $stub) -or $Force) {
        Say "系统里没有可用的 Python，下载便携版 3.11（约 30 MB，只放在 tools\python 下）..."
        $tgz = Join-Path $env:TEMP "py311.tgz"
        Get-File "https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9+20240726-x86_64-pc-windows-msvc-shared-install_only.tar.gz" $tgz 20971520
        if (Test-Path -LiteralPath $pyDir) {
            Remove-Item -LiteralPath $pyDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        New-Item -ItemType Directory -Force -Path $pyDir | Out-Null
        & tar -xzf $tgz -C $pyDir --strip-components=1
        if ($LASTEXITCODE -ne 0) {
            Remove-Item -LiteralPath $tgz -Force -ErrorAction SilentlyContinue
            Fail "解压便携 Python 失败（需要 Windows 10 1803+ 自带的 tar）。可手动安装 Python 3.11 后重试"
        }
        Remove-Item -LiteralPath $tgz -Force -ErrorAction SilentlyContinue
    }
    $ver = Test-PythonExe $stub
    if (-not $ver) { Fail "便携 Python 无法运行：$stub（删除 tools\python 后重试）" }
    $pyExe = $stub
}

$verLine = "unknown"
try { $verLine = ([string](& $pyExe -V 2>$null)).Trim() } catch { }
Say "使用 $verLine  ($pyExe)"

# ---------------------------------------------------------------- 2. venv

$venv = Join-Path $Root ".venv"
$script:Vpy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $script:Vpy) -or $Force) {
    Say "创建虚拟环境 .venv ..."
    if (Test-Path -LiteralPath $venv) {
        Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction SilentlyContinue
    }
    & $pyExe -m venv $venv
    if (-not (Test-Path -LiteralPath $script:Vpy)) { Fail "虚拟环境创建失败" }
} else {
    Say "已存在 .venv，跳过创建"
}

Step-Pip @("--upgrade", "pip") "升级 pip"

# ---------------------------------------------------------------- 3. PyTorch

if ($Torch -eq "auto") {
    if ($hasNv -and $drvOK) { $Torch = "cu121" } else { $Torch = "cpu" }
}
$idx = "https://download.pytorch.org/whl/" + $Torch
Say "PyTorch: $Torch  (NVIDIA: $hasNv, 驱动: $drv)"
Step-Pip @("--no-cache-dir", "torch==2.5.1", "torchvision==0.20.1", "--index-url", $idx) "安装 PyTorch（约 2.4 GB，请耐心等）"

# ---------------------------------------------------------------- 4. 依赖

$req = Join-Path $Root "requirements.txt"
$pipExtra = @("--timeout", "60", "--retries", "3")
if ($Mirror) {
    Step-Pip (@("-r", $req) + $pipExtra + @("-i", $Mirror)) "安装其它依赖（镜像：$Mirror）"
} else {
    Say "安装其它依赖 ..."
    & $script:Vpy -m pip install --disable-pip-version-check --no-input -r $req @pipExtra
    if ($LASTEXITCODE -ne 0) {
        Warn "默认源安装依赖失败，改用清华镜像重试一次 ..."
        & $script:Vpy -m pip install --disable-pip-version-check --no-input -r $req @pipExtra -i https://pypi.tuna.tsinghua.edu.cn/simple
        if ($LASTEXITCODE -ne 0) {
            Fail "安装其它依赖失败（pip 退出码 $LASTEXITCODE）。可加 -Mirror 换源后重试"
        }
    }
}

# ---------------------------------------------------------------- 5. 权重

$wdir = Join-Path $Root "weights"
New-Item -ItemType Directory -Force -Path $wdir | Out-Null
$base = "https://github.com/sczhou/ProPainter/releases/download/v0.1.0"
$weightFiles = @(
    # 最低大小取实际大小的 98%（HEAD 拿不到时才用这里的兜底值）。
    # 注意 recurrent_flow_completion.pth 只有 19.4 MB，不要把阈值写太高，
    # 否则每次运行都会把正常文件误判成残缺并反复重下。
    @{ Name = "raft-things.pth";               Min = 19922944 },
    @{ Name = "recurrent_flow_completion.pth"; Min = 19293798 },
    @{ Name = "ProPainter.pth";                Min = 149946368 }
)
foreach ($wf in $weightFiles) {
    $dst = Join-Path $wdir $wf.Name
    $url = "$base/$($wf.Name)"
    $min = [int64]$wf.Min
    $remote = Get-RemoteSize $url
    if ($remote -gt 0) { $min = [int64]($remote * 0.98) }
    $ok = $false
    if ((Test-Path -LiteralPath $dst) -and -not $Force) {
        $sz = (Get-Item -LiteralPath $dst).Length
        if ($sz -ge $min) { $ok = $true }
        else {
            Warn "已有 $($wf.Name) 但只有 $([math]::Round($sz / 1MB, 1)) MB（应约 $([math]::Round($min / 1MB, 1)) MB），判定为残缺，重新下载"
        }
    }
    if ($ok) { Say "已有 $($wf.Name)"; continue }
    Say "下载 $($wf.Name) ..."
    Get-File $url $dst $min
}

# ---------------------------------------------------------------- 6. Real-CUGAN

$cugan = Join-Path $Root "tools\realcugan"
$cuganExe = Join-Path $cugan "realcugan-ncnn-vulkan.exe"
if ((Test-Path -LiteralPath $cuganExe) -and -not $Force) {
    Say "已有 Real-CUGAN"
} else {
    Say "下载 Real-CUGAN（约 45 MB）..."
    $zip = Join-Path $env:TEMP "realcugan.zip"
    Get-File "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip" $zip 31457280
    $tmp = Join-Path $Root "tools\_tmp"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force -Path $cugan | Out-Null
    $inner = Join-Path $tmp "realcugan-ncnn-vulkan-20220728-windows"
    if (-not (Test-Path -LiteralPath $inner)) { Fail "Real-CUGAN 压缩包结构异常：$tmp" }
    Copy-Item (Join-Path $inner "*") $cugan -Recurse -Force
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $cuganExe)) { Fail "Real-CUGAN 解压后找不到 realcugan-ncnn-vulkan.exe" }
}

# ---------------------------------------------------------------- 7. 自检

Say "自检 ..."
& $script:Vpy -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { Fail "自检失败：torch 无法导入" }
& $script:Vpy -c "import cv2,scipy,imageio,timm,einops;print('deps ok')"
if ($LASTEXITCODE -ne 0) { Fail "自检失败：依赖不完整（cv2/scipy/imageio/timm/einops）" }

Say "完成。可以双击 去水印.cmd / 超分.cmd / 去水印超分.cmd 了。"
if (-not ($hasNv -and $drvOK)) {
    Warn "没有可用的 NVIDIA 显卡，去水印会非常慢，建议只用超分。"
}
Say "日志已保存：$LogPath"

} catch {
    Write-Host ""
    Write-Host "[X] 安装失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    完整日志：$LogPath" -ForegroundColor Yellow
    Write-Host "    修好后重新双击 setup.cmd 即可续装（已完成的步骤会自动跳过）。" -ForegroundColor Yellow
    $exitCode = 1
} finally {
    $tmp = Join-Path $Root "tools\_tmp"
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    # 被 Ctrl+C 打断时可能留下 .part，下次运行前顺手清掉
    $wdirTmp = Join-Path $Root "weights"
    if (Test-Path -LiteralPath $wdirTmp) {
        Get-ChildItem -LiteralPath $wdirTmp -Filter "*.part" -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
    Stop-Log
}

exit $exitCode

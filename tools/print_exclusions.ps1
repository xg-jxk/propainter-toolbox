# 打印需要加入杀软信任区的两个目录
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot
$appdata = Join-Path $env:LOCALAPPDATA "ProPainterToolbox"

"把下面两个目录加入杀软信任区（火绒：防护中心 → 设置 → 信任区 → 添加目录）："
""
"  1) $proj"
"  2) $appdata"
""

foreach ($p in @($proj, $appdata)) {
    if (Test-Path -LiteralPath $p) { "已存在：$p" } else { "不存在：$p" }
}

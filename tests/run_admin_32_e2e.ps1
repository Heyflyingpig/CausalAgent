param(
    [switch]$ReuseExisting,
    [switch]$KeepSeededData
)

# 3.2 沿用 3.1 的隔离容器命名以保持兼容；实际脚本已覆盖 3.2 migration、
# 受控用户/文件写入、生命周期清理、主从追平和普通用户回归。
$arguments = @{}
if ($ReuseExisting) {
    $arguments["ReuseExisting"] = $true
}
if ($KeepSeededData) {
    $arguments["KeepSeededData"] = $true
}

& "$PSScriptRoot/run_admin_31_e2e.ps1" @arguments
exit $LASTEXITCODE

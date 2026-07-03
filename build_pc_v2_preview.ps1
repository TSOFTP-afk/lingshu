# 灵枢 v2.0 PC 端打包入口
# 已从 PyInstaller 迁移至 Electron Builder
#
# 直接调用: .\build_electron.ps1 -Version "v2.0-preview" -ProductName "灵枢"

param(
    [string]$Version = "v2.0-preview",
    [string]$ProductName = "LingShu"
)

$buildScript = Join-Path $PSScriptRoot "build_electron.ps1"
if (-not (Test-Path -LiteralPath $buildScript)) {
    Write-Error "找不到 build_electron.ps1，请确保脚本在项目根目录"
    exit 1
}

& $buildScript -Version $Version -ProductName $ProductName
exit $LASTEXITCODE

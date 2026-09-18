# 灵枢 v2.0 桌面端 + Web 书城打包入口
# 已从 PyInstaller 迁移至 Electron Builder + Vue Build

param(
    [string]$Version = "v2.0-preview",
    [string]$ProductName = "灵枢"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$releaseDir = Join-Path $projectRoot "release"

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

# Step 1: 构建 Web 书城
Write-Output "[1/2] 构建 Web 书城..."
Push-Location (Join-Path $projectRoot "web")
try {
    & npm run build 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Web 构建失败" }
    $webZip = Join-Path $releaseDir "lingshu-web-$Version.zip"
    Compress-Archive -Path (Join-Path $projectRoot "web\dist\*") -DestinationPath $webZip -Force
    Write-Output "  Web 包: $webZip"
} finally { Pop-Location }

# Step 2: 构建 Electron 桌面端
Write-Output "[2/2] 构建 Electron 桌面端..."
$buildScript = Join-Path $projectRoot "build_electron.ps1"
& $buildScript -Version $Version -ProductName $ProductName
exit $LASTEXITCODE

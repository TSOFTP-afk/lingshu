<#
.SYNOPSIS
  灵枢 v2.0 Electron 打包脚本（可视化进度条）
  
.DESCRIPTION
  4 步流程: 前端构建 -> 依赖安装 -> NSIS 打包 -> 验证签名
  产物自动缓存，重复运行跳过已完成步骤。

.EXAMPLE
  .\build_electron.ps1 -Version "v2.0-preview" -ProductName "灵枢"
#>
param(
    [string]$Version = "v2.0-preview",
    [string]$ProductName = "LingShu"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }
$projectRoot = (Resolve-Path -LiteralPath $projectRoot).Path
$releaseDir = Join-Path $projectRoot "release"
$electronDir = Join-Path $projectRoot "electron"
$frontendDir = Join-Path $projectRoot "lingshu-app"
$pkgPath = Join-Path $electronDir "package.json"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$launcherSourcePath = Join-Path $projectRoot "packaging\ElectronSelfExtractLauncher.cs"
$appIconPath = Join-Path $projectRoot "packaging\app_icon.ico"

$portableExeOutput = Join-Path $releaseDir "$ProductName-$Version.exe"
$appDirOutput = Join-Path $releaseDir "$ProductName-$Version-app"
$appExeOutput = Join-Path $appDirOutput "LingShu.exe"
$cacheDir = Join-Path $releaseDir "electron-cache"
$cacheMarker = Join-Path $cacheDir "$Version.marker"
$electronPythonRoot = Join-Path $releaseDir "electron-python"
$electronPythonDir = Join-Path $electronPythonRoot "python"
$electronPythonManifest = Join-Path $electronPythonRoot "runtime-manifest.json"

# ---------- helpers ----------

function Write-Step($step, $total, $label) {
    $pct = [Math]::Round(($step / $total) * 100)
    Write-Progress -Activity "LingShu Pack: $ProductName-$Version" -Status "[$step/$total] $label" -PercentComplete $pct
    Write-Host "  [$step/$total] $label" -ForegroundColor Cyan
}

function Invoke-NpmStream($script, $cwd) {
    $npmArgs = if ($script -eq "install") { "install" } else { "run $script" }
    Write-Host "    npm $npmArgs ..." -ForegroundColor DarkGray
    $outFile = "$env:TEMP\lingshu-npm-$script.txt"
    $errFile = "$env:TEMP\lingshu-npm-err.txt"
    Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c npm $npmArgs"
    $psi.WorkingDirectory = $cwd
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds 500
        $out = $proc.StandardOutput.ReadLine()
        if ($out) { Write-Host "`r    $($out.Substring(0,[Math]::Min(78,$out.Length)))" -NoNewline }
        $elapsed = $sw.Elapsed.TotalSeconds
    } while (-not $proc.HasExited -and $elapsed -lt 600)

    Write-Host ""
    if (-not $proc.HasExited) { $proc.Kill() }
    $proc.WaitForExit()
    return $proc.ExitCode
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Resolve-HostPythonExe {
    if ($env:LINGSHU_PYTHON -and (Test-Path -LiteralPath $env:LINGSHU_PYTHON)) {
        return (Resolve-Path -LiteralPath $env:LINGSHU_PYTHON).Path
    }
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return (Resolve-Path -LiteralPath $venvPython).Path
    }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python runtime not found. Install Python 3.13 or set LINGSHU_PYTHON."
}

function Resolve-PythonRuntimeRoot([string]$PythonExePath) {
    $code = "import sys; print(sys.base_prefix or sys.prefix)"
    $runtimeRoot = (& $PythonExePath -c $code 2>$null | Select-Object -First 1)
    if (-not $runtimeRoot) {
        $runtimeRoot = Split-Path -Parent $PythonExePath
    }
    $runtimeRoot = $runtimeRoot.Trim()
    if (-not (Test-Path -LiteralPath $runtimeRoot)) {
        throw "Could not resolve Python runtime root from $PythonExePath"
    }
    return (Resolve-Path -LiteralPath $runtimeRoot).Path
}

function Copy-FileIfExists([string]$Source, [string]$DestinationDir, [bool]$Required = $true) {
    if (Test-Path -LiteralPath $Source) {
        New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
        Copy-Item -LiteralPath $Source -Destination $DestinationDir -Force
    } elseif ($Required) {
        throw "Required runtime file not found: $Source"
    }
}

function Copy-DirectoryFast([string]$Source, [string]$Destination, [string[]]$ExcludeDirs = @()) {
    if (-not (Test-Path -LiteralPath $Source)) { return }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $args = @($Source, $Destination, "/E", "/MT:8", "/NJH", "/NJS", "/NP", "/NS", "/NDL", "/R:1", "/W:1")
    if ($ExcludeDirs.Count -gt 0) {
        $args += "/XD"
        foreach ($dir in $ExcludeDirs) { $args += $dir }
    }
    robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed from $Source to $Destination ($LASTEXITCODE)" }
}

function Clear-SafeDirectory([string]$Target, [string]$AllowedRoot) {
    $resolvedAllowedRoot = (Resolve-Path -LiteralPath $AllowedRoot).Path
    if (Test-Path -LiteralPath $Target) {
        $resolvedTarget = (Resolve-Path -LiteralPath $Target).Path
        if (-not $resolvedTarget.StartsWith($resolvedAllowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clear unexpected path: $resolvedTarget"
        }
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
}

function Find-LatestPythonRuntimeCache {
    $runtimeRepo = Join-Path $releaseDir "runtime"
    if (-not (Test-Path -LiteralPath $runtimeRepo)) { return $null }
    $candidates = Get-ChildItem -LiteralPath $runtimeRepo -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "python\python.exe") } |
        Sort-Object LastWriteTime -Descending
    if ($candidates.Count -eq 0) { return $null }
    return (Join-Path $candidates[0].FullName "python")
}

function Copy-SystemPythonRuntime([string]$PythonExePath, [string]$TargetDir) {
    $pythonRoot = Resolve-PythonRuntimeRoot $PythonExePath
    Copy-FileIfExists (Join-Path $pythonRoot "python.exe") $TargetDir
    Copy-FileIfExists (Join-Path $pythonRoot "pythonw.exe") $TargetDir $false
    Copy-FileIfExists (Join-Path $pythonRoot "python3.dll") $TargetDir $false
    $pythonDll = Get-ChildItem -LiteralPath $pythonRoot -Filter "python*.dll" -ErrorAction SilentlyContinue |
        Sort-Object Name |
        Select-Object -First 1
    if ($pythonDll) { Copy-Item -LiteralPath $pythonDll.FullName -Destination $TargetDir -Force }
    Copy-FileIfExists (Join-Path $pythonRoot "vcruntime140.dll") $TargetDir $false
    Copy-FileIfExists (Join-Path $pythonRoot "vcruntime140_1.dll") $TargetDir $false
    Copy-DirectoryFast (Join-Path $pythonRoot "DLLs") (Join-Path $TargetDir "DLLs")
    Copy-DirectoryFast (Join-Path $pythonRoot "Lib") (Join-Path $TargetDir "Lib") @("__pycache__")
    $tclSource = Join-Path $pythonRoot "tcl"
    if (Test-Path -LiteralPath $tclSource) {
        Copy-DirectoryFast $tclSource (Join-Path $TargetDir "tcl") @("__pycache__")
    }
}

function Prepare-PythonRuntime {
    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        throw "requirements.txt not found: $requirementsPath"
    }
    $requirementsHash = Get-FileSha256 $requirementsPath
    if ((Test-Path -LiteralPath (Join-Path $electronPythonDir "python.exe")) -and (Test-Path -LiteralPath $electronPythonManifest)) {
        try {
            $manifest = Get-Content -LiteralPath $electronPythonManifest -Raw | ConvertFrom-Json
            if ([string]$manifest.requirements_hash -eq $requirementsHash) {
                Write-Host "  OK: bundled Python runtime cache is current" -ForegroundColor Green
                return
            }
        } catch {
            Write-Host "  Runtime manifest unreadable; rebuilding" -ForegroundColor Yellow
        }
    }

    Clear-SafeDirectory $electronPythonRoot $releaseDir
    New-Item -ItemType Directory -Path $electronPythonDir -Force | Out-Null

    $cachedPython = Find-LatestPythonRuntimeCache
    if ($cachedPython) {
        Write-Host "  Reusing runtime cache: $cachedPython" -ForegroundColor DarkGray
        Copy-DirectoryFast $cachedPython $electronPythonDir @("__pycache__")
    } else {
        $hostPython = Resolve-HostPythonExe
        Write-Host "  Copying system Python runtime: $hostPython" -ForegroundColor DarkGray
        Copy-SystemPythonRuntime $hostPython $electronPythonDir
    }

    $bundledPython = Join-Path $electronPythonDir "python.exe"
    if (-not (Test-Path -LiteralPath $bundledPython)) {
        throw "Bundled python.exe was not prepared"
    }
    $sitePackages = Join-Path $electronPythonDir "Lib\site-packages"
    Clear-SafeDirectory $sitePackages $electronPythonDir

    & $bundledPython -m ensurepip --upgrade | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "ensurepip failed for bundled Python" }

    & $bundledPython -m pip install --upgrade --target $sitePackages -r $requirementsPath | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "pip install failed for bundled Python runtime" }

    @{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        requirements_hash = $requirementsHash
    } | ConvertTo-Json | Set-Content -LiteralPath $electronPythonManifest -Encoding UTF8
    Write-Host "  OK: bundled Python runtime prepared" -ForegroundColor Green
}

function ConvertTo-CSharpLiteral([string]$Value) {
    return $Value.Replace("\", "\\").Replace('"', '\"')
}

function Resolve-CscExe {
    $candidates = @(
        (Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        (Join-Path $env:SystemRoot "Microsoft.NET\Framework\v4.0.30319\csc.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    throw "Could not find .NET Framework csc.exe for self-extract launcher."
}

function New-LauncherConfig([string]$Path) {
    $escapedProduct = ConvertTo-CSharpLiteral $ProductName
    $escapedVersion = ConvertTo-CSharpLiteral $Version
@"
namespace LingShuElectronLauncher
{
    internal static class LauncherConfig
    {
        public const string AppName = "$escapedProduct";
        public const string Version = "$escapedVersion";
        public const string InnerExeName = "LingShu.exe";
    }
}
"@ | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Build-SingleExeLauncher([string]$AppDir, [string]$OutputExe) {
    if (-not (Test-Path -LiteralPath $launcherSourcePath)) {
        throw "Launcher source not found: $launcherSourcePath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir "LingShu.exe"))) {
        throw "App directory is missing LingShu.exe: $AppDir"
    }

    Add-Type -AssemblyName "System.IO.Compression.FileSystem"
    $safeVersion = ($Version -replace '[\\/:*?"<>|]', '_')
    $launcherWorkRoot = Join-Path $releaseDir "launcher-work-$safeVersion"
    Clear-SafeDirectory $launcherWorkRoot $releaseDir
    $payloadZip = Join-Path $launcherWorkRoot "payload.zip"

    Write-Host "  Compressing app payload (Fastest)..." -ForegroundColor DarkGray
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $AppDir,
        $payloadZip,
        [System.IO.Compression.CompressionLevel]::Fastest,
        $false
    )

    $csc = Resolve-CscExe
    $cscWorkRoot = Join-Path ([System.IO.Path]::GetTempPath()) "lingshu-electron-launcher-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    New-Item -ItemType Directory -Path $cscWorkRoot -Force | Out-Null
    $cscLauncherSource = Join-Path $cscWorkRoot "ElectronSelfExtractLauncher.cs"
    $cscLauncherConfig = Join-Path $cscWorkRoot "LauncherConfig.cs"
    $cscPayloadZip = Join-Path $cscWorkRoot "payload.zip"
    $cscTempOutputExe = Join-Path $cscWorkRoot "launcher.exe"

    try {
        Copy-Item -LiteralPath $launcherSourcePath -Destination $cscLauncherSource -Force
        Copy-Item -LiteralPath $payloadZip -Destination $cscPayloadZip -Force
        New-LauncherConfig $cscLauncherConfig

        $cscArgs = @(
            "/nologo",
            "/target:winexe",
            "/optimize+",
            "/out:$cscTempOutputExe",
            "/resource:$cscPayloadZip,payload.zip",
            "/reference:System.IO.Compression.dll",
            "/reference:System.IO.Compression.FileSystem.dll",
            "/reference:System.Drawing.dll",
            "/reference:System.Windows.Forms.dll"
        )
        if (Test-Path -LiteralPath $appIconPath) {
            $cscAppIcon = Join-Path $cscWorkRoot "app_icon.ico"
            Copy-Item -LiteralPath $appIconPath -Destination $cscAppIcon -Force
            $cscArgs += "/win32icon:$cscAppIcon"
        }
        $cscArgs += $cscLauncherSource
        $cscArgs += $cscLauncherConfig

        Write-Host "  Compiling self-extract launcher..." -ForegroundColor DarkGray
        & $csc @cscArgs | Out-Host
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cscTempOutputExe)) {
            throw "Launcher compiler failed."
        }

        Copy-Item -LiteralPath $cscTempOutputExe -Destination $OutputExe -Force
    } finally {
        try { Remove-Item -LiteralPath $cscWorkRoot -Recurse -Force } catch { }
        try { Remove-Item -LiteralPath $launcherWorkRoot -Recurse -Force } catch { }
    }
}

# ================================================================

Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host "  LingShu Electron Packager                         " -ForegroundColor Green
Write-Host "  Version : $Version" -ForegroundColor Green
Write-Host "  Product : $ProductName" -ForegroundColor Green
Write-Host "  Output  : $ProductName-$Version.exe" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
Write-Host ""

# --- cache check ---
if (Test-Path -LiteralPath $portableExeOutput) {
    $sz = [Math]::Round((Get-Item -LiteralPath $portableExeOutput).Length / 1MB, 1)
    Write-Host "[CACHE] $ProductName-$Version.exe exists (${sz} MB)" -ForegroundColor Yellow
    Write-Host "[CACHE] To rebuild, delete this file first" -ForegroundColor Yellow
    Write-Progress -Activity "LingShu Pack" -Completed
    exit 0
}

$TOTAL = 6

# --- Step 1: Build Vue ---
Write-Step 1 $TOTAL "Build Vue frontend (lingshu-app)"
$ec = Invoke-NpmStream "build" $frontendDir
if ($ec -ne 0) { Write-Host "  FAILED" -ForegroundColor Red; exit $ec }
$frontendDist = Join-Path $frontendDir "dist"
$electronDist = Join-Path $electronDir "dist"
if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
    Write-Host "  FAILED: lingshu-app/dist/index.html not found" -ForegroundColor Red
    exit 1
}
$resolvedElectronDir = (Resolve-Path -LiteralPath $electronDir).Path
if (Test-Path -LiteralPath $electronDist) {
    $resolvedElectronDist = (Resolve-Path -LiteralPath $electronDist).Path
    if (-not $resolvedElectronDist.StartsWith($resolvedElectronDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "  FAILED: refusing to clear unexpected dist path $resolvedElectronDist" -ForegroundColor Red
        exit 1
    }
    Remove-Item -LiteralPath $resolvedElectronDist -Recurse -Force
}
New-Item -ItemType Directory -Path $electronDist -Force | Out-Null
Copy-Item -Path (Join-Path $frontendDist "*") -Destination $electronDist -Recurse -Force
Write-Host "  Synced Vue dist -> electron/dist" -ForegroundColor Green
Write-Host "  OK" -ForegroundColor Green

# --- Step 2: Check Electron ---
Write-Step 2 $TOTAL "Install Electron dependencies"
$ebin = Join-Path $electronDir "node_modules\electron\dist\electron.exe"
if (Test-Path $ebin) {
    Write-Host "  OK: Electron installed" -ForegroundColor Green
} else {
    Write-Host "  Installing Electron (first time, ~2-3 min)..." -ForegroundColor Yellow
    Push-Location $electronDir
    try {
        $env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
        $ec = Invoke-NpmStream "install" $electronDir
        if (-not (Test-Path $ebin)) {
            Write-Host "  Downloading Electron binary..." -ForegroundColor Yellow
            $ij = Join-Path $electronDir "node_modules\electron\install.js"
            if (Test-Path $ij) { node $ij 2>&1 | Out-Null }
        }
    } finally { Pop-Location }
    if (Test-Path $ebin) { Write-Host "  OK" -ForegroundColor Green }
    else { Write-Host "  WARN: download may have failed (network)" -ForegroundColor Red }
}

# --- Step 3: Python runtime ---
Write-Step 3 $TOTAL "Prepare bundled Python runtime"
Prepare-PythonRuntime

# --- Step 4: Electron Builder ---
Write-Step 4 $TOTAL "Electron Builder pack (app directory)"
Write-Host "  Target: win/x64 + unpacked app directory" -ForegroundColor DarkGray
Write-Host "  Estimated: 3-5 min first run" -ForegroundColor DarkGray

Push-Location $electronDir
try {
    $pkg = Get-Content -LiteralPath $pkgPath -Raw | ConvertFrom-Json
    $origVer = $pkg.version
    # electron-builder requires valid semver (x.y.z); use 2.0.0 as base
    $semver = ($Version -replace "^v","" -replace "-.*$","")
    if ($semver -notmatch '^\d+\.\d+\.\d+$') { $semver = "2.0.0" }
    $pkg.version = $semver
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($pkgPath, ($pkg | ConvertTo-Json -Depth 10) + "`n", $utf8)

    $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
    $outF = "$env:TEMP\lingshu-eb-out.txt"
    Remove-Item $outF -ErrorAction SilentlyContinue

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "cmd.exe"
    $psi.Arguments = "/c npx electron-builder --win --x64 --dir"
    $psi.WorkingDirectory = $electronDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $eb = [System.Diagnostics.Process]::Start($psi)

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $eb.HasExited) {
        Start-Sleep -Milliseconds 800
        $out = $eb.StandardOutput.ReadLine()
        if ($out) { Write-Host "`r  $($out.Substring(0,[Math]::Min(78,$out.Length)))" -NoNewline -ForegroundColor DarkGray }
        if ($sw.Elapsed.TotalSeconds -gt 900) { $eb.Kill(); break }
    }
    Write-Host ""
    $ebResult = $eb.ExitCode

    $pkg.version = $origVer
    [System.IO.File]::WriteAllText($pkgPath, ($pkg | ConvertTo-Json -Depth 10) + "`n", $utf8)

    if ($ebResult -ne 0) {
        Write-Host "  WARN: exit=$ebResult" -ForegroundColor Red
        if (Test-Path "$env:TEMP\lingshu-eb-err.txt") {
            Get-Content "$env:TEMP\lingshu-eb-err.txt" -Tail 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        }
    } else { Write-Host "  OK" -ForegroundColor Green }
} finally { Pop-Location }

# --- Step 5: Prepare app directory ---
Write-Step 5 $TOTAL "Prepare unpacked app directory"
$unpackedDir = Join-Path $releaseDir "win-unpacked"
$unpackedExe = Join-Path $unpackedDir "LingShu.exe"

if (Test-Path -LiteralPath $unpackedExe) {
    if (Test-Path -LiteralPath $appDirOutput) {
        $resolvedAppDir = (Resolve-Path -LiteralPath $appDirOutput).Path
        $resolvedReleaseDir = (Resolve-Path -LiteralPath $releaseDir).Path
        if (-not $resolvedAppDir.StartsWith($resolvedReleaseDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host "  FAILED: refusing to clear unexpected app path $resolvedAppDir" -ForegroundColor Red
            exit 1
        }
        Remove-Item -LiteralPath $resolvedAppDir -Recurse -Force
    }
    Move-Item -LiteralPath $unpackedDir -Destination $appDirOutput -Force
    Write-Host "  App directory -> $appDirOutput" -ForegroundColor Green
} else {
    Write-Progress -Activity "LingShu Pack" -Completed
    Write-Host ""
    Write-Host "====================================================" -ForegroundColor Red
    Write-Host "  No output found. Retry manually:                  " -ForegroundColor Red
    Write-Host "    cd electron                                     " -ForegroundColor Yellow
    Write-Host "    npx electron-builder --win --x64 --dir          " -ForegroundColor Yellow
    Write-Host "====================================================" -ForegroundColor Red
    exit 1
}

# --- Step 6: Build single exe ---
Write-Step 6 $TOTAL "Build single self-extract exe"
Build-SingleExeLauncher $appDirOutput $portableExeOutput

$verifyRoot = Join-Path $releaseDir "tmp-single-exe-verify"
if (Test-Path -LiteralPath $verifyRoot) {
    $resolvedVerifyRoot = (Resolve-Path -LiteralPath $verifyRoot).Path
    $resolvedReleaseDir = (Resolve-Path -LiteralPath $releaseDir).Path
    if (-not $resolvedVerifyRoot.StartsWith($resolvedReleaseDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "  FAILED: refusing to clear unexpected verify path $resolvedVerifyRoot" -ForegroundColor Red
        exit 1
    }
    Remove-Item -LiteralPath $resolvedVerifyRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $verifyRoot -Force | Out-Null
$verifyExe = Join-Path $verifyRoot (Split-Path -Leaf $portableExeOutput)
Copy-Item -LiteralPath $portableExeOutput -Destination $verifyExe -Force

Write-Host "  Verifying first extraction path..." -ForegroundColor DarkGray
$oldExtractOnly = $env:LINGSHU_LAUNCHER_EXTRACT_ONLY
$env:LINGSHU_LAUNCHER_EXTRACT_ONLY = "1"
try {
    $verify = Start-Process -FilePath $verifyExe -WorkingDirectory $verifyRoot -Wait -PassThru -WindowStyle Hidden
    if ($verify.ExitCode -ne 0) {
        throw "Self-extract launcher verify failed with exit code $($verify.ExitCode)"
    }
} finally {
    if ($null -eq $oldExtractOnly) {
        Remove-Item Env:\LINGSHU_LAUNCHER_EXTRACT_ONLY -ErrorAction SilentlyContinue
    } else {
        $env:LINGSHU_LAUNCHER_EXTRACT_ONLY = $oldExtractOnly
    }
}
$verifyInnerExe = Get-ChildItem -LiteralPath (Join-Path $verifyRoot ".lingshu-runtime\versions") -Recurse -Filter "LingShu.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $verifyInnerExe) {
    throw "Self-extract launcher did not extract LingShu.exe under $verifyRoot"
}
Remove-Item -LiteralPath $verifyRoot -Recurse -Force

$hash = (Get-FileHash $portableExeOutput -Algorithm SHA256).Hash
$mb = [Math]::Round((Get-Item -LiteralPath $portableExeOutput).Length / 1MB, 1)
$appMb = [Math]::Round(((Get-ChildItem -LiteralPath $appDirOutput -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)

New-Item -ItemType Directory $cacheDir -Force | Out-Null
Set-Content $cacheMarker "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss') | $Version | single-exe | ${mb}MB | app=${appMb}MB | $hash" -NoNewline

Write-Progress -Activity "LingShu Pack" -Completed
Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host "  BUILD SUCCESS                                     " -ForegroundColor Green
Write-Host "  EXE    : $ProductName-$Version.exe" -ForegroundColor Green
Write-Host "  AppDir : $ProductName-$Version-app\\" -ForegroundColor DarkGray
Write-Host "  Size   : ${mb} MB" -ForegroundColor Green
Write-Host "  EXE256 : $hash" -ForegroundColor Gray
Write-Host "  Cache  : $cacheMarker" -ForegroundColor Gray
Write-Host "====================================================" -ForegroundColor Green

Remove-Item "$env:TEMP\lingshu-*.txt" -ErrorAction SilentlyContinue

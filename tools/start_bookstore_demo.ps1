param(
    [int]$ApiPort = 8787,
    [int]$WebPort = 5173,
    [int]$AdminPort = 5174,
    [string]$ApiHost = "0.0.0.0",
    [string]$WebHost = "0.0.0.0",
    [string]$AdminHost = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$WebRoot = Join-Path $Root "web"
$AdminRoot = Join-Path $Root "admin-web"

$apiOut = Join-Path $Root ".bookstore-api.out.log"
$apiErr = Join-Path $Root ".bookstore-api.err.log"
$webOut = Join-Path $Root ".bookstore-web.out.log"
$webErr = Join-Path $Root ".bookstore-web.err.log"
$adminOut = Join-Path $Root ".bookstore-admin-web.out.log"
$adminErr = Join-Path $Root ".bookstore-admin-web.err.log"

function Stop-PortListener {
    param([int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $processId = [int]$connection.OwningProcess
        if ($processId -gt 0) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
}

if ([string]::IsNullOrWhiteSpace($env:BOOKSTORE_PUBLISH_TOKEN)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    $env:BOOKSTORE_PUBLISH_TOKEN = ([Convert]::ToBase64String($bytes)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$apiArgs = @("-m", "uvicorn", "novel_app.bookstore_api:app", "--host", $ApiHost, "--port", [string]$ApiPort)
$webArgs = @("run", "dev", "--", "--host", $WebHost, "--port", [string]$WebPort)
$adminArgs = @("run", "dev", "--", "--host", $AdminHost, "--port", [string]$AdminPort)

Stop-PortListener -Port $ApiPort
Stop-PortListener -Port $WebPort
Stop-PortListener -Port $AdminPort

$api = Start-Process -FilePath "python" -ArgumentList $apiArgs -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr -PassThru
$web = Start-Process -FilePath "npm.cmd" -ArgumentList $webArgs -WorkingDirectory $WebRoot -WindowStyle Hidden -RedirectStandardOutput $webOut -RedirectStandardError $webErr -PassThru
$admin = Start-Process -FilePath "npm.cmd" -ArgumentList $adminArgs -WorkingDirectory $AdminRoot -WindowStyle Hidden -RedirectStandardOutput $adminOut -RedirectStandardError $adminErr -PassThru

Write-Host "Lingshu bookstore demo started"
Write-Host "API: http://127.0.0.1:$ApiPort (PID $($api.Id), listen $ApiHost)"
Write-Host "Web: http://127.0.0.1:$WebPort (PID $($web.Id), listen $WebHost)"
Write-Host "Admin: http://127.0.0.1:$AdminPort (PID $($admin.Id), listen $AdminHost)"
$lanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress
if ($lanIp) {
    Write-Host "LAN Web: http://$lanIp`:$WebPort"
    Write-Host "LAN Admin: http://$lanIp`:$AdminPort"
}
Write-Host "Publish token: $env:BOOKSTORE_PUBLISH_TOKEN"
Write-Host "Logs: $apiOut / $apiErr / $webOut / $webErr / $adminOut / $adminErr"

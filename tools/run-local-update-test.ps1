param(
    [string]$FeedDir = "$env:TEMP\\pylrcget-update-feed",
    [string]$ExePath = "$PSScriptRoot\\..\\dist\\pylrcget.exe",
    [int]$Port = 8765,
    [switch]$EnableUpdateDebug
)

$ErrorActionPreference = "Stop"

$feedPath = [System.IO.Path]::GetFullPath($FeedDir)
$exeFullPath = [System.IO.Path]::GetFullPath($ExePath)

if (!(Test-Path -LiteralPath $feedPath)) {
    throw "Feed directory not found. Run tools/setup-local-update-feed.ps1 first."
}
if (!(Test-Path -LiteralPath (Join-Path $feedPath "latest.json"))) {
    throw "latest.json is missing in $feedPath"
}
if (!(Test-Path -LiteralPath $exeFullPath)) {
    throw "Executable not found at: $exeFullPath"
}

$server = Start-Process -FilePath "python" -ArgumentList @("-m", "http.server", "$Port") -WorkingDirectory $feedPath -PassThru
Write-Host "Started local update server PID=$($server.Id) at http://127.0.0.1:$Port/latest.json" -ForegroundColor Green

Start-Sleep -Milliseconds 500

$env:PYLRCGET_UPDATE_LATEST_URL = "http://127.0.0.1:$Port/latest.json"
$env:PYLRCGET_UPDATE_DEBUG = $(if ($EnableUpdateDebug) { "1" } else { "0" })
Write-Host "Set PYLRCGET_UPDATE_LATEST_URL=$env:PYLRCGET_UPDATE_LATEST_URL"
Write-Host "Set PYLRCGET_UPDATE_DEBUG=$env:PYLRCGET_UPDATE_DEBUG"
Write-Host "Launching app: $exeFullPath"
Start-Process -FilePath $exeFullPath

Write-Host ""
Write-Host "When done testing, stop server with:" -ForegroundColor Yellow
Write-Host "  Stop-Process -Id $($server.Id)"

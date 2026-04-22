param(
    [string]$VersionTag = "v0.9.99",
    [string]$FeedDir = "$env:TEMP\\pylrcget-update-feed",
    [string]$ExePath = "$PSScriptRoot\\..\\dist\\pylrcget.exe",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$feedPath = [System.IO.Path]::GetFullPath($FeedDir)
$exeFullPath = [System.IO.Path]::GetFullPath($ExePath)

if (!(Test-Path -LiteralPath $exeFullPath)) {
    throw "Executable not found at: $exeFullPath"
}

New-Item -ItemType Directory -Path $feedPath -Force | Out-Null

$installerPath = Join-Path $feedPath "pylrcget-windows-installer.exe"
if (Test-Path -LiteralPath $installerPath) {
    Remove-Item -LiteralPath $installerPath -Force
}
Copy-Item -LiteralPath $exeFullPath -Destination $installerPath -Force
$installerSize = (Get-Item -LiteralPath $installerPath).Length

$latestUrl = "http://127.0.0.1:$Port/latest.json"
$assetUrl = "http://127.0.0.1:$Port/pylrcget-windows-installer.exe"
$publishedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

$payload = @{
    tag_name = $VersionTag
    name = "$VersionTag local dummy"
    html_url = $latestUrl
    body = "Local dummy update feed"
    published_at = $publishedAt
    assets = @(
        @{
            name = "pylrcget-windows-installer.exe"
            browser_download_url = $assetUrl
            size = $installerSize
            content_type = "application/octet-stream"
        }
    )
} | ConvertTo-Json -Depth 5

$latestJsonPath = Join-Path $feedPath "latest.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($latestJsonPath, $payload, $utf8NoBom)

Write-Host "Feed prepared:" -ForegroundColor Green
Write-Host "  Feed dir:      $feedPath"
Write-Host "  Asset:         $installerPath"
Write-Host "  latest.json:   $latestJsonPath"
Write-Host "  Latest URL:    $latestUrl"
Write-Host "  Asset URL:     $assetUrl"

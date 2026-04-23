param(
    [string]$VersionTag = "v99.0.0",
    [string]$FeedDir = "$env:TEMP\\pylrcget-update-feed",
    [string]$InstallerPath = "$PSScriptRoot\\..\\dist\\pylrcget-windows-installer.exe",
    [string]$ExePath = "$PSScriptRoot\\..\\dist\\pylrcget.exe",
    [int]$Port = 8765,
    [switch]$AllowDummyExe
)

$ErrorActionPreference = "Stop"

$feedPath = [System.IO.Path]::GetFullPath($FeedDir)
$installerFullPath = [System.IO.Path]::GetFullPath($InstallerPath)
$exeFullPath = [System.IO.Path]::GetFullPath($ExePath)

$sourceAssetPath = $null
$sourceMode = ""

if (Test-Path -LiteralPath $installerFullPath) {
    $sourceAssetPath = $installerFullPath
    $sourceMode = "installer"
} elseif ($AllowDummyExe) {
    if (!(Test-Path -LiteralPath $exeFullPath)) {
        throw "Executable not found at: $exeFullPath"
    }
    $sourceAssetPath = $exeFullPath
    $sourceMode = "dummy-exe"
    Write-Warning "Using app executable as dummy installer asset. Installer UI/restart behavior will not match a real installer."
} else {
    throw "Installer not found at: $installerFullPath. Build/provide a real installer or rerun with -AllowDummyExe for limited smoke tests."
}

New-Item -ItemType Directory -Path $feedPath -Force | Out-Null

$installerPath = Join-Path $feedPath "pylrcget-windows-installer.exe"
if (Test-Path -LiteralPath $installerPath) {
    Remove-Item -LiteralPath $installerPath -Force
}
Copy-Item -LiteralPath $sourceAssetPath -Destination $installerPath -Force
$installerSize = (Get-Item -LiteralPath $installerPath).Length

$latestUrl = "http://127.0.0.1:$Port/latest.json"
$assetUrl = "http://127.0.0.1:$Port/pylrcget-windows-installer.exe"
$publishedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

$payload = @{
    tag_name = $VersionTag
    name = "$VersionTag local dummy"
    html_url = $latestUrl
    body = "Local update feed ($sourceMode)"
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
Write-Host "  Source asset:  $sourceAssetPath ($sourceMode)"
Write-Host "  Asset:         $installerPath"
Write-Host "  latest.json:   $latestJsonPath"
Write-Host "  Latest URL:    $latestUrl"
Write-Host "  Asset URL:     $assetUrl"

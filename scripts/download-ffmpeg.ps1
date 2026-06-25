param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$InstallDir = (Join-Path $RepoRoot "tools\ffmpeg"),
  [string]$ReleaseTag = "autobuild-2026-06-15-15-03",
  [string]$StatusPath = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "logs\setup-status.txt")
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host "[download-ffmpeg] $Message"
}

function Append-Status([string]$Message) {
  $statusDir = Split-Path -Parent $StatusPath
  if ($statusDir) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
  Add-Content -LiteralPath $StatusPath -Value "[ffmpeg] $Message" -Encoding UTF8
}

function Ensure-Tool([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name が見つかりません。PATH を確認してください。"
  }
}

function Get-ReleaseAssetUrl {
  param(
    [Parameter(Mandatory=$true)][string]$ApiUrl
  )

  $headers = @{
    "User-Agent" = "Codex-FFmpeg-Downloader"
    "Accept" = "application/vnd.github+json"
  }
  $release = Invoke-RestMethod -Uri $ApiUrl -Headers $headers -Method Get
  $preferredNames = @(
    "ffmpeg-master-latest-win64-gpl-shared.zip",
    "ffmpeg-master-latest-win64-gpl.zip"
  )

  foreach ($name in $preferredNames) {
    $asset = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if ($asset) {
      return $asset.browser_download_url
    }
  }

  throw "GPL版のFFmpegアセットが見つかりませんでした。LGPL版は許可しません。"
}

function Find-Exe([string]$Root, [string]$Name) {
  $candidates = Get-ChildItem -LiteralPath $Root -Recurse -Filter $Name -File -ErrorAction SilentlyContinue
  return $candidates | Select-Object -First 1
}

Ensure-Tool Invoke-WebRequest
Ensure-Tool Expand-Archive

$existingFfmpeg = Find-Exe -Root $InstallDir -Name "ffmpeg.exe"
$existingFfprobe = Find-Exe -Root $InstallDir -Name "ffprobe.exe"
if ($existingFfmpeg -and $existingFfprobe) {
  Write-Step "skip existing install: ffmpeg.exe and ffprobe.exe already present"
  Append-Status "install: skipped (already present)"
  return
}

  $headers = @{
  "User-Agent" = "Codex-FFmpeg-Downloader"
  "Accept" = "application/vnd.github+json"
}
$releaseApi = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/$ReleaseTag"
$release = Invoke-RestMethod -Uri $releaseApi -Headers $headers -Method Get
$downloadUrl = Get-ReleaseAssetUrl -ApiUrl $releaseApi
$selectedAsset = $release.assets | Where-Object { $_.browser_download_url -eq $downloadUrl } | Select-Object -First 1
$tempDir = Join-Path $env:TEMP ("ffmpeg-download-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
try {
  $zipPath = Join-Path $tempDir "ffmpeg.zip"
  Write-Step "download $downloadUrl"
  Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing

  if (-not $selectedAsset -or -not $selectedAsset.digest) {
    throw "FFmpeg release asset の digest が取得できません。検証なし配布は許可しません。"
  }
  if ($selectedAsset.digest -notmatch '^sha256:(?<sha>[A-Fa-f0-9]+)$') {
    throw "FFmpeg release asset の digest 形式が不正です: $($selectedAsset.digest)"
  }
  $expected = $Matches.sha.ToLowerInvariant()
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
  if ($expected -ne $actual) {
    throw "FFmpeg ZIP の SHA-256 が一致しません。expected=$expected actual=$actual"
  }
  Write-Step "sha256 verified"

  if (Test-Path -LiteralPath $InstallDir) {
    Write-Step "remove existing install"
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

  Write-Step "extract"
  Expand-Archive -LiteralPath $zipPath -DestinationPath $tempDir -Force

  $top = Get-ChildItem -LiteralPath $tempDir -Directory | Where-Object { $_.Name -like "ffmpeg*" } | Select-Object -First 1
  if (-not $top) {
    throw "展開後のフォルダが見つかりませんでした。"
  }

  Copy-Item -LiteralPath (Join-Path $top.FullName "*") -Destination $InstallDir -Recurse -Force
  $ffmpegExe = Find-Exe -Root $InstallDir -Name "ffmpeg.exe"
  $ffprobeExe = Find-Exe -Root $InstallDir -Name "ffprobe.exe"
  if (-not $ffmpegExe -or -not $ffprobeExe) {
    throw "FFmpeg / FFprobe のインストール確認に失敗しました。"
  }
  Append-Status "install: completed ($ReleaseTag)"
  Append-Status "verification: passed"
  Write-Step "done -> $InstallDir"
}
finally {
  Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

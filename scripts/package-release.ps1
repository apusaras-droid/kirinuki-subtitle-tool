param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\release"),
  [switch]$IncludeModels,
  [string]$SourceOfferUrl = "<fill in the release source URL or archive URL>",
  [string]$SourceOfferChecksum = "<fill in the checksum>"
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  $here = Resolve-Path -LiteralPath $PSScriptRoot
  return (Resolve-Path -LiteralPath (Join-Path $here "..")).Path
}

function Copy-SelectedPaths {
  param(
    [string]$SourceRoot,
    [string]$DestinationRoot,
    [string[]]$RelativePaths
  )

  New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
  foreach ($relative in $RelativePaths) {
    $source = Join-Path $SourceRoot $relative
    if (-not (Test-Path -LiteralPath $source)) { continue }

    $target = Join-Path $DestinationRoot $relative
    $targetParent = Split-Path -Parent $target
    if ($targetParent) {
      New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    }

    if (Test-Path -LiteralPath $source -PathType Container) {
      Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    }
    else {
      Copy-Item -LiteralPath $source -Destination $target -Force
    }
  }
}

function Get-GitCommit {
  try {
    $commit = git rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $commit) { return ($commit | Select-Object -First 1).Trim() }
  } catch {}
  return "<unknown>"
}

function Write-TextFile {
  param([string]$Path, [string]$Content)
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
  Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
}

function Remove-GeneratedArtifacts {
  param([string]$Root)
  Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
  Get-ChildItem -LiteralPath $Root -Recurse -Force -File -Filter "*.pyc" | Remove-Item -Force
}

$repoRoot = Resolve-RepoRoot
$releaseRoot = Resolve-Path -LiteralPath (New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$appRoot = Join-Path $releaseRoot "app"
$sourceRoot = Join-Path $releaseRoot "source"
$licensesRoot = Join-Path $releaseRoot "licenses"
$buildInfoRoot = Join-Path $licensesRoot "build-info"

Remove-Item -LiteralPath $releaseRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $appRoot, $sourceRoot, $licensesRoot, $buildInfoRoot | Out-Null

$sourceItems = @(
  "backend",
  "frontend",
  "docs",
  "licenses",
  "scripts",
  "README.md",
  "LICENSE",
  "requirements.txt",
  ".gitignore"
)

$appItems = @(
  "backend",
  "frontend",
  "tools\whisper.cpp\bin",
  "docs",
  "licenses",
  "scripts",
  "README.md",
  "LICENSE",
  "requirements.txt",
  ".gitignore"
)

Copy-SelectedPaths -SourceRoot $repoRoot -DestinationRoot $sourceRoot -RelativePaths $sourceItems
Copy-SelectedPaths -SourceRoot $repoRoot -DestinationRoot $appRoot -RelativePaths $appItems

if ($IncludeModels) {
  Copy-SelectedPaths -SourceRoot $repoRoot -DestinationRoot $appRoot -RelativePaths @("tools\whisper.cpp\models")
}

Remove-GeneratedArtifacts -Root $sourceRoot
Remove-GeneratedArtifacts -Root $appRoot

foreach ($name in @("GPL-3.0-or-later.txt", "third_party_notices.txt", "source-offer.txt", "README.md")) {
  Copy-Item -LiteralPath (Join-Path $repoRoot "licenses\$name") -Destination (Join-Path $licensesRoot $name) -Force -ErrorAction SilentlyContinue
}
foreach ($name in @("FFmpeg-notice.txt", "MIT-whisper.cpp.txt")) {
  if (Test-Path (Join-Path $repoRoot "licenses\$name")) {
    Copy-Item -LiteralPath (Join-Path $repoRoot "licenses\$name") -Destination (Join-Path $licensesRoot $name) -Force
  }
}

$commit = Get-GitCommit
$environment = @"
OS: $([System.Environment]::OSVersion.VersionString)
PowerShell: $($PSVersionTable.PSVersion)
Python: $(python --version 2>&1)
FFmpeg: $(ffmpeg -version | Select-Object -First 1)
FFprobe: $(ffprobe -version | Select-Object -First 1)
whisper.cpp: bundled in tools/whisper.cpp
"@

Write-TextFile -Path (Join-Path $buildInfoRoot "commit.txt") -Content $commit
Write-TextFile -Path (Join-Path $buildInfoRoot "environment.txt") -Content $environment
Write-TextFile -Path (Join-Path $buildInfoRoot "dependency-lock.txt") -Content (Get-Content -LiteralPath (Join-Path $repoRoot "requirements.txt") -Raw)
Write-TextFile -Path (Join-Path $licensesRoot "source-offer.txt") -Content @"
Source location: $SourceOfferUrl
Source archive checksum: $SourceOfferChecksum
Release tag / commit: $commit
"@

$sourceArchive = Join-Path $releaseRoot "source.zip"
if (Test-Path $sourceArchive) { Remove-Item -LiteralPath $sourceArchive -Force }
Compress-Archive -Path (Join-Path $sourceRoot '*') -DestinationPath $sourceArchive -Force
$hash = Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256
Write-TextFile -Path (Join-Path $buildInfoRoot "source.zip.sha256") -Content "$($hash.Hash)  $([IO.Path]::GetFileName($sourceArchive))"

Write-Host "Release package created at $releaseRoot"
Write-Host "Source archive: $sourceArchive"
if ($IncludeModels) {
  Write-Host "Models were included because -IncludeModels was specified."
} else {
  Write-Host "Models were excluded by default. Re-run with -IncludeModels if redistribution is permitted."
}

param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\release"),
  [switch]$IncludeModels,
  [string]$SourceOfferUrl = "",
  [string]$SourceOfferChecksum = ""
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

function Assert-RequiredPaths {
  param([string]$Root, [string[]]$RelativePaths)

  $missing = @($RelativePaths | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Root $_)) })
  if ($missing.Count -gt 0) {
    throw "Release package is missing required paths: $($missing -join ', ')"
  }
}

function Get-CommandVersionLine {
  param([string]$Command, [string[]]$Arguments)

  try {
    $resolved = Get-Command $Command -ErrorAction Stop
    return (& $resolved.Source @Arguments 2>&1 | Select-Object -First 1)
  }
  catch {
    return "<not found>"
  }
}

function Remove-GeneratedArtifacts {
  param([string]$Root)
  Get-ChildItem -LiteralPath $Root -Recurse -Force -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
  Get-ChildItem -LiteralPath $Root -Recurse -Force -File -Filter "*.pyc" | Remove-Item -Force
}

$repoRoot = Resolve-RepoRoot
$requiredPaths = @(
  "LICENSE",
  "README.md",
  "ACKNOWLEDGEMENTS.md",
  "THIRD_PARTY_NOTICES.md",
  "SECURITY.md",
  "requirements.txt",
  "requirements-core.txt",
  "requirements-standard.txt",
  "requirements-full.txt",
  "requirements-dev.txt",
  "setup.bat",
  "launch.bat",
  "download-runtime.bat",
  "download-ffmpeg.bat",
  "tools\whisper.cpp\bin\whisper-cli.exe",
  "licenses\MIT-whisper.cpp.txt",
  "backend",
  "frontend",
  "scripts"
)
Assert-RequiredPaths -Root $repoRoot -RelativePaths $requiredPaths

if ((Get-Item -LiteralPath (Join-Path $repoRoot "LICENSE")).Length -lt 30000) {
  throw "LICENSE does not appear to contain the full GPLv3 license text."
}
if ($SourceOfferUrl -match '<fill in|YOUR_|example\.com' -or $SourceOfferChecksum -match '<fill in|YOUR_|example') {
  throw "Source offer contains a placeholder value."
}

$releaseRoot = Resolve-Path -LiteralPath (New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$appRoot = Join-Path $releaseRoot "app"
$sourceRoot = Join-Path $releaseRoot "source"
$licensesRoot = Join-Path $releaseRoot "licenses"
$buildInfoRoot = Join-Path $licensesRoot "build-info"
$appBuildInfoRoot = Join-Path $appRoot "licenses\build-info"
$sourceBuildInfoRoot = Join-Path $sourceRoot "licenses\build-info"

Remove-Item -LiteralPath $releaseRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $appRoot, $sourceRoot, $licensesRoot, $buildInfoRoot | Out-Null

$sourceItems = @(
  "backend",
  "frontend",
  "docs",
  "licenses",
  "scripts",
  "tests",
  "README.md",
  "ACKNOWLEDGEMENTS.md",
  "THIRD_PARTY_NOTICES.md",
  "SECURITY.md",
  "LICENSE",
  "requirements.txt",
  "requirements-core.txt",
  "requirements-standard.txt",
  "requirements-full.txt",
  "requirements-dev.txt",
  "setup.bat",
  "launch.bat",
  "download-runtime.bat",
  "download-ffmpeg.bat",
  "download-japanese-fonts.bat",
  "process-video.bat",
  "process-video-cpu-autocut.bat",
  "process-video-cpu-nocut.bat",
  "process-video-gpu-nocut.bat",
  "preflight-release.bat",
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
  "ACKNOWLEDGEMENTS.md",
  "THIRD_PARTY_NOTICES.md",
  "SECURITY.md",
  "LICENSE",
  "requirements.txt",
  "requirements-core.txt",
  "requirements-standard.txt",
  "requirements-full.txt",
  "requirements-dev.txt",
  "setup.bat",
  "launch.bat",
  "download-runtime.bat",
  "download-ffmpeg.bat",
  "download-japanese-fonts.bat",
  "process-video.bat",
  "process-video-cpu-autocut.bat",
  "process-video-cpu-nocut.bat",
  "process-video-gpu-nocut.bat",
  "preflight-release.bat",
  ".gitignore"
)

Copy-SelectedPaths -SourceRoot $repoRoot -DestinationRoot $sourceRoot -RelativePaths $sourceItems
Copy-SelectedPaths -SourceRoot $repoRoot -DestinationRoot $appRoot -RelativePaths $appItems
New-Item -ItemType Directory -Force -Path $appBuildInfoRoot, $sourceBuildInfoRoot | Out-Null

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
FFmpeg: $(Get-CommandVersionLine -Command "ffmpeg" -Arguments @("-version"))
FFprobe: $(Get-CommandVersionLine -Command "ffprobe" -Arguments @("-version"))
whisper.cpp: bundled in tools/whisper.cpp
"@

$dependencyLock = @"
# requirements.txt
$(Get-Content -LiteralPath (Join-Path $repoRoot "requirements.txt") -Raw)

# requirements-core.txt
$(Get-Content -LiteralPath (Join-Path $repoRoot "requirements-core.txt") -Raw)

# requirements-standard.txt
$(Get-Content -LiteralPath (Join-Path $repoRoot "requirements-standard.txt") -Raw)

# requirements-full.txt
$(Get-Content -LiteralPath (Join-Path $repoRoot "requirements-full.txt") -Raw)

# requirements-dev.txt
$(Get-Content -LiteralPath (Join-Path $repoRoot "requirements-dev.txt") -Raw)
"@
$whisperBin = Join-Path $repoRoot "tools\whisper.cpp\bin"
$whisperHashes = @(Get-ChildItem -LiteralPath $whisperBin -File | Sort-Object Name | ForEach-Object {
    $fileHash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    "$($fileHash.Hash)  $($_.Name)"
  }) -join "`r`n"
foreach ($targetBuildInfoRoot in @($buildInfoRoot, $appBuildInfoRoot, $sourceBuildInfoRoot)) {
  Write-TextFile -Path (Join-Path $targetBuildInfoRoot "commit.txt") -Content $commit
  Write-TextFile -Path (Join-Path $targetBuildInfoRoot "environment.txt") -Content $environment
  Write-TextFile -Path (Join-Path $targetBuildInfoRoot "dependency-lock.txt") -Content $dependencyLock
  Write-TextFile -Path (Join-Path $targetBuildInfoRoot "whisper-cpp-files.sha256") -Content $whisperHashes
}

$sourceArchive = Join-Path $releaseRoot "source.zip"
if (Test-Path $sourceArchive) { Remove-Item -LiteralPath $sourceArchive -Force }
Compress-Archive -Path (Join-Path $sourceRoot '*') -DestinationPath $sourceArchive -Force
$hash = Get-FileHash -LiteralPath $sourceArchive -Algorithm SHA256
Write-TextFile -Path (Join-Path $buildInfoRoot "source.zip.sha256") -Content "$($hash.Hash)  $([IO.Path]::GetFileName($sourceArchive))"

$resolvedSourceUrl = if ($SourceOfferUrl) { $SourceOfferUrl } else { "Bundled alongside the application package as source.zip" }
$resolvedSourceChecksum = if ($SourceOfferChecksum) { $SourceOfferChecksum } else { $hash.Hash }
$sourceOffer = @"
Corresponding source: $resolvedSourceUrl
Source archive SHA-256: $resolvedSourceChecksum
Release tag / commit: $commit
"@
Write-TextFile -Path (Join-Path $licensesRoot "source-offer.txt") -Content $sourceOffer
Write-TextFile -Path (Join-Path $appRoot "licenses\source-offer.txt") -Content $sourceOffer

$appArchive = Join-Path $releaseRoot "app.zip"
if (Test-Path $appArchive) { Remove-Item -LiteralPath $appArchive -Force }
Compress-Archive -Path (Join-Path $appRoot '*') -DestinationPath $appArchive -Force
$appHash = Get-FileHash -LiteralPath $appArchive -Algorithm SHA256
Write-TextFile -Path (Join-Path $buildInfoRoot "app.zip.sha256") -Content "$($appHash.Hash)  $([IO.Path]::GetFileName($appArchive))"

Write-TextFile -Path (Join-Path $releaseRoot "SHA256SUMS.txt") -Content @"
$($hash.Hash)  source.zip
$($appHash.Hash)  app.zip
"@

Write-Host "Release package created at $releaseRoot"
Write-Host "Source archive: $sourceArchive"
Write-Host "Application archive: $appArchive"
if ($IncludeModels) {
  Write-Host "Models were included because -IncludeModels was specified."
} else {
  Write-Host "Models were excluded by default. Re-run with -IncludeModels if redistribution is permitted."
}

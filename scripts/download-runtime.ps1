param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$PythonExe = "python",
  [ValidateSet("minimal", "standard", "full", "models")]
  [string]$Profile = "standard",
  [string[]]$Models = @("large-v3", "silero-v6.2.0"),
  [switch]$SkipPip,
  [string]$StatusPath = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "logs\setup-status.txt")
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host "[download-runtime] $Message"
}

function Append-Status([string]$Message) {
  $statusDir = Split-Path -Parent $StatusPath
  if ($statusDir) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
  Add-Content -LiteralPath $StatusPath -Value "[runtime] $Message" -Encoding UTF8
}

function Ensure-Tool([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name was not found. Check PATH."
  }
}

function Assert-FileHash([string]$Path, [string]$ExpectedSha256) {
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Hash verification target was not found: $Path"
  }
  $stream = [System.IO.File]::OpenRead($Path)
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    $hashBytes = $sha256.ComputeHash($stream)
    $actual = ([System.BitConverter]::ToString($hashBytes)).Replace("-", "")
  } finally {
    $sha256.Dispose()
    $stream.Dispose()
  }
  $expected = $ExpectedSha256.ToUpperInvariant()
  if ($actual -ne $expected) {
    throw "SHA-256 verification failed for $(Split-Path -Leaf $Path). Expected $expected but received $actual. Delete the file and retry only after confirming the download source."
  }
}

function Invoke-VerifiedDownload([string]$Url, [string]$Destination, [string]$Sha256) {
  $destParent = Split-Path -Parent $Destination
  if ($destParent) { New-Item -ItemType Directory -Force -Path $destParent | Out-Null }
  if (Test-Path -LiteralPath $Destination) {
    Write-Step "verify existing $(Split-Path -Leaf $Destination)"
    Assert-FileHash -Path $Destination -ExpectedSha256 $Sha256
    return
  }
  $temporary = "$Destination.download"
  Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  try {
    Write-Step "download $(Split-Path -Leaf $Destination)"
    Invoke-WebRequest -Uri $Url -OutFile $temporary -UseBasicParsing
    Assert-FileHash -Path $temporary -ExpectedSha256 $Sha256
    Move-Item -LiteralPath $temporary -Destination $Destination
  } finally {
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
  }
}

function Test-PythonPackage([string]$ImportName) {
  $code = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ImportName') else 1)"
  & $PythonExe -c $code | Out-Null
  return $LASTEXITCODE -eq 0
}

function Assert-PythonPackage([string]$ImportName, [string]$DisplayName) {
  if (-not (Test-PythonPackage $ImportName)) {
    throw "$DisplayName installation verification failed."
  }
}

if ($PythonExe -eq "python") {
  Ensure-Tool python
} elseif (-not (Test-Path -LiteralPath $PythonExe)) {
  throw "Python executable was not found: $PythonExe"
}

$corePackages = @(
  @{ Import = "fastapi"; Display = "fastapi" },
  @{ Import = "uvicorn"; Display = "uvicorn" },
  @{ Import = "multipart"; Display = "python-multipart" },
  @{ Import = "pydantic"; Display = "pydantic" }
)
$standardPackages = $corePackages + @(
  @{ Import = "google.genai"; Display = "google-genai" }
)
$fullPackages = $standardPackages + @(
  @{ Import = "faster_whisper"; Display = "faster-whisper" },
  @{ Import = "whisperx"; Display = "whisperx" },
  @{ Import = "demucs"; Display = "demucs" },
  @{ Import = "speechbrain"; Display = "speechbrain" },
  @{ Import = "silero_vad"; Display = "silero-vad" }
)

$profileInfo = @{
  "minimal" = @{ Requirements = "requirements-core.txt"; Packages = $corePackages; DownloadModels = $false }
  "standard" = @{ Requirements = "requirements-standard.txt"; Packages = $standardPackages; DownloadModels = $true }
  "full" = @{ Requirements = "requirements-full.txt"; Packages = $fullPackages; DownloadModels = $true }
  "models" = @{ Requirements = $null; Packages = @(); DownloadModels = $true }
}
$selectedProfile = $profileInfo[$Profile]
$requiredPackages = @($selectedProfile.Packages)
Write-Step "profile=$Profile"
Append-Status "profile: $Profile"

if (-not $SkipPip -and $selectedProfile.Requirements) {
  $missing = @()
  foreach ($pkg in $requiredPackages) {
    if (-not (Test-PythonPackage $pkg.Import)) {
      $missing += $pkg.Display
    }
  }
  if ($missing.Count -gt 0) {
    Write-Step "install python dependencies: missing $($missing -join ', ')"
    Append-Status "pip install: missing $($missing -join ', ')"
    & $PythonExe -m pip install -r (Join-Path $RepoRoot $selectedProfile.Requirements)
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  } else {
    Write-Step "skip pip install: python dependencies already present"
    Append-Status "pip install: skipped (already present)"
  }
} elseif ($SkipPip) {
  Write-Step "skip pip install: requested"
  Append-Status "pip install: skipped (requested)"
}

$modelDir = Join-Path $RepoRoot "tools\whisper.cpp\models"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

$whisperModelMap = @{
  "base" = @{
    Url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
    Sha256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
  }
  "small" = @{
    Url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
    Sha256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
  }
  "medium" = @{
    Url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
    Sha256 = "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208"
  }
  "large-v3" = @{
    Url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
    Sha256 = "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"
  }
  "silero-v6.2.0" = @{
    Url = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin"
    Sha256 = "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
  }
}

if ($selectedProfile.DownloadModels) {
  foreach ($model in $Models) {
    $name = $model.Trim()
    if (-not $name) { continue }
    if (-not $whisperModelMap.ContainsKey($name)) {
      throw "Unsupported model: $name"
    }
    $filename = if ($name -eq "silero-v6.2.0") { "ggml-silero-v6.2.0.bin" } else { "ggml-$name.bin" }
    $destination = Join-Path $modelDir $filename
    $before = Test-Path -LiteralPath $destination
    $modelInfo = $whisperModelMap[$name]
    Invoke-VerifiedDownload -Url $modelInfo.Url -Destination $destination -Sha256 $modelInfo.Sha256
    if ($before) {
      Append-Status "model ${name}: verified (already present)"
    } else {
      Append-Status "model ${name}: downloaded and verified"
    }
  }
} else {
  Write-Step "skip models for minimal profile"
  Append-Status "models: skipped (minimal profile)"
}

foreach ($pkg in $requiredPackages) {
  Assert-PythonPackage $pkg.Import $pkg.Display
}

Append-Status "verification: passed"

Write-Step "done"

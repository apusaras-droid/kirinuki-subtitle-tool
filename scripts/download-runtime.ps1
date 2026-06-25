param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string[]]$Models = @("large-v3", "silero-v5.1.2"),
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
    throw "$Name が見つかりません。PATH を確認してください。"
  }
}

function Invoke-Download([string]$Url, [string]$Destination) {
  $destParent = Split-Path -Parent $Destination
  if ($destParent) { New-Item -ItemType Directory -Force -Path $destParent | Out-Null }
  if (Test-Path -LiteralPath $Destination) {
    Write-Step "skip existing $(Split-Path -Leaf $Destination)"
    return
  }
  Write-Step "download $(Split-Path -Leaf $Destination)"
  Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

function Test-PythonPackage([string]$ImportName) {
  $code = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ImportName') else 1)"
  & python -c $code | Out-Null
  return $LASTEXITCODE -eq 0
}

function Assert-PythonPackage([string]$ImportName, [string]$DisplayName) {
  if (-not (Test-PythonPackage $ImportName)) {
    throw "$DisplayName のインストール確認に失敗しました。"
  }
}

Ensure-Tool python

if (-not $SkipPip) {
  $requiredPackages = @(
    @{ Import = "fastapi"; Display = "fastapi" },
    @{ Import = "uvicorn"; Display = "uvicorn" },
    @{ Import = "whisperx"; Display = "whisperx" },
    @{ Import = "faster_whisper"; Display = "faster-whisper" },
    @{ Import = "demucs"; Display = "demucs" },
    @{ Import = "speechbrain"; Display = "speechbrain" }
  )
  $missing = @()
  foreach ($pkg in $requiredPackages) {
    if (-not (Test-PythonPackage $pkg.Import)) {
      $missing += $pkg.Display
    }
  }
  if ($missing.Count -gt 0) {
    Write-Step "install python dependencies: missing $($missing -join ', ')"
    Append-Status "pip install: missing $($missing -join ', ')"
    & python -m pip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
  } else {
    Write-Step "skip pip install: python dependencies already present"
    Append-Status "pip install: skipped (already present)"
  }
}

$modelDir = Join-Path $RepoRoot "tools\whisper.cpp\models"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

$whisperModelMap = @{
  "base" = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
  "small" = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
  "medium" = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
  "large-v3" = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"
  "silero-v5.1.2" = "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
}

foreach ($model in $Models) {
  $name = $model.Trim()
  if (-not $name) { continue }
  if (-not $whisperModelMap.ContainsKey($name)) {
    throw "未対応のモデルです: $name"
  }
  $filename = if ($name -eq "silero-v5.1.2") { "ggml-silero-v5.1.2.bin" } else { "ggml-$name.bin" }
  $destination = Join-Path $modelDir $filename
  $before = Test-Path -LiteralPath $destination
  Invoke-Download -Url $whisperModelMap[$name] -Destination $destination
  if ($before) {
    Append-Status "model $name: skipped (already present)"
  } else {
    Append-Status "model $name: downloaded"
  }
}

Assert-PythonPackage "fastapi" "fastapi"
Assert-PythonPackage "uvicorn" "uvicorn"
Assert-PythonPackage "whisperx" "whisperx"
Assert-PythonPackage "faster_whisper" "faster-whisper"
Assert-PythonPackage "demucs" "demucs"
Assert-PythonPackage "speechbrain" "speechbrain"

Append-Status "verification: passed"

Write-Step "done"

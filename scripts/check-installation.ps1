param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Write-Result([string]$Name, [bool]$Present, [string]$Detail = "") {
  $status = if ($Present) { "OK" } else { "MISSING" }
  $suffix = if ($Detail) { " - $Detail" } else { "" }
  Write-Host ("[{0}] {1}{2}" -f $status, $Name, $suffix)
}

function Test-PythonImport([string]$PythonExe, [string]$ImportName) {
  if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
  $code = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ImportName') else 1)"
  & $PythonExe -c $code 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

$pythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$hasVenv = Test-Path -LiteralPath $pythonExe
Write-Host "Installation status"
Write-Host "Repository: $RepoRoot"
Write-Result ".venv Python" $hasVenv

$groups = @(
  @{ Name = "Core web application"; Imports = @("fastapi", "uvicorn", "multipart", "pydantic") },
  @{ Name = "Gemini integration"; Imports = @("google.genai") },
  @{ Name = "Heavy Python AI features"; Imports = @("faster_whisper", "whisperx", "demucs", "speechbrain", "silero_vad") }
)
foreach ($group in $groups) {
  $missing = @($group.Imports | Where-Object { -not (Test-PythonImport $pythonExe $_) })
  Write-Result $group.Name ($missing.Count -eq 0) $(if ($missing.Count) { "missing: $($missing -join ', ')" } else { "" })
}

$whisperExe = Join-Path $RepoRoot "tools\whisper.cpp\bin\whisper-cli.exe"
$largeModel = Join-Path $RepoRoot "tools\whisper.cpp\models\ggml-large-v3.bin"
$vadModel = Join-Path $RepoRoot "tools\whisper.cpp\models\ggml-silero-v6.2.0.bin"
Write-Result "whisper.cpp executable" (Test-Path -LiteralPath $whisperExe)
Write-Result "Whisper large-v3 model" (Test-Path -LiteralPath $largeModel)
Write-Result "Silero VAD model" (Test-Path -LiteralPath $vadModel)

$localFfmpeg = Get-ChildItem -LiteralPath (Join-Path $RepoRoot "tools\ffmpeg") -Filter "ffmpeg.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$pathFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
Write-Result "FFmpeg" ([bool]($localFfmpeg -or $pathFfmpeg)) $(if ($localFfmpeg) { $localFfmpeg.FullName } elseif ($pathFfmpeg) { $pathFfmpeg.Source } else { "" })

$fontNames = @(
  "NotoSansJP-Variable.ttf",
  "MPLUSRounded1c-Regular.ttf",
  "MPLUSRounded1c-ExtraBold.ttf",
  "DelaGothicOne-Regular.ttf",
  "BIZUDPGothic-Regular.ttf",
  "BIZUDPGothic-Bold.ttf",
  "ZenKakuGothicNew-Regular.ttf",
  "ZenKakuGothicNew-Bold.ttf",
  "ZenMaruGothic-Regular.ttf",
  "ZenMaruGothic-Bold.ttf",
  "ZenOldMincho-Regular.ttf",
  "ZenOldMincho-Bold.ttf"
)
$fontRoot = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$installedFonts = @($fontNames | Where-Object { Test-Path -LiteralPath (Join-Path $fontRoot $_) })
Write-Result "Bundled Japanese font set" ($installedFonts.Count -eq $fontNames.Count) "$($installedFonts.Count)/$($fontNames.Count) installed"

Write-Host ""
Write-Host "Profiles:"
Write-Host "  minimal  = Core web application + FFmpeg"
Write-Host "  standard = minimal + Gemini + local Whisper/VAD models + Japanese fonts"
Write-Host "  full     = standard + heavy Python AI features"

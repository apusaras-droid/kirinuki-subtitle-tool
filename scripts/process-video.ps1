param(
  [string[]]$VideoPath = @(),
  [string]$PresetName = "gpu_autocut",
  [string]$PresetPath = (Join-Path $PSScriptRoot "process-video.presets.json"),
  [string]$OutFolderName = "SRT",
  [string]$ComputeProfile = "gpu",
  [string]$Engine = "whisper.cpp",
  [string]$Model = "large-v3",
  [string]$OutputTag = "",
  [string]$DetectionMode = "vad",
  [switch]$NoAutoCut,
  [double]$StartSec = 0,
  [double]$EndSec = 0
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
$pythonExe = if ($env:CUTSUBTITLE_PYTHON -and (Test-Path -LiteralPath $env:CUTSUBTITLE_PYTHON)) {
  (Resolve-Path -LiteralPath $env:CUTSUBTITLE_PYTHON).Path
} elseif (Test-Path -LiteralPath $venvPython) {
  (Resolve-Path -LiteralPath $venvPython).Path
} else {
  (Get-Command python -ErrorAction Stop).Source
}

if (-not $VideoPath -or $VideoPath.Count -eq 0) {
  $VideoPath = @($args | Where-Object { $_ -and -not ($_ -is [System.Management.Automation.SwitchParameter]) })
}

if (-not $VideoPath -or $VideoPath.Count -eq 0) {
  throw "No video file was provided."
}

function Read-Preset {
  param([string]$Path, [string]$Name)
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Preset file not found: $Path"
  }
  $all = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $all.PSObject.Properties.Name -contains $Name) {
    throw "Preset not found: $Name"
  }
  return $all.$Name
}

function Get-PresetValue {
  param(
    $Preset,
    [string]$Key,
    $Fallback
  )
  if ($null -ne $Preset -and $Preset.PSObject.Properties.Name -contains $Key) {
    $value = $Preset.$Key
    if ($null -ne $value -and "$value" -ne "") {
      return $value
    }
  }
  return $Fallback
}

function Get-VideoDuration {
  param([string]$Path)
  $result = & ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $Path
  if ($LASTEXITCODE -ne 0 -or -not $result) {
    throw "ffprobe failed to read duration: $Path"
  }
  return [double]::Parse(($result | Select-Object -First 1).Trim(), [System.Globalization.CultureInfo]::InvariantCulture)
}

function Get-SafeFileName {
  param([string]$Name)
  $safe = $Name -replace '[\\/:*?"<>|\[\]]', '_'
  if ([string]::IsNullOrWhiteSpace($safe)) {
    return 'output'
  }
  return $safe
}

function Invoke-ProcessOne {
  param([string]$InputPath)

  $preset = Read-Preset -Path $PresetPath -Name $PresetName

  $resolved = (Resolve-Path -LiteralPath $InputPath).Path
  $source = Get-Item -LiteralPath $resolved
  $baseName = [System.IO.Path]::GetFileNameWithoutExtension($source.Name)
  $safeBaseName = Get-SafeFileName -Name $baseName
  $safeOutputTag = Get-SafeFileName -Name $OutputTag
  $outputStem = if ([string]::IsNullOrWhiteSpace($safeOutputTag)) { $safeBaseName } else { "$safeBaseName.$safeOutputTag" }
  $parent = $source.DirectoryName
  $outDir = Join-Path $parent $OutFolderName
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null

  $duration = Get-VideoDuration -Path $resolved
  if ($EndSec -gt 0 -and $EndSec -gt $StartSec) {
    $clipStart = $StartSec
    $clipEnd = $EndSec
  } else {
    $clipStart = 0
    $clipEnd = $duration
  }
  if ($clipEnd -le $clipStart) {
    throw "Invalid clip range: $clipStart - $clipEnd"
  }
  if ($duration -le 0) {
    throw "Failed to read video duration: $resolved"
  }

  $reportPath = Join-Path $outDir ($outputStem + '.report.json')
  $logPath = Join-Path $outDir ($outputStem + '.run.log')
  $editPlanPath = Join-Path $outDir ($outputStem + '.edit_plan.json')
  $cliArgs = @(
    '-m', 'backend',
    'run-pipeline',
    '--video', $resolved,
    '--name', $baseName,
    '--start', ('{0:F3}' -f $clipStart),
    '--end', ('{0:F3}' -f $clipEnd),
    '--compute-profile', (Get-PresetValue -Preset $preset -Key 'compute_profile' -Fallback $ComputeProfile),
    '--engine', (Get-PresetValue -Preset $preset -Key 'engine' -Fallback $Engine),
    '--model', (Get-PresetValue -Preset $preset -Key 'model' -Fallback $Model),
    '--detection-mode', (Get-PresetValue -Preset $preset -Key 'detection_mode' -Fallback $DetectionMode),
    '--report', $reportPath
  )
  $presetAutoCut = $true
  if ($preset.PSObject.Properties.Name -contains 'auto_cut') {
    $presetAutoCut = [bool](Get-PresetValue -Preset $preset -Key 'auto_cut' -Fallback $true)
  }
  $effectiveAutoCut = if ($NoAutoCut.IsPresent) { $false } else { $presetAutoCut }
  if ($effectiveAutoCut) {
    $cliArgs += @('--auto-cut')
  } else {
    $cliArgs += @('--no-auto-cut')
  }

  Write-Host ("[processor] running pipeline: " + $resolved)
  $previousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & $pythonExe @cliArgs *> $logPath
  $exitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorActionPreference

  if (Test-Path -LiteralPath $logPath) {
    Write-Host "[processor] tail log:"
    Get-Content -LiteralPath $logPath -Tail 20 | ForEach-Object { Write-Host $_ }
  }
  if ($exitCode -ne 0) {
    throw "run-pipeline failed for: $resolved"
  }

  $reportJson = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8
  $report = $reportJson | ConvertFrom-Json
  $projectId = [string]$report.project.project_id
  $workspaceRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')
  $projectDir = Join-Path $workspaceRoot "projects\$projectId"
  $finalMp4 = Join-Path $projectDir 'output\final.mp4'
  $finalSrt = Join-Path $projectDir 'output\final.srt'
  $copiedMp4 = Join-Path $outDir ($outputStem + '.mp4')
  $copiedSrt = Join-Path $outDir ($outputStem + '.srt')

  Copy-Item -LiteralPath $finalMp4 -Destination $copiedMp4 -Force
  Copy-Item -LiteralPath $finalSrt -Destination $copiedSrt -Force

  $summary = [pscustomobject]@{
    input = $resolved
    project_id = $projectId
    duration_sec = $duration
    out_dir = $outDir
    video = $copiedMp4
    subtitles = $copiedSrt
    report = $reportPath
    output_tag = $safeOutputTag
    preset = $PresetName
    auto_cut = $effectiveAutoCut
  }
  $summaryPath = Join-Path $outDir ($outputStem + '.summary.json')
  $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

  $cleanupTargets = @($reportPath, $summaryPath, $logPath, $editPlanPath)
  foreach ($target in $cleanupTargets) {
    if (Test-Path -LiteralPath $target) {
      Remove-Item -LiteralPath $target -Force
    }
  }

  Write-Host ("Processed: " + $resolved)
  Write-Host ("Saved video: " + $copiedMp4)
  Write-Host ("Saved subtitles: " + $copiedSrt)
  Write-Host ("Cleaned up auxiliary files in: " + $outDir)
}

foreach ($item in $VideoPath) {
  if (-not (Test-Path -LiteralPath $item)) {
    throw "Video file not found: $item"
  }
  Invoke-ProcessOne -InputPath $item
}

param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\logs\smoke-test"),
  [string]$ReportPath,
  [string]$ProjectName = "smoke_project",
  [string]$Language = "en",
  [string]$Model = "large-v3",
  [string]$Engine = "whisper.cpp",
  [string]$SpeechText = "This is a smoke test for the subtitle clipping pipeline.",
  [string]$ServerUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

function New-Check {
  param(
    [string]$Id,
    [string]$Label,
    $Pass,
    [string]$Detail = ""
  )
  [pscustomobject]@{
    id = $Id
    label = $Label
    pass = [bool]$Pass
    detail = $Detail
  }
}

function Invoke-CommandLogged {
  param(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$LogPath
  )
  $stdoutPath = [System.IO.Path]::GetTempFileName()
  $stderrPath = [System.IO.Path]::GetTempFileName()
  try {
    $proc = Start-Process -FilePath $FilePath -ArgumentList $Arguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $stdout = if (Test-Path -LiteralPath $stdoutPath) { Get-Content -LiteralPath $stdoutPath -Raw } else { "" }
    $stderr = if (Test-Path -LiteralPath $stderrPath) { Get-Content -LiteralPath $stderrPath -Raw } else { "" }
    Set-Content -LiteralPath $LogPath -Value ("COMMAND`n{0} {1}`n`nSTDOUT`n{2}`n`nSTDERR`n{3}" -f $FilePath, ($Arguments -join " "), $stdout, $stderr) -Encoding UTF8
    $output = $stdout + $stderr
  } finally {
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
  }
  return @{
    exit_code = $proc.ExitCode
    output = $output
  }
}

function New-SpeechWave {
  param(
    [string]$Path,
    [string]$Text
  )
  Add-Type -AssemblyName System.Speech
  $synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
  try {
    $synth.Rate = 0
    $synth.SetOutputToWaveFile($Path)
    $synth.Speak($Text)
  } finally {
    $synth.Dispose()
  }
}

function Test-PathExists {
  param([string]$Path)
  return (Test-Path -LiteralPath $Path)
}

function Test-Server {
  param([string]$Url)
  try {
    $res = Invoke-WebRequest -UseBasicParsing "$Url/" -TimeoutSec 5
    return $res.StatusCode -eq 200
  } catch {
    return $false
  }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$workDir = Join-Path $OutputDir "work"
$projectNameSafe = ($ProjectName -replace '[^A-Za-z0-9_-]+', '_').Trim('_')
if (-not $projectNameSafe) { $projectNameSafe = "smoke_project" }
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

$checks = New-Object System.Collections.Generic.List[object]
$checks.Add((New-Check "server.root" "Local server responds" (Test-Server -Url $ServerUrl) $ServerUrl))
$checks.Add((New-Check "tool.ffmpeg" "ffmpeg exists" ([bool](Get-Command ffmpeg -ErrorAction SilentlyContinue))))
$checks.Add((New-Check "tool.ffprobe" "ffprobe exists" ([bool](Get-Command ffprobe -ErrorAction SilentlyContinue))))
$checks.Add((New-Check "tool.python" "python exists" ([bool](Get-Command python -ErrorAction SilentlyContinue))))

$speechRaw = Join-Path $workDir "speech_raw.wav"
$speech16 = Join-Path $workDir "speech_16k.wav"
$silenceA = Join-Path $workDir "silence_a.wav"
$silenceB = Join-Path $workDir "silence_b.wav"
$speechMix = Join-Path $workDir "speech_mix.wav"
$videoPath = Join-Path $workDir "smoke_input.mp4"
$configPath = Join-Path $workDir "smoke_config.json"
$pipelineReportPath = Join-Path $OutputDir "pipeline-report.json"
$pipelineLogPath = Join-Path $OutputDir "pipeline.log"
$smokeJsonPath = if ($ReportPath) { $ReportPath } else { Join-Path $OutputDir "smoke-report.json" }

try {
  New-SpeechWave -Path $speechRaw -Text $SpeechText
  $checks.Add((New-Check "tts.generated" "Synthetic speech generated" (Test-PathExists $speechRaw) $speechRaw))

  $ffmpegLogs = Join-Path $OutputDir "ffmpeg.log"
  $normalize = Invoke-CommandLogged -FilePath "ffmpeg" -Arguments @("-y", "-i", $speechRaw, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", $speech16) -LogPath $ffmpegLogs
  if ($normalize.exit_code -ne 0) { throw "Failed to normalize speech audio" }
  $checks.Add((New-Check "audio.normalized" "Speech normalized to 16 kHz mono" (Test-PathExists $speech16) $speech16))

  $mixLog = Join-Path $OutputDir "audio-mix.log"
  $mix = Invoke-CommandLogged -FilePath "ffmpeg" -Arguments @(
    "-y",
    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=0.6",
    "-i", $speech16,
    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=0.6",
    "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[outa]",
    "-map", "[outa]",
    "-c:a", "pcm_s16le",
    $speechMix
  ) -LogPath $mixLog
  if ($mix.exit_code -ne 0) { throw "Failed to build speech mix" }
  $checks.Add((New-Check "audio.mixed" "Speech mix generated" (Test-PathExists $speechMix) $speechMix))

  $videoLog = Join-Path $OutputDir "video-create.log"
  $video = Invoke-CommandLogged -FilePath "ffmpeg" -Arguments @(
    "-y",
    "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=6",
    "-i", $speechMix,
    "-shortest",
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    $videoPath
  ) -LogPath $videoLog
  if ($video.exit_code -ne 0) { throw "Failed to build smoke video" }
  $checks.Add((New-Check "video.generated" "Smoke video generated" (Test-PathExists $videoPath) $videoPath))

  $config = [pscustomobject]@{
    video = $videoPath
    name = $projectNameSafe
    start = 0.0
    end = 6.0
    language = $Language
    model = $Model
    engine = $Engine
    silence_threshold_db = -35.0
    threshold_db = -35.0
    min_silence_duration = 0.3
    burn_subtitles = $false
    subtitles = @(
      [pscustomobject]@{
        source_start_sec = 1.0
        source_end_sec = 4.2
        text = $SpeechText
      }
    )
    settings_json = '{"pre_speech_padding":0.2,"post_speech_padding":0.2,"merge_gap_duration":0.1}'
    report = $pipelineReportPath
  }
  $config | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configPath -Encoding UTF8
  $checks.Add((New-Check "config.written" "Pipeline config written" (Test-PathExists $configPath) $configPath))

  $pipeline = Invoke-CommandLogged -FilePath "python" -Arguments @("-m", "backend", "run-pipeline", "--config", $configPath, "--report", $pipelineReportPath) -LogPath $pipelineLogPath
  $pipelineOk = $pipeline.exit_code -eq 0
  $checks.Add((New-Check "pipeline.exit" "run-pipeline completed" $pipelineOk $pipelineLogPath))
  if (-not $pipelineOk) {
    throw "Pipeline failed"
  }

  $pipelineData = $null
  if (Test-Path -LiteralPath $pipelineReportPath) {
    $pipelineData = Get-Content -LiteralPath $pipelineReportPath -Raw | ConvertFrom-Json
  }
  $checks.Add((New-Check "pipeline.report" "Pipeline report written" ([bool]$pipelineData) $pipelineReportPath))

  if ($pipelineData) {
    $projectId = $pipelineData.project.project_id
    $projectDir = Join-Path (Join-Path $PSScriptRoot "..") "projects\$projectId"
    $projectJson = Join-Path $projectDir "project.json"
    $editPlanJson = Join-Path $projectDir "edit_plan.json"
    $finalVideo = Join-Path $projectDir "output\final.mp4"
    $finalSrt = Join-Path $projectDir "output\final.srt"
    $auditGlobal = Join-Path (Join-Path $PSScriptRoot "..") "logs\app_audit.jsonl"
    $auditProject = Join-Path $projectDir "temp\logs\audit.jsonl"

    $checks.Add((New-Check "project.json" "project.json exists" (Test-PathExists $projectJson) $projectJson))
    $checks.Add((New-Check "edit_plan.json" "edit_plan.json exists" (Test-PathExists $editPlanJson) $editPlanJson))
    $checks.Add((New-Check "final.mp4" "Final video exists" (Test-PathExists $finalVideo) $finalVideo))
    $checks.Add((New-Check "final.srt" "Final subtitles exist" (Test-PathExists $finalSrt) $finalSrt))
    $checks.Add((New-Check "audit.global" "Global audit log exists" (Test-PathExists $auditGlobal) $auditGlobal))
    $checks.Add((New-Check "audit.project" "Project audit log exists" (Test-PathExists $auditProject) $auditProject))

    if (Test-Path -LiteralPath $projectJson) {
      $projectData = Get-Content -LiteralPath $projectJson -Raw | ConvertFrom-Json
      $projectRelative = ($projectData.source_video -notmatch '^[A-Za-z]:\\') -and ($projectData.source_video -notmatch '^/')
      $checks.Add((New-Check "project.relative" "Project JSON stores relative source path" $projectRelative $projectData.source_video))
    }
    if (Test-Path -LiteralPath $editPlanJson) {
      $planData = Get-Content -LiteralPath $editPlanJson -Raw | ConvertFrom-Json
      $planRelative = ($planData.source_video -notmatch '^[A-Za-z]:\\') -and ($planData.source_video -notmatch '^/')
      $checks.Add((New-Check "plan.relative" "Edit plan stores relative source path" $planRelative $planData.source_video))
    }
  }
}
catch {
  $checks.Add((New-Check "pipeline.error" "Smoke pipeline threw an exception" $false $_.Exception.Message))
}

$summary = [pscustomobject]@{
  timestamp = (Get-Date).ToString("o")
  total = $checks.Count
  passed = ($checks | Where-Object { $_.pass }).Count
  failed = ($checks | Where-Object { -not $_.pass }).Count
  checks = $checks
}

$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $smokeJsonPath -Encoding UTF8

$checks | ForEach-Object {
  $status = if ($_.pass) { "PASS" } else { "FAIL" }
  Write-Host "[$status] $($_.label)"
}
Write-Host "Report: $smokeJsonPath"
exit ([int]($summary.failed -gt 0))

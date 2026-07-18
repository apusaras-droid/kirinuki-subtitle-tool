param(
  [string]$ReportPath = (Join-Path $PSScriptRoot "..\logs\spec-verify-report.json"),
  [string]$ProjectId,
  [string]$ServerUrl = "http://127.0.0.1:8000",
  [bool]$RunSmokeTest = $true,
  [string]$SmokeReportPath = (Join-Path $PSScriptRoot "..\logs\smoke-test\smoke-report.json")
)

$ErrorActionPreference = "Stop"

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

function Test-PathExists {
  param([string]$Path)
  return (Test-Path -LiteralPath $Path)
}

function Get-FileText {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return Get-Content -LiteralPath $Path -Raw
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

function Test-CommandOk {
  param([scriptblock]$Script)
  try {
    & $Script *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

$checks = New-Object System.Collections.Generic.List[object]

$checks.Add((New-Check "docs.flowchart" "Flowchart exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\flowchart.md"))))
$checks.Add((New-Check "docs.checklist" "Spec checklist exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\spec-checklist.md"))))
$checks.Add((New-Check "docs.gpl" "GPL distribution spec exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\gpl-distribution-spec.md"))))
$checks.Add((New-Check "docs.index" "Documentation index exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\README.md"))))
$checks.Add((New-Check "docs.workflow" "Workflow contract exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\工程分割UI適用方針.md"))))
$checks.Add((New-Check "docs.cli" "CLI integration contract exists" (Test-PathExists (Join-Path $PSScriptRoot "..\docs\外部CLI連携.md"))))
$checks.Add((New-Check "cli.entry" "CLI entry exists" (Test-PathExists (Join-Path $PSScriptRoot "..\backend\__main__.py"))))
$checks.Add((New-Check "cli.script" "CLI implementation exists" (Test-PathExists (Join-Path $PSScriptRoot "..\backend\app\cli.py"))))
$checks.Add((New-Check "audit.global" "Global audit logger exists" (Test-PathExists (Join-Path $PSScriptRoot "..\backend\app\audit.py"))))
$checks.Add((New-Check "audit.logs" "Audit log directory exists" (Test-PathExists (Join-Path $PSScriptRoot "..\logs"))))
$checks.Add((New-Check "release.script" "Release script exists" (Test-PathExists (Join-Path $PSScriptRoot "..\scripts\make-release.ps1"))))
$checks.Add((New-Check "release.package" "Release packaging script exists" (Test-PathExists (Join-Path $PSScriptRoot "..\scripts\package-release.ps1"))))
$checks.Add((New-Check "smoke.script" "CLI smoke test script exists" (Test-PathExists (Join-Path $PSScriptRoot "..\scripts\smoke-test.ps1"))))
$checks.Add((New-Check "license.root" "LICENSE exists" (Test-PathExists (Join-Path $PSScriptRoot "..\LICENSE"))))
$checks.Add((New-Check "license.thirdparty" "Third-party notices exist" (Test-PathExists (Join-Path $PSScriptRoot "..\licenses\third_party_notices.txt"))))
$checks.Add((New-Check "license.whisper" "whisper.cpp notice exists" (Test-PathExists (Join-Path $PSScriptRoot "..\licenses\MIT-whisper.cpp.txt"))))
$checks.Add((New-Check "license.ffmpeg" "FFmpeg notice exists" (Test-PathExists (Join-Path $PSScriptRoot "..\licenses\FFmpeg-notice.txt"))))
$checks.Add((New-Check "whisper.cpp.exe" "whisper.cpp executable exists" (Test-PathExists (Join-Path $PSScriptRoot "..\tools\whisper.cpp\bin\whisper-cli.exe"))))
$checks.Add((New-Check "whisper.cpp.model" "default whisper.cpp small model exists" (Test-PathExists (Join-Path $PSScriptRoot "..\tools\whisper.cpp\models\ggml-small.bin"))))
$checks.Add((New-Check "cli.help" "CLI help works" (Test-CommandOk { python -m backend --help }) "Run python -m backend --help"))
$checks.Add((New-Check "server.root" "Local API/GUI responds" (Test-Server -Url $ServerUrl) $ServerUrl))

$cliText = Get-FileText (Join-Path $PSScriptRoot "..\backend\app\cli.py")
if ($cliText) {
  $checks.Add((New-Check "cli.run-pipeline" "run-pipeline exists" ($cliText -match 'run-pipeline')))
  $checks.Add((New-Check "cli.config" "run-pipeline --config exists" ($cliText -match '--config')))
  $checks.Add((New-Check "cli.report" "run-pipeline --report exists" ($cliText -match '--report')))
}

$mainText = Get-FileText (Join-Path $PSScriptRoot "..\backend\app\main.py")
if ($mainText) {
  $checks.Add((New-Check "api.audit" "API audit middleware exists" ($mainText -match '@app.middleware\("http"\)')))
}

if ($RunSmokeTest) {
  $smokeScript = Join-Path $PSScriptRoot "smoke-test.ps1"
  $smokeOk = Test-CommandOk { & $smokeScript -OutputDir (Split-Path -Parent $SmokeReportPath) -ReportPath $SmokeReportPath }
  $checks.Add((New-Check "cli.smoke" "CLI smoke test" $smokeOk $SmokeReportPath))
}

if ($ProjectId) {
  $projectPath = Join-Path (Join-Path $PSScriptRoot "..\projects") $ProjectId
  $projectJson = Join-Path $projectPath "project.json"
  $editPlanJson = Join-Path $projectPath "edit_plan.json"
  $projectOk = $false
  $editPlanOk = $false
  $relativeOk = $false
  if (Test-Path -LiteralPath $projectJson) {
    $projectData = Get-Content -LiteralPath $projectJson -Raw | ConvertFrom-Json
    $projectOk = $true
    $relativeOk = ($projectData.source_video -notmatch '^[A-Za-z]:\\') -and ($projectData.source_video -notmatch '^/')
  }
  if (Test-Path -LiteralPath $editPlanJson) {
    $planData = Get-Content -LiteralPath $editPlanJson -Raw | ConvertFrom-Json
    $editPlanOk = $true
    $relativeOk = $relativeOk -and (($planData.source_video -notmatch '^[A-Za-z]:\\') -and ($planData.source_video -notmatch '^/'))
  }
  $checks.Add((New-Check "project.json" "project.json exists" $projectOk $projectJson))
  $checks.Add((New-Check "edit_plan.json" "edit_plan.json exists" $editPlanOk $editPlanJson))
  $checks.Add((New-Check "relative.paths" "Relative path storage" $relativeOk))
}

$summary = [pscustomobject]@{
  timestamp = (Get-Date).ToString("o")
  total = $checks.Count
  passed = ($checks | Where-Object { $_.pass }).Count
  failed = ($checks | Where-Object { -not $_.pass }).Count
  checks = $checks
}

$reportDir = Split-Path -Parent $ReportPath
if ($reportDir) { New-Item -ItemType Directory -Force -Path $reportDir | Out-Null }
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

$summary.checks | ForEach-Object {
  $status = if ($_.pass) { "PASS" } else { "FAIL" }
  Write-Host "[$status] $($_.label)"
}
Write-Host "Report: $ReportPath"
exit ([int]($summary.failed -gt 0))

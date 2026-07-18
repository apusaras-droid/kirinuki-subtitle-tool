param(
  [switch]$AllowDirty,
  [switch]$RequireRemote,
  [switch]$RunTests,
  [switch]$BuildPackage,
  [string]$ReportPath = (Join-Path $PSScriptRoot "..\release\preflight-report.json")
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}

function Add-Check {
  param(
    [System.Collections.Generic.List[object]]$Checks,
    [string]$Id,
    [string]$Label,
    [bool]$Pass,
    [string]$Detail = ""
  )

  $Checks.Add([pscustomobject]@{
      id = $Id
      label = $Label
      pass = $Pass
      detail = $Detail
    })
}

function Invoke-CheckedCommand {
  param([scriptblock]$Command, [string]$Label)

  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

function Test-PowerShellSyntax {
  param([string]$Path)

  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
  return @($errors).Count -eq 0
}

function Find-HistorySensitiveData {
  param([string]$Pattern)

  $hits = New-Object System.Collections.Generic.List[string]
  foreach ($commit in @(git rev-list --all)) {
    $matches = @(git grep -I -n -E $Pattern $commit 2>$null)
    foreach ($match in $matches) {
      $hits.Add($match)
      if ($hits.Count -ge 20) { return $hits }
    }
  }
  return $hits
}

$repoRoot = Resolve-RepoRoot
Set-Location $repoRoot
$checks = New-Object System.Collections.Generic.List[object]
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }

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
  "tests",
  "docs\gpl-distribution-spec.md",
  "scripts\package-release.ps1"
)

foreach ($relative in $requiredPaths) {
  Add-Check $checks "required.$relative" "Required path: $relative" (Test-Path -LiteralPath (Join-Path $repoRoot $relative))
}

$licensePath = Join-Path $repoRoot "LICENSE"
$licenseText = if (Test-Path -LiteralPath $licensePath) { Get-Content -LiteralPath $licensePath -Raw } else { "" }
Add-Check $checks "license.full" "LICENSE contains full GPLv3 text" ($licenseText.Length -gt 30000 -and $licenseText -match 'GNU GENERAL PUBLIC LICENSE' -and $licenseText -match 'Version 3, 29 June 2007')
Add-Check $checks "license.copy" "licenses copy matches LICENSE" ((Test-Path -LiteralPath (Join-Path $repoRoot "licenses\GPL-3.0-or-later.txt")) -and ((Get-FileHash $licensePath).Hash -eq (Get-FileHash (Join-Path $repoRoot "licenses\GPL-3.0-or-later.txt")).Hash))

$status = @(git status --porcelain)
Add-Check $checks "git.clean" "Git working tree is clean or explicitly allowed" ($AllowDirty -or $status.Count -eq 0) (($status | Select-Object -First 20) -join "`n")

$branch = (git branch --show-current).Trim()
Add-Check $checks "git.branch" "Current branch is named" ([bool]$branch) $branch

$remotes = @(git remote -v)
$remotePass = if ($RequireRemote) { @($remotes | Where-Object { $_ -match '^origin\s+https://github\.com/' }).Count -gt 0 } else { $true }
Add-Check $checks "git.remote" "GitHub origin is configured when required" $remotePass (($remotes | Select-Object -First 10) -join "`n")

$tracked = @(git ls-files)
$forbiddenPattern = '(^|/)(projects|logs|temp|data/private|data/settings)/|\.(mp4|mkv|mov|webm|wav|bin|exe|dll|zip|7z)$|(^|/)\.env($|\.)'
$forbidden = @($tracked | Where-Object { $_ -match $forbiddenPattern })
Add-Check $checks "git.forbidden" "No private, media, model, executable, or archive files are tracked" ($forbidden.Count -eq 0) (($forbidden | Select-Object -First 30) -join "`n")

$historyPattern = 'gh[opsu]_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|C:\\Users\\keymi'
$historyHits = @(Find-HistorySensitiveData -Pattern $historyPattern)
Add-Check $checks "git.history-secrets" "No known token or personal-path patterns exist in Git history" ($historyHits.Count -eq 0) (($historyHits | Select-Object -First 20) -join "`n")

$largeObjects = @(foreach ($entry in @(git rev-list --objects --all)) {
    $parts = $entry.Split(' ', 2)
    $objectId = $parts[0]
    $objectType = (git cat-file -t $objectId 2>$null)
    if ($objectType -ne 'blob') { continue }
    $objectSize = [int64](git cat-file -s $objectId)
    if ($objectSize -gt 10MB) {
      "$objectId $objectSize $($parts[1])"
    }
  })
Add-Check $checks "git.large-objects" "No Git blob exceeds 10 MiB" ($largeObjects.Count -eq 0) (($largeObjects | Select-Object -First 20) -join "`n")

foreach ($scriptFile in @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "scripts") -Filter "*.ps1" | Sort-Object Name)) {
  $script = "scripts\$($scriptFile.Name)"
  Add-Check $checks "syntax.$script" "PowerShell syntax: $script" (Test-PowerShellSyntax (Join-Path $repoRoot $script))
}

$packageText = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\package-release.ps1") -Raw
Add-Check $checks "package.entrypoints" "Package script includes setup and launch entrypoints" ($packageText -match 'setup\.bat' -and $packageText -match 'launch\.bat')
Add-Check $checks "package.archives" "Package script creates app.zip and source.zip" ($packageText -match 'app\.zip' -and $packageText -match 'source\.zip')

$setupText = Get-Content -LiteralPath (Join-Path $repoRoot "setup.bat") -Raw
$setupProfilesPresent = $setupText -match 'install_minimal' -and $setupText -match 'install_standard' -and $setupText -match 'install_full' -and $setupText -match 'check-installation\.ps1'
Add-Check $checks "setup.profiles" "Setup menu exposes minimal, standard, full, and status paths" $setupProfilesPresent

$requirementsText = Get-Content -LiteralPath (Join-Path $repoRoot "requirements.txt") -Raw
$standardRequirementsText = Get-Content -LiteralPath (Join-Path $repoRoot "requirements-standard.txt") -Raw
$fullRequirementsText = Get-Content -LiteralPath (Join-Path $repoRoot "requirements-full.txt") -Raw
$requirementsLayered = $requirementsText -match 'requirements-full\.txt' -and $standardRequirementsText -match 'requirements-core\.txt' -and $fullRequirementsText -match 'requirements-standard\.txt'
Add-Check $checks "requirements.profiles" "Python requirements are layered by setup profile" $requirementsLayered

$runtimeDownloadText = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\download-runtime.ps1") -Raw
$requiredModelHashes = @(
  "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
  "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
  "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
  "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2",
  "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
)
$missingModelHashes = @($requiredModelHashes | Where-Object { $runtimeDownloadText -notmatch [regex]::Escape($_) })
Add-Check $checks "downloads.model-hashes" "Runtime model downloads require pinned SHA-256" ($missingModelHashes.Count -eq 0) (($missingModelHashes) -join "`n")

if ($RunTests) {
  try {
    Invoke-CheckedCommand { & $pythonExe -m compileall -q backend } "Python compileall"
    Add-Check $checks "tests.compileall" "Python compileall" $true

    $testFiles = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "tests") -Filter "test_*.py" | Sort-Object Name)
    foreach ($testFile in $testFiles) {
      Invoke-CheckedCommand { & $pythonExe -m pytest -q $testFile.FullName } "pytest $($testFile.Name)"
    }
    Add-Check $checks "tests.pytest" "Python tests by file" $true "$($testFiles.Count) files"

    Invoke-CheckedCommand { node --check frontend/app.js } "frontend/app.js syntax"
    Invoke-CheckedCommand { node --check frontend/workflow-state.js } "frontend/workflow-state.js syntax"
    Invoke-CheckedCommand { node --test tests/workflow-state.test.cjs } "Node workflow tests"
    & (Join-Path $repoRoot "tests\check-frontend.ps1")
    Add-Check $checks "tests.frontend" "Frontend syntax, state, and DOM contract" $true

    Invoke-CheckedCommand { & $pythonExe -m pip check } "pip check"
    Add-Check $checks "tests.dependencies" "Python dependency check" $true
  }
  catch {
    Add-Check $checks "tests.failure" "Release test suite" $false $_.Exception.Message
  }
}

if ($BuildPackage) {
  try {
    & (Join-Path $repoRoot "scripts\package-release.ps1")
    $releaseRoot = Join-Path $repoRoot "release"
    $sourceArchive = Join-Path $releaseRoot "source.zip"
    $appArchive = Join-Path $releaseRoot "app.zip"
    Add-Check $checks "package.source" "source.zip was created" (Test-Path -LiteralPath $sourceArchive)
    Add-Check $checks "package.app" "app.zip was created" (Test-Path -LiteralPath $appArchive)

    if (Test-Path -LiteralPath $appArchive) {
      $archiveEntries = @(tar.exe -tf $appArchive)
      $badEntries = @($archiveEntries | Where-Object { $_ -match '(^|/)(projects|logs|temp|data/private|data/settings|\.git)(/|$)|\.(mp4|mkv|mov|webm|wav|bin)$' })
      Add-Check $checks "package.contents" "Application archive excludes private and generated files" ($badEntries.Count -eq 0) (($badEntries | Select-Object -First 20) -join "`n")

      $requiredArchiveEntries = @(
        "LICENSE",
        "README.md",
        "ACKNOWLEDGEMENTS.md",
        "THIRD_PARTY_NOTICES.md",
        "SECURITY.md",
        "setup.bat",
        "requirements-core.txt",
        "requirements-standard.txt",
        "requirements-full.txt",
        "launch.bat",
        "download-runtime.bat",
        "download-ffmpeg.bat",
        "scripts/check-installation.ps1",
        "licenses/source-offer.txt",
        "licenses/MIT-whisper.cpp.txt",
        "licenses/build-info/whisper-cpp-files.sha256",
        "tools/whisper.cpp/bin/whisper-cli.exe"
      )
      $missingArchiveEntries = @($requiredArchiveEntries | Where-Object { $archiveEntries -notcontains $_ })
      Add-Check $checks "package.required" "Application archive includes required entrypoints and notices" ($missingArchiveEntries.Count -eq 0) (($missingArchiveEntries | Select-Object -First 20) -join "`n")
    }
  }
  catch {
    Add-Check $checks "package.failure" "Release package build" $false $_.Exception.Message
  }
}

$failed = @($checks | Where-Object { -not $_.pass })
$report = [ordered]@{
  generated_at = (Get-Date).ToString("o")
  repository = $repoRoot
  branch = $branch
  commit = (git rev-parse HEAD).Trim()
  passed = $failed.Count -eq 0
  total = $checks.Count
  failed = $failed.Count
  checks = $checks
}

$reportDirectory = Split-Path -Parent $ReportPath
if ($reportDirectory) { New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null }
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8

foreach ($check in $checks) {
  $statusLabel = if ($check.pass) { "PASS" } else { "FAIL" }
  Write-Host "[$statusLabel] $($check.label)"
  if (-not $check.pass -and $check.detail) { Write-Host $check.detail }
}
Write-Host "Report: $ReportPath"

if ($failed.Count -gt 0) { exit 1 }

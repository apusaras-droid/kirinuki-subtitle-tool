param(
  [string]$HostName = '127.0.0.1',
  [int]$Port = 8000,
  [string]$LogDir = (Join-Path $PSScriptRoot '..\logs'),
  [switch]$NoBrowser,
  [switch]$Hidden
)

$ErrorActionPreference = 'Stop'

function Test-PortOpen {
  param(
    [string]$HostName,
    [int]$Port
  )
  try {
    $client = [System.Net.Sockets.TcpClient]::new()
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne(200)) {
      $client.Close()
      return $false
    }
    $client.EndConnect($iar)
    $client.Close()
    return $true
  } catch {
    return $false
  }
}

function Get-LocalBuildId {
  param([string]$Root)
  $files = @(
    'backend/app/main.py',
    'backend/app/services.py',
    'backend/app/edit_plan.py',
    'backend/app/srt.py',
    'backend/app/cli.py',
    'frontend/app.js',
    'frontend/index.html',
    'frontend/styles.css'
  )
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    foreach ($relative in $files) {
      $path = Join-Path $Root $relative
      if (-not (Test-Path -LiteralPath $path)) { continue }
      $relBytes = [System.Text.Encoding]::UTF8.GetBytes($relative)
      $sha.TransformBlock($relBytes, 0, $relBytes.Length, $null, 0) | Out-Null
      $sha.TransformBlock([byte[]](0), 0, 1, $null, 0) | Out-Null
      $bytes = [System.IO.File]::ReadAllBytes($path)
      $sha.TransformBlock($bytes, 0, $bytes.Length, $null, 0) | Out-Null
      $sha.TransformBlock([byte[]](0), 0, 1, $null, 0) | Out-Null
    }
    [void]$sha.TransformFinalBlock([byte[]]::new(0), 0, 0)
    return ([BitConverter]::ToString($sha.Hash)).Replace('-', '').ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Get-ServerVersion {
  param(
    [string]$HostName,
    [int]$Port
  )
  try {
    $uri = 'http://' + $HostName + ':' + $Port + '/api/version'
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $uri
    $payload = $response.Content | ConvertFrom-Json
    return [pscustomobject]@{
      app_version = [string]$payload.app_version
      build_id = [string]$payload.build_id
    }
  } catch {
    return $null
  }
}

function Stop-ProcessOnPort {
  param(
    [string]$HostName,
    [int]$Port
  )
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($null -eq $connection) { return $false }
  try {
    Stop-Process -Id $connection.OwningProcess -Force -ErrorAction Stop
    return $true
  } catch {
    return $false
  }
}

function Find-FreePort {
  param(
    [string]$HostName,
    [int]$StartPort,
    [int]$MaxAttempts = 20
  )
  for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
    $candidate = $StartPort + $offset
    if (-not (Test-PortOpen -HostName $HostName -Port $candidate)) {
      return $candidate
    }
  }
  return $null
}

function Open-Browser {
  param(
    [string]$Url
  )
  try {
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $Url
    $psi.UseShellExecute = $true
    [void][System.Diagnostics.Process]::Start($psi)
    return $true
  } catch {
    try {
      Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', 'start', '', $Url) | Out-Null
      return $true
    } catch {
      try {
        Start-Process -FilePath 'rundll32.exe' -ArgumentList @('url.dll,FileProtocolHandler', $Url) | Out-Null
        return $true
      } catch {
        try {
          Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile', '-Command', "Start-Process '$Url'") | Out-Null
          return $true
        } catch {
          return $false
        }
      }
    }
  }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$python = (Get-Command python).Source
$localVersion = Get-LocalBuildId -Root $root
$selectedPort = $Port
$logFile = Join-Path $LogDir ('server-{0}.log' -f $selectedPort)

Set-Location $root

if (Test-PortOpen -HostName $HostName -Port $selectedPort) {
  $serverVersion = Get-ServerVersion -HostName $HostName -Port $selectedPort
  if ($null -eq $serverVersion -or $serverVersion.build_id -ne $localVersion) {
    Stop-ProcessOnPort -HostName $HostName -Port $selectedPort | Out-Null
    $deadline = (Get-Date).AddSeconds(15)
    while (Test-PortOpen -HostName $HostName -Port $selectedPort) {
      if ((Get-Date) -gt $deadline) {
        $fallbackPort = Find-FreePort -HostName $HostName -StartPort ($selectedPort + 1)
        if ($null -eq $fallbackPort) {
          throw ('Old server could not be stopped and no fallback port was free.')
        }
        $selectedPort = [int]$fallbackPort
        break
      }
      Start-Sleep -Milliseconds 250
    }
  }
}

if (-not (Test-PortOpen -HostName $HostName -Port $selectedPort)) {
  $childScript = Join-Path $LogDir ('launch-child-{0}.cmd' -f $selectedPort)
  @(
    '@echo off'
    'set "ROOT=%~dp0.."'
    'cd /d "%ROOT%"'
    ('"' + $python + '" -m uvicorn backend.app.main:app --host ' + $HostName + ' --port ' + $selectedPort + ' >> "%~dp0server-' + $selectedPort + '.log" 2>&1')
  ) | Set-Content -LiteralPath $childScript -Encoding ASCII

  $startParams = @{
    FilePath = 'cmd.exe'
    ArgumentList = @('/c', $childScript)
    WorkingDirectory = $root
  }
  if ($Hidden) {
    $startParams.WindowStyle = 'Hidden'
  }
  Start-Process @startParams | Out-Null

  $deadline = (Get-Date).AddSeconds(90)
  while (-not (Test-PortOpen -HostName $HostName -Port $selectedPort)) {
    if ((Get-Date) -gt $deadline) {
      throw ('Server did not become ready in time. Check {0}' -f $logFile)
    }
    Start-Sleep -Milliseconds 500
  }
}

if (-not $NoBrowser) {
  $browserOpened = Open-Browser -Url ('http://' + $HostName + ':' + $selectedPort)
  if (-not $browserOpened) {
    Write-Warning ('Browser could not be opened. Check {0}' -f $logFile)
    if (-not $Hidden) {
      Read-Host 'Press Enter to close this window' | Out-Null
    }
  }
}

if ($selectedPort -ne $Port) {
  Write-Warning ('Port {0} was busy, using {1} instead.' -f $Port, $selectedPort)
}
Write-Host ('Started or connected: http://' + $HostName + ':' + $selectedPort)

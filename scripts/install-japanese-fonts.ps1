param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
  [string]$StatusPath = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "logs\setup-status.txt"),
  [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot.Trim().Trim('"'))

$GoogleFontsCommit = "389b770410cc0b7c21c85673bfa2077420fe7f65"
$RawRoot = "https://raw.githubusercontent.com/google/fonts/$GoogleFontsCommit/ofl"
$UserFontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
$RegistryPath = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
$LicenseDir = Join-Path $RepoRoot "licenses\fonts"
$DownloadDir = Join-Path $env:TEMP "kirinuki-subtitle-fonts"

$Fonts = @(
  @{ Family = "Noto Sans JP"; Style = "Variable"; Folder = "notosansjp"; File = "NotoSansJP-Variable.ttf"; SourceFile = "NotoSansJP[wght].ttf"; Sha256 = "C2F3B4D463500A2DDCD3849CDED1FCEEB9FD6D1C32E6CBECD568453BA50FC68F" },
  @{ Family = "M PLUS Rounded 1c"; Style = "Regular"; Folder = "mplusrounded1c"; File = "MPLUSRounded1c-Regular.ttf"; Sha256 = "B75708B53E45B06D17D470AEECA5B766E3D1B3999F03F13EC4EB863CA846C14C" },
  @{ Family = "M PLUS Rounded 1c"; Style = "ExtraBold"; Folder = "mplusrounded1c"; File = "MPLUSRounded1c-ExtraBold.ttf"; Sha256 = "8E7C15901DCA87F1451B356DDA594F7D092BA252A5DCC47DA74523A242493C36" },
  @{ Family = "Dela Gothic One"; Style = "Regular"; Folder = "delagothicone"; File = "DelaGothicOne-Regular.ttf"; Sha256 = "4FF87A0965F1B0505E5A2C58424BC6AD3CFF27E56A82F21C2FC9D6B0E3857EE2" },
  @{ Family = "BIZ UDPGothic"; Style = "Regular"; Folder = "bizudpgothic"; File = "BIZUDPGothic-Regular.ttf"; Sha256 = "258D7156C165F2FF774B6EFEE637C22C3B950DE0D8A10E501137061BC8085D01" },
  @{ Family = "BIZ UDPGothic"; Style = "Bold"; Folder = "bizudpgothic"; File = "BIZUDPGothic-Bold.ttf"; Sha256 = "30EBA52FC837E8B62C97D4B82E6706583149FB7294E3712DD71A655EAEA80A90" },
  @{ Family = "Zen Kaku Gothic New"; Style = "Regular"; Folder = "zenkakugothicnew"; File = "ZenKakuGothicNew-Regular.ttf"; Sha256 = "B840CD07A67D89CACCA44249AE49AA99EE7640EB5CE623BE8D8983D6AABAC801" },
  @{ Family = "Zen Kaku Gothic New"; Style = "Bold"; Folder = "zenkakugothicnew"; File = "ZenKakuGothicNew-Bold.ttf"; Sha256 = "0081CEDABC4921982FCD061F845A005664AC7FB642AF2DD34B4007BC63CCD235" },
  @{ Family = "Zen Maru Gothic"; Style = "Regular"; Folder = "zenmarugothic"; File = "ZenMaruGothic-Regular.ttf"; Sha256 = "A0C0B53543E0993AE2225E629C833F3D51495AD31720694FF112CE4CE11111EF" },
  @{ Family = "Zen Maru Gothic"; Style = "Bold"; Folder = "zenmarugothic"; File = "ZenMaruGothic-Bold.ttf"; Sha256 = "FE24426B9C8B5523A0146A8235C8674ECCF0493AF354A53EC895C3596D9EB745" },
  @{ Family = "Zen Old Mincho"; Style = "Regular"; Folder = "zenoldmincho"; File = "ZenOldMincho-Regular.ttf"; Sha256 = "4C051A78A21C4E8E9DCCF1C754776D33F356B8CC6EF95D9B64761B9BAE814B84" },
  @{ Family = "Zen Old Mincho"; Style = "Bold"; Folder = "zenoldmincho"; File = "ZenOldMincho-Bold.ttf"; Sha256 = "D6B95C1FF45C8DAC153D28961E4C37D7D03B648330C71F884D124DC652A13C0D" }
)

$Licenses = @(
  @{ Folder = "notosansjp"; File = "NotoSansJP-OFL.txt"; Sha256 = "1C05C68C34F9708415AADA51F17E1B0092D2CEA709BF4A94CD38114F9E73D7D9" },
  @{ Folder = "mplusrounded1c"; File = "MPLUSRounded1c-OFL.txt"; Sha256 = "04971E3FCEE60B247395150D93B3616F6A0B092572332C96187B472976553ABC"; Url = "https://raw.githubusercontent.com/coz-m/MPLUS_FONTS/eb604901d6f04b6f7f2a84b0378c58df84a9dba6/OFL.txt" },
  @{ Folder = "delagothicone"; File = "DelaGothicOne-OFL.txt"; Sha256 = "C0014792D4F4ABC0508C295B277F2B17AE44465C8DC88D12AF9CEA48279B5FDA" },
  @{ Folder = "bizudpgothic"; File = "BIZUDPGothic-OFL.txt"; Sha256 = "E753D7155D53C747D037A445E584C8ECFCA6DD79846DB610417E282A736B28BC" },
  @{ Folder = "zenkakugothicnew"; File = "ZenKakuGothicNew-OFL.txt"; Sha256 = "0FAC78A235C98D640CB06332EB5362C211D86FA03C011DF438C35005D22AD2C7" },
  @{ Folder = "zenmarugothic"; File = "ZenMaruGothic-OFL.txt"; Sha256 = "2A20CF7CE1909D8EE1E949095D340F7D7656705F7C810A2D6FAF56800AD0CB3D" },
  @{ Folder = "zenoldmincho"; File = "ZenOldMincho-OFL.txt"; Sha256 = "469D214F9842809659C827B7F2ADAF40EC0DF6EFDD5FE18B7127665C32AAFAEC" }
)

function Write-Step([string]$Message) {
  Write-Host "[japanese-fonts] $Message"
}

function Append-Status([string]$Message) {
  $statusDir = Split-Path -Parent $StatusPath
  if ($statusDir) { New-Item -ItemType Directory -Force -Path $statusDir | Out-Null }
  Add-Content -LiteralPath $StatusPath -Value "[fonts] $Message" -Encoding UTF8
}

function Get-Sha256Hex([string]$Path) {
  $stream = [System.IO.File]::OpenRead($Path)
  try {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
      return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "")
    } finally {
      $sha.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
}

function Test-FileHash([string]$Path, [string]$Expected) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
  return (Get-Sha256Hex $Path) -eq $Expected
}

function Get-VerifiedDownload([string]$Url, [string]$Destination, [string]$ExpectedHash) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
  Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
  Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
  if (-not (Test-FileHash $Destination $ExpectedHash)) {
    Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    throw "SHA-256 verification failed: $(Split-Path -Leaf $Destination)"
  }
}

New-Item -ItemType Directory -Force -Path $UserFontDir, $LicenseDir, $DownloadDir | Out-Null
New-Item -Path $RegistryPath -Force | Out-Null

$installed = 0
$skipped = 0
foreach ($font in $Fonts) {
  $destination = Join-Path $UserFontDir $font.File
  if (Test-FileHash $destination $font.Sha256) {
    $skipped++
    Write-Step "already installed: $($font.Family) $($font.Style)"
  } elseif ($VerifyOnly) {
    throw "Font is missing or invalid: $($font.Family) $($font.Style)"
  } else {
    $download = Join-Path $DownloadDir $font.File
    $sourceFile = if ($font.SourceFile) { $font.SourceFile } else { $font.File }
    $url = "$RawRoot/$($font.Folder)/$sourceFile"
    Write-Step "download: $($font.Family) $($font.Style)"
    Get-VerifiedDownload $url $download $font.Sha256
    Copy-Item -LiteralPath $download -Destination $destination -Force
    if (-not (Test-FileHash $destination $font.Sha256)) {
      throw "Installed font verification failed: $($font.File)"
    }
    $installed++
  }
  $registryName = "$($font.Family) $($font.Style) (TrueType)"
  New-ItemProperty -Path $RegistryPath -Name $registryName -Value $destination -PropertyType String -Force | Out-Null
}

foreach ($license in $Licenses) {
  $destination = Join-Path $LicenseDir $license.File
  if (Test-FileHash $destination $license.Sha256) { continue }
  if ($VerifyOnly) { throw "Font license is missing or invalid: $($license.File)" }
  $licenseUrl = if ($license.Url) { $license.Url } else { "$RawRoot/$($license.Folder)/OFL.txt" }
  Get-VerifiedDownload $licenseUrl $destination $license.Sha256
}

if (-not ("KirinukiFontBroadcast" -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class KirinukiFontBroadcast {
  [DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)]
  public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, IntPtr lParam, uint flags, uint timeout, out UIntPtr result);
}
"@
}
$broadcastResult = [UIntPtr]::Zero
[void][KirinukiFontBroadcast]::SendMessageTimeout([IntPtr]0xffff, 0x001D, [UIntPtr]::Zero, [IntPtr]::Zero, 0x0002, 3000, [ref]$broadcastResult)

Append-Status "Japanese subtitle fonts: installed=$installed, skipped=$skipped, verification=passed"
Write-Step "done (installed=$installed, skipped=$skipped)"

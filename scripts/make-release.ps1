param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\release"),
  [switch]$IncludeModels,
  [string]$SourceOfferUrl = "",
  [string]$SourceOfferChecksum = ""
)

$ErrorActionPreference = "Stop"

$packageScript = Join-Path $PSScriptRoot "package-release.ps1"
if ($IncludeModels) {
  & $packageScript -OutputDir $OutputDir -SourceOfferUrl $SourceOfferUrl -SourceOfferChecksum $SourceOfferChecksum -IncludeModels
}
else {
  & $packageScript -OutputDir $OutputDir -SourceOfferUrl $SourceOfferUrl -SourceOfferChecksum $SourceOfferChecksum
}

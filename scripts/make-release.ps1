param(
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\release"),
  [switch]$IncludeModels,
  [string]$SourceOfferUrl = "<fill in the release source URL or archive URL>",
  [string]$SourceOfferChecksum = "<fill in the checksum>"
)

$ErrorActionPreference = "Stop"

$packageScript = Join-Path $PSScriptRoot "package-release.ps1"
if ($IncludeModels) {
  & $packageScript -OutputDir $OutputDir -SourceOfferUrl $SourceOfferUrl -SourceOfferChecksum $SourceOfferChecksum -IncludeModels
}
else {
  & $packageScript -OutputDir $OutputDir -SourceOfferUrl $SourceOfferUrl -SourceOfferChecksum $SourceOfferChecksum
}

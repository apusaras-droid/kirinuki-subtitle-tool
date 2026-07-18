$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$appPath = Join-Path $root "frontend\app.js"
$htmlPath = Join-Path $root "frontend\index.html"

$appText = Get-Content -LiteralPath $appPath -Raw -Encoding UTF8
$htmlText = Get-Content -LiteralPath $htmlPath -Raw -Encoding UTF8

$references = [regex]::Matches($appText, '\$\("([A-Za-z0-9_-]+)"\)') |
  ForEach-Object { $_.Groups[1].Value } |
  Sort-Object -Unique
$ids = [regex]::Matches($htmlText, 'id="([A-Za-z0-9_-]+)"') |
  ForEach-Object { $_.Groups[1].Value } |
  Sort-Object -Unique

$dynamicIds = @(
  "subtitle-panel",
  "subtitleCount",
  "subtitleList",
  "zoomBoxScaleInput",
  "zoomBoxXInput",
  "zoomBoxYInput"
)
$missing = $references | Where-Object { $_ -notin $ids -and $_ -notin $dynamicIds }
$duplicates = [regex]::Matches($htmlText, 'id="([A-Za-z0-9_-]+)"') |
  ForEach-Object { $_.Groups[1].Value } |
  Group-Object |
  Where-Object Count -gt 1

if ($missing) {
  throw "Missing frontend IDs: $($missing -join ', ')"
}
if ($duplicates) {
  throw "Duplicate frontend IDs: $($duplicates.Name -join ', ')"
}
if ($appText.Contains('subtitlePageVideo?.paused && selectedSubtitle()')) {
  throw "Subtitle preview must not show the selected subtitle outside its timeline range"
}
if (-not $appText.Contains('const overlaySub = subtitleAtTimelineTime(subtitlePageT, state.mode);')) {
  throw "Subtitle preview must resolve its overlay from the active preview timeline"
}

Write-Output "frontend DOM contract passed"

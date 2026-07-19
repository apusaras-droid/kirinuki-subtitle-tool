$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$appPath = Join-Path $root "frontend\app.js"
$htmlPath = Join-Path $root "frontend\index.html"
$stylesPath = Join-Path $root "frontend\styles.css"

$appText = Get-Content -LiteralPath $appPath -Raw -Encoding UTF8
$htmlText = Get-Content -LiteralPath $htmlPath -Raw -Encoding UTF8
$stylesText = Get-Content -LiteralPath $stylesPath -Raw -Encoding UTF8

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

if (-not $appText.Contains('screen-effect-selection-button') -or -not $appText.Contains('saveChangesBtn.addEventListener')) {
  throw "Added screen effects must expose a selectable edit-and-save workflow"
}

if (-not $appText.Contains('screenEffectPanelMode') -or -not $appText.Contains('const speedIds = new Set')) {
  throw "Screen effect add/edit modes and relevant-only parameters must remain separated"
}

if (-not $appText.Contains('screenEffectPositionPresets') -or -not $appText.Contains('position_preset')) {
  throw "Large question placement presets and numeric fine tuning must remain available"
}

if ($appText.Contains('page === "export" && !(state.editPlanPath || state.editPlan)')) {
  throw "The export options page must remain reachable before a lazy edit-plan build"
}

if (-not $appText.Contains('$("previewToExportBtn").addEventListener') -or -not $appText.Contains('await prepareFinalExport(true);')) {
  throw "Preview-to-export navigation must persist data and build a missing edit plan"
}

if (-not $appText.Contains('function appliedScreenEffectCount(') -or $appText.Contains('const effects = state.decorationProject?.screen_effect_stacks?.length || 0;')) {
  throw "Export summary must count assigned screen effects instead of stored definitions"
}

if (-not $appText.Contains('narration: {') -or ([regex]::Matches($htmlText, 'option value="narration"')).Count -lt 2) {
  throw "Narration timing preset must remain available on both transcription settings surfaces"
}

if (-not $appText.Contains('checkbox.checked = category !== "cut" || item.action === "remove";')) {
  throw "Gemini cut review must select remove proposals instead of keep/highlight entries"
}

if (-not $appText.Contains('if (cut && !subtitle && !selectedCuts.length)')) {
  throw "Gemini cut apply must reject an empty remove selection instead of silently succeeding"
}

if (-not $appText.Contains('item.src_start ?? item.start_sec ?? item.start ?? item.source_start_sec')) {
  throw "Cut interval normalization must accept Gemini start_sec/end_sec proposals"
}

if (-not $appText.Contains('const VAD_BOUNDARY_PRESETS = Object.freeze({') -or ([regex]::Matches($htmlText, '<option value="(tight|compact|balanced|narration|generous)">')).Count -lt 5) {
  throw "Detailed settings must expose all five VAD boundary presets"
}

if (-not $stylesText.Contains('width: 80%;') -or -not $stylesText.Contains('overflow-wrap: anywhere;')) {
  throw "Subtitle preview must wrap long captions inside 80 percent of the video width"
}

Write-Output "frontend DOM contract passed"

const state = {
  projectId: null,
  projectName: "",
  sourceVideo: null,
  sourceVideoUrl: null,
  audioPath: null,
  transcript: null,
  silences: [],
  editPlanPath: null,
  editPlan: null,
  editPlanBuildSignature: "",
  mode: "source",
  selectedSubtitleId: null,
  loopSubtitleId: null,
  editorView: "timeline",
  waveformDrafts: {
    cut: { start: null, end: null },
  },
  manualCutSegments: [],
  waveformLoopRange: null,
  appPage: "editor",
  sourceRanges: [],
  selectedSourceRangeIndex: 0,
  previewUrl: null,
  waveformUrl: null,
  videoInfo: null,
  processingSummary: null,
  videoInfoExpanded: false,
  projectSettings: {
    default_emotion_preset_id: "emotion_neutral",
    default_subtitle_style_preset_id: "subtitle_standard",
    output_profile: "mp4_compat",
    final_output_mode: "video_srt",
  },
  projectScenes: [],
  presets: {
    emotion_presets: [],
    subtitle_style_presets: [],
    scenes: [],
    decoration_presets: {
      font_presets: [],
      effect_groups: [],
      layout_presets: [],
    },
    emotion_labels: ["neutral", "joy", "anger", "sadness", "surprise", "fear", "embarrassment", "teasing"],
  },
  decorationProject: null,
  decorationSelectionId: null,
  decorationPreviewUrl: null,
  projectList: [],
  systemFonts: [],
  decorationEditTab: "text",
  frameSyncMode: "live",
  screenEffectSelectedStackId: "",
  screenEffectCategoryFilter: "all",
  zoomBox: {
    active: false,
    centerX: 0.5,
    centerY: 0.5,
    widthRatio: 0.8,
  },
  decorationShaderPreview: {
    gl: null,
    program: null,
    texture: null,
    buffer: null,
    raf: null,
    active: false,
  },
};

const $ = (id) => document.getElementById(id);
const video = $("video");
const subtitlePageVideo = $("subtitlePagePreviewVideo");
const statusEl = $("status");
let previewSyncLock = false;
let browserHeartbeatTimer = null;
let taskProgressTimer = null;
let backendProgressTimer = null;
let activeTaskProgress = null;
const TASK_DURATION_HISTORY_KEY = "kirinuki_task_duration_history_v1";
const ZOOM_BOX_PRESETS_KEY = "kirinuki_zoom_box_presets_v1";
const TASK_FALLBACK_ESTIMATE_SEC = {
  "動画読み込み": 20,
  "音声抽出": 30,
  "文字起こし": 300,
  "文字起こし 精密補正": 1200,
  "無音検出": 30,
  "カット案作成": 15,
  "仮出力": 180,
  "手動カット仮出力": 180,
  "最終出力": 300,
  "装飾プレビュー": 60,
  "現在字幕プレビュー": 45,
  "軽量装飾プレビュー": 60,
  "カット動画+ASS出力": 300,
};

const AUDIO_TIMING_PRESETS = {
  standard: {
    useVad: true,
    voiceIsolationEnabled: false,
    useIsolatedVoiceForVad: false,
    useIsolatedVoiceForWhisper: false,
    alignTimestamps: true,
    useWhisperxAlignment: false,
    vadThreshold: 0.25,
    minSpeechDurationSec: 0.2,
    minSilenceDurationSec: 0.5,
    vadMinSilenceDurationSec: 0.08,
    speechPadSec: 0.05,
    preMarginSec: 0.3,
    postMarginSec: 0.5,
    mergeSilenceGapSec: 0.5,
    silenceThresholdDb: -35,
    minKeepSegmentDuration: 1.0,
  },
  strict: {
    useVad: true,
    voiceIsolationEnabled: false,
    useIsolatedVoiceForVad: false,
    useIsolatedVoiceForWhisper: false,
    alignTimestamps: true,
    useWhisperxAlignment: false,
    vadThreshold: 0.22,
    minSpeechDurationSec: 0.12,
    minSilenceDurationSec: 0.2,
    vadMinSilenceDurationSec: 0.08,
    speechPadSec: 0.03,
    preMarginSec: 0.12,
    postMarginSec: 0.25,
    mergeSilenceGapSec: 0.2,
    silenceThresholdDb: -35,
    minKeepSegmentDuration: 0.35,
  },
  bgm_strong: {
    useVad: true,
    voiceIsolationEnabled: true,
    useIsolatedVoiceForVad: true,
    useIsolatedVoiceForWhisper: false,
    alignTimestamps: true,
    useWhisperxAlignment: false,
    vadThreshold: 0.32,
    minSpeechDurationSec: 0.16,
    minSilenceDurationSec: 0.28,
    vadMinSilenceDurationSec: 0.1,
    speechPadSec: 0.04,
    preMarginSec: 0.18,
    postMarginSec: 0.35,
    mergeSilenceGapSec: 0.3,
    silenceThresholdDb: -38,
    minKeepSegmentDuration: 0.45,
  },
  whisperx_precise: {
    useVad: true,
    voiceIsolationEnabled: false,
    useIsolatedVoiceForVad: false,
    useIsolatedVoiceForWhisper: false,
    alignTimestamps: true,
    useWhisperxAlignment: true,
    vadThreshold: 0.22,
    minSpeechDurationSec: 0.12,
    minSilenceDurationSec: 0.2,
    vadMinSilenceDurationSec: 0.08,
    speechPadSec: 0.03,
    preMarginSec: 0.12,
    postMarginSec: 0.25,
    mergeSilenceGapSec: 0.2,
    silenceThresholdDb: -35,
    minKeepSegmentDuration: 0.35,
  },
  loose: {
    useVad: true,
    voiceIsolationEnabled: false,
    useIsolatedVoiceForVad: false,
    useIsolatedVoiceForWhisper: false,
    alignTimestamps: true,
    useWhisperxAlignment: false,
    vadThreshold: 0.2,
    minSpeechDurationSec: 0.18,
    minSilenceDurationSec: 0.6,
    vadMinSilenceDurationSec: 0.12,
    speechPadSec: 0.08,
    preMarginSec: 0.5,
    postMarginSec: 0.8,
    mergeSilenceGapSec: 0.75,
    silenceThresholdDb: -35,
    minKeepSegmentDuration: 1.0,
  },
};

function sendBrowserHeartbeat() {
  fetch("/api/browser/heartbeat", {
    method: "POST",
    keepalive: true,
  }).catch(() => {});
}

function sendBrowserCloseSignal() {
  try {
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/browser/close", new Blob([], { type: "application/json" }));
      return;
    }
  } catch {
    // Fall through to fetch.
  }
  fetch("/api/browser/close", {
    method: "POST",
    keepalive: true,
  }).catch(() => {});
}

function startBrowserHeartbeat() {
  if (browserHeartbeatTimer) return;
  sendBrowserHeartbeat();
  browserHeartbeatTimer = setInterval(sendBrowserHeartbeat, 5000);
}

function playbackSourceUrl() {
  if (state.mode === "rendered" && state.previewUrl) return state.previewUrl;
  return state.sourceVideoUrl || "";
}

function mirroredPreviewVideos() {
  return [subtitlePageVideo].filter(Boolean);
}

function activeMirroredPreviewVideo() {
  if (state.appPage === "subtitles") return subtitlePageVideo || null;
  return null;
}

function primaryPlaybackVideo() {
  return activeMirroredPreviewVideo() || video;
}

function updatePreviewAudioRouting() {
  const activeMirror = activeMirroredPreviewVideo();
  if (video) video.muted = Boolean(activeMirror);
  for (const previewVideo of mirroredPreviewVideos()) {
    previewVideo.muted = previewVideo !== activeMirror;
  }
}

function syncMirroredPreviewSource(previewVideo) {
  if (!previewVideo) return;
  const nextSrc = playbackSourceUrl();
  if ((previewVideo.dataset.syncSrc || "") !== nextSrc) {
    previewVideo.dataset.syncSrc = nextSrc;
    if (nextSrc) {
      previewVideo.src = nextSrc;
      previewVideo.load();
    }
  }
}

function syncMirroredPreviewState(previewVideo) {
  if (!previewVideo) return;
  updatePreviewAudioRouting();
  syncMirroredPreviewSource(previewVideo);
  if (state.appPage === "subtitles") {
    previewVideo.playbackRate = video.playbackRate || previewVideo.playbackRate || 1;
    return;
  }
  if (previewVideo.readyState >= 1 && Math.abs((previewVideo.currentTime || 0) - (video.currentTime || 0)) > 0.15) {
    previewSyncLock = true;
    previewVideo.currentTime = video.currentTime || 0;
    previewSyncLock = false;
  }
  previewVideo.playbackRate = video.playbackRate || 1;
  if (video.paused && !previewVideo.paused) {
    previewSyncLock = true;
    previewVideo.pause();
    previewSyncLock = false;
  } else if (!video.paused && previewVideo.paused && document.body.contains(previewVideo)) {
    previewVideo.play().catch(() => {});
  }
}

function syncAllMirroredPreviews() {
  updatePreviewAudioRouting();
  mirroredPreviewVideos().forEach(syncMirroredPreviewState);
}

function bindMirroredPreviewVideo(previewVideo) {
  if (!previewVideo || previewVideo.dataset.bound === "1") return;
  previewVideo.dataset.bound = "1";
  previewVideo.addEventListener("timeupdate", updateOverlay);
  previewVideo.addEventListener("loadedmetadata", updateOverlay);
  previewVideo.addEventListener("play", () => {
    if (previewSyncLock) return;
    if (activeMirroredPreviewVideo() === previewVideo) return;
    previewSyncLock = true;
    if (Math.abs((video.currentTime || 0) - (previewVideo.currentTime || 0)) > 0.05) {
      video.currentTime = previewVideo.currentTime || 0;
    }
    video.play().catch(() => {});
    previewSyncLock = false;
  });
  previewVideo.addEventListener("pause", () => {
    if (previewSyncLock) return;
    if (activeMirroredPreviewVideo() === previewVideo) return;
    previewSyncLock = true;
    if (!video.paused) video.pause();
    previewSyncLock = false;
  });
  previewVideo.addEventListener("seeked", () => {
    if (previewSyncLock) return;
    if (activeMirroredPreviewVideo() === previewVideo) {
      updateOverlay();
      return;
    }
    previewSyncLock = true;
    video.currentTime = previewVideo.currentTime || 0;
    previewSyncLock = false;
  });
  previewVideo.addEventListener("ratechange", () => {
    if (previewSyncLock) return;
    if (activeMirroredPreviewVideo() === previewVideo) return;
    previewSyncLock = true;
    video.playbackRate = previewVideo.playbackRate || 1;
    previewSyncLock = false;
  });
}

bindMirroredPreviewVideo(subtitlePageVideo);
updatePreviewAudioRouting();

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function formatDuration(sec) {
  sec = Math.max(0, Math.round(Number(sec) || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function taskDurationHistory() {
  try {
    return JSON.parse(localStorage.getItem(TASK_DURATION_HISTORY_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function averageTaskDuration(label) {
  const values = taskDurationHistory()[label] || [];
  if (!values.length) return TASK_FALLBACK_ESTIMATE_SEC[label] || null;
  return values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length;
}

function rememberTaskDuration(label, sec) {
  if (!label || !Number.isFinite(sec) || sec <= 0) return;
  const history = taskDurationHistory();
  const values = [...(history[label] || []), Math.round(sec)].slice(-5);
  history[label] = values;
  try {
    localStorage.setItem(TASK_DURATION_HISTORY_KEY, JSON.stringify(history));
  } catch {
    // localStorage is best-effort only.
  }
}

function renderTaskProgress() {
  const box = $("taskProgress");
  const name = $("taskProgressName");
  const time = $("taskProgressTime");
  if (!box || !name || !time) return;
  if (!activeTaskProgress) {
    box.classList.add("idle");
    name.textContent = "待機中";
    time.textContent = "経過 00:00 / 残り --:--";
    return;
  }
  const elapsed = (performance.now() - activeTaskProgress.startedAt) / 1000;
  const backend = activeTaskProgress.backendProgress || null;
  const estimate = activeTaskProgress.estimateSec;
  const remaining = backend?.remaining_sec ?? (estimate ? Math.max(0, estimate - elapsed) : null);
  const overtime = !backend && estimate && elapsed > estimate;
  const percent = Number.isFinite(Number(backend?.percent)) ? ` ${Number(backend.percent).toFixed(1)}%` : "";
  const speed = Number(backend?.speed) > 0 ? ` / ${Number(backend.speed).toFixed(3)}x` : "";
  box.classList.remove("idle");
  name.textContent = `${backend?.stage || activeTaskProgress.label}中${percent}`;
  time.textContent = `経過 ${formatDuration(elapsed)} / 残り ${remaining === null ? "推定中" : overtime ? "確認中" : formatDuration(remaining)}`;
  if (speed) time.textContent += speed;
}

function startTaskProgress(label) {
  if (taskProgressTimer) clearInterval(taskProgressTimer);
  if (backendProgressTimer) clearInterval(backendProgressTimer);
  activeTaskProgress = {
    label,
    startedAt: performance.now(),
    estimateSec: averageTaskDuration(label),
    backendProgress: null,
  };
  renderTaskProgress();
  taskProgressTimer = setInterval(renderTaskProgress, 1000);
  if (state.projectId) {
    pollBackendProgress();
    backendProgressTimer = setInterval(pollBackendProgress, 2500);
  }
}

function finishTaskProgress(success = true) {
  if (activeTaskProgress) {
    const elapsed = (performance.now() - activeTaskProgress.startedAt) / 1000;
    if (success) rememberTaskDuration(activeTaskProgress.label, elapsed);
  }
  if (taskProgressTimer) clearInterval(taskProgressTimer);
  taskProgressTimer = null;
  if (backendProgressTimer) clearInterval(backendProgressTimer);
  backendProgressTimer = null;
  activeTaskProgress = null;
  renderTaskProgress();
}

async function pollBackendProgress() {
  if (!activeTaskProgress || !state.projectId) return;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.projectId)}/progress`);
    if (!res.ok) return;
    const data = await res.json();
    if (!activeTaskProgress) return;
    activeTaskProgress.backendProgress = data && data.active !== false ? data : activeTaskProgress.backendProgress;
    renderTaskProgress();
  } catch {
    // Progress polling is informational and must not fail the running task.
  }
}

function setBusy(busy) {
  const persistentButtons = new Set([
    "editorPageBtn",
    "subtitlePageBtn",
    "projectListPageBtn",
    "settingsPageBtn",
    "decorationPageBtn",
    "previewCheckPageBtn",
    "saveProjectBtn",
    "overwriteProjectBtn",
    "subtitlePageBackBtn",
    "settingsBackBtn",
    "projectListBackBtn",
    "decorationBackBtn",
    "previewCheckBackBtn",
  ]);
  document.querySelectorAll("button").forEach((button) => {
    if (persistentButtons.has(button.id)) return;
    button.disabled = busy;
  });
}

function setProjectReady(ready) {
  for (const id of ["saveProjectBtn", "overwriteProjectBtn", "saveSubtitlesBtn", "manualPreviewBtn", "previewRenderBtn", "exportBtn", "probeBtn", "extractBtn", "transcribeBtn", "silenceBtn", "planBtn"]) {
    $(id).disabled = !ready;
  }
}

function subtitleItems() {
  if (Array.isArray(state.editPlan?.subtitles) && state.editPlan.subtitles.length) return state.editPlan.subtitles;
  if (Array.isArray(state.transcript?.subtitles) && state.transcript.subtitles.length) return state.transcript.subtitles;
  return Array.isArray(state.editPlan?.subtitles) ? state.editPlan.subtitles : [];
}

function subtitleSignatureItems(subtitles = subtitleItems()) {
  return (subtitles || []).map((sub) => ({
    id: sub.id || "",
    enabled: sub.enabled !== false,
    text: sub.text || "",
    start: roundTime(Number(sub.range_relative_start_sec ?? sub.start_sec ?? sub.output_start_sec ?? 0) || 0),
    end: roundTime(Number(sub.range_relative_end_sec ?? sub.end_sec ?? sub.output_end_sec ?? 0) || 0),
  }));
}

function transcriptForEditPlanRequest() {
  const transcript = { ...(state.transcript || {}) };
  const subtitles = subtitleItems();
  if (subtitles.length) {
    transcript.subtitles = subtitles.map((sub) => ({ ...sub }));
  }
  return transcript;
}

function currentSubtitleById(id) {
  return subtitleItems().find((sub) => sub.id === id) || null;
}

function selectedSubtitle() {
  return state.selectedSubtitleId ? currentSubtitleById(state.selectedSubtitleId) : null;
}

function presetOptions(items, selectedValue, placeholder = "") {
  const select = document.createElement("select");
  if (placeholder) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.appendChild(option);
  }
  for (const item of items || []) {
    const option = document.createElement("option");
    option.value = item.id || "";
    option.textContent = item.name || item.id || "";
    select.appendChild(option);
  }
  select.value = selectedValue || "";
  return select;
}

function selectedEmotionLabel() {
  const sub = selectedSubtitle();
  return sub?.emotion || "neutral";
}

function selectedStylePresetId() {
  const sub = selectedSubtitle();
  return sub?.subtitle_style_preset_id || "";
}

function syncProjectSettingsForm() {
  if ($("defaultEmotionPreset")) $("defaultEmotionPreset").value = state.projectSettings?.default_emotion_preset_id || "emotion_neutral";
  if ($("defaultSubtitleStylePreset")) $("defaultSubtitleStylePreset").value = state.projectSettings?.default_subtitle_style_preset_id || "subtitle_standard";
  if ($("outputProfile")) $("outputProfile").value = state.projectSettings?.output_profile || "mp4_compat";
  if ($("finalOutputMode")) $("finalOutputMode").value = state.projectSettings?.final_output_mode || "video_srt";
  const audio = state.projectSettings?.audio_timing || {};
  if ($("audioTimingPreset")) $("audioTimingPreset").value = audio.preset_id || "strict";
  applyAudioTimingValues(audio, { keepPreset: true, silent: true });
}

function autoProjectNameForFile(fileName) {
  const today = new Date();
  const yyyy = String(today.getFullYear());
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  const stem = String(fileName || "project").replace(/\.[^.]+$/, "").trim();
  const cleaned = stem.replace(/[\\/:*?"<>|]+/g, "_").replace(/\s+/g, " ").trim() || "project";
  return `${cleaned}_${yyyy}${mm}${dd}`;
}

function projectDisplayName() {
  return state.projectName || state.projectId || "プロジェクト未作成";
}

function renderProjectLabel() {
  const label = $("projectLabel");
  if (!label) return;
  label.textContent = state.projectId ? `${projectDisplayName()} / ${state.projectId}` : "プロジェクト未作成";
}

function syncProjectNameInput(value) {
  const input = $("projectName");
  if (input) input.value = value || "";
}

function numericInputValue(id, fallback) {
  const value = Number($(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function setChecked(id, value) {
  const input = $(id);
  if (input) input.checked = Boolean(value);
}

function setInputValue(id, value) {
  const input = $(id);
  if (input) input.value = String(value);
}

function applyAudioTimingValues(values = {}, options = {}) {
  const presetId = values.preset_id || $("audioTimingPreset")?.value || "strict";
  const preset = AUDIO_TIMING_PRESETS[presetId] || AUDIO_TIMING_PRESETS.strict;
  const next = { ...preset, ...values };
  if (!options.keepPreset && $("audioTimingPreset")) $("audioTimingPreset").value = presetId;
  setChecked("useVad", next.useVad);
  setChecked("voiceIsolationEnabled", next.voiceIsolationEnabled);
  setChecked("useIsolatedVoiceForVad", next.useIsolatedVoiceForVad);
  setChecked("useIsolatedVoiceForWhisper", next.useIsolatedVoiceForWhisper);
  setChecked("alignTimestamps", next.alignTimestamps);
  setChecked("useWhisperxAlignment", next.useWhisperxAlignment);
  setInputValue("vadThreshold", next.vadThreshold);
  setInputValue("minSpeechDurationSec", next.minSpeechDurationSec);
  setInputValue("minSilenceDurationSec", next.minSilenceDurationSec);
  setInputValue("vadMinSilenceDurationSec", next.vadMinSilenceDurationSec);
  setInputValue("speechPadSec", next.speechPadSec);
  setInputValue("preMarginSec", next.preMarginSec);
  setInputValue("postMarginSec", next.postMarginSec);
  setInputValue("mergeSilenceGapSec", next.mergeSilenceGapSec);
  setInputValue("silenceThresholdDb", next.silenceThresholdDb);
  setInputValue("minKeepSegmentDuration", next.minKeepSegmentDuration);
  syncAudioSettingsControls();
  if (!options.silent) {
    setStatus(`発話タイミング設定を「${$("audioTimingPreset")?.selectedOptions?.[0]?.textContent || presetId}」にしました`);
  }
}

function audioTimingSettings() {
  const minSpeechDurationSec = numericInputValue("minSpeechDurationSec", 0.2);
  const vadMinSilenceDurationSec = numericInputValue("vadMinSilenceDurationSec", 0.08);
  const speechPadSec = numericInputValue("speechPadSec", 0.05);
  const minSilenceDurationSec = numericInputValue("minSilenceDurationSec", 0.5);
  return {
    preset_id: $("audioTimingPreset")?.value || "strict",
    detection_mode: $("useVad")?.checked ? "vad" : "silencedetect",
    voice_isolation_enabled: Boolean($("voiceIsolationEnabled")?.checked),
    use_isolated_voice_for_vad: Boolean($("useIsolatedVoiceForVad")?.checked),
    use_isolated_voice_for_whisper: Boolean($("useIsolatedVoiceForWhisper")?.checked),
    align_timestamps: Boolean($("alignTimestamps")?.checked),
    use_whisperx_alignment: Boolean($("useWhisperxAlignment")?.checked),
    vad_threshold: numericInputValue("vadThreshold", 0.25),
    min_speech_duration_sec: minSpeechDurationSec,
    min_silence_duration_sec: minSilenceDurationSec,
    vad_min_speech_duration_ms: Math.max(1, Math.round(minSpeechDurationSec * 1000)),
    vad_min_silence_duration_ms: Math.max(1, Math.round(vadMinSilenceDurationSec * 1000)),
    vad_speech_pad_ms: Math.max(0, Math.round(speechPadSec * 1000)),
    speech_pad_sec: speechPadSec,
    pre_margin_sec: numericInputValue("preMarginSec", 0.3),
    post_margin_sec: numericInputValue("postMarginSec", 0.5),
    merge_silence_gap_sec: numericInputValue("mergeSilenceGapSec", 0.5),
    silence_threshold_db: numericInputValue("silenceThresholdDb", -35),
    min_keep_segment_duration: numericInputValue("minKeepSegmentDuration", 1.0),
  };
}

function updatePresetSelectors() {
  const emotionSelect = $("defaultEmotionPreset");
  const styleSelect = $("defaultSubtitleStylePreset");
  if (!emotionSelect || !styleSelect) return;
  const emotionPresets = state.presets.emotion_presets || [];
  const stylePresets = state.presets.subtitle_style_presets || [];
  emotionSelect.textContent = "";
  const emotionItems = [
    ...emotionPresets.map((item) => ({ id: item.emotion || item.id, name: `${item.name || item.id} (${item.emotion || item.id})` })),
  ];
  for (const opt of emotionItems) {
    const option = document.createElement("option");
    option.value = opt.id;
    option.textContent = opt.name;
    emotionSelect.appendChild(option);
  }
  const defaultEmotion = state.projectSettings?.default_emotion_preset_id || selectedEmotionLabel();
  if (!emotionSelect.value) emotionSelect.value = defaultEmotion;
  styleSelect.textContent = "";
  for (const item of stylePresets) {
    const option = document.createElement("option");
    option.value = item.id || "";
    option.textContent = item.name || item.id || "";
    styleSelect.appendChild(option);
  }
  if (!styleSelect.value) {
    styleSelect.value = state.projectSettings?.default_subtitle_style_preset_id || selectedStylePresetId() || (stylePresets[0]?.id || "");
  }
}

function applyDefaultPresetToSubtitle(sub) {
  if (!sub) return;
  const emotion = $("defaultEmotionPreset")?.value || "neutral";
  const style = $("defaultSubtitleStylePreset")?.value || "subtitle_standard";
  sub.emotion = emotion;
  sub.subtitle_style_preset_id = style;
}

function resetProjectDefaultPresetsToStandard() {
  const emotionSelect = $("defaultEmotionPreset");
  const styleSelect = $("defaultSubtitleStylePreset");
  if (emotionSelect) emotionSelect.value = "emotion_neutral";
  if (styleSelect) styleSelect.value = "subtitle_standard";
  saveProjectSettings().catch(() => {});
  renderScenes();
  renderSubtitles();
}

async function loadPresets() {
  const data = await api("/api/presets", { method: "GET" });
  const fontData = await api("/api/system/fonts", { method: "GET" }).catch(() => ({ fonts: [] }));
  const filteredFonts = japaneseFontNames(fontData.fonts || []);
  state.systemFonts = filteredFonts.length ? filteredFonts : ["Meiryo", "Yu Gothic", "Yu Mincho", "MS Gothic", "MS Mincho"];
  state.presets = {
    emotion_presets: data.emotion_presets || [],
    subtitle_style_presets: data.subtitle_style_presets || [],
    scenes: data.scenes || [],
    decoration_presets: data.decoration_presets || {
      font_presets: [],
      effect_groups: [],
      screen_effect_library: [],
      screen_effect_stacks: [],
      layout_presets: [],
      frame_presets: [],
      screen_effect_targets: { global_stack_ids: [], scene_stack_ids: {} },
    },
    emotion_labels: data.emotion_labels || ["neutral", "joy", "anger", "sadness", "surprise", "fear", "embarrassment", "teasing"],
  };
  updatePresetSelectors();
  renderSubtitles();
  renderVideoInfo();
  renderDecorationPage();
}

function syncProjectScenesFromSubtitles() {
  const subtitles = subtitleItems();
  const source = subtitles.length ? subtitles : (state.decorationProject?.events || []).filter((item) => !isGlobalDecorationEvent(item));
  state.projectScenes = sceneCatalogFromSubtitles(source);
  if (state.decorationProject) state.decorationProject.scenes = [...state.projectScenes];
}

async function saveProjectScenes() {
  if (!state.projectId) return;
  syncProjectScenesFromSubtitles();
  const data = await api("/api/projects/scenes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId, scenes: state.projectScenes }),
  });
  state.projectScenes = data.project?.scenes || state.projectScenes;
}

async function persistCurrentSubtitles() {
  if (!state.projectId) return;
  const subtitles = subtitleItems();
  if (!subtitles.length) throw new Error("先に字幕を生成してください");
  if (state.editPlan) {
    state.editPlan.subtitles = subtitles;
    const data = await api("/api/edit-plan/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, edit_plan: state.editPlan }),
    });
    state.editPlan = data.edit_plan || state.editPlan;
  } else {
    const data = await api("/api/transcript/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, subtitles }),
    });
    if (data.transcript) {
      state.transcript = {
        ...state.transcript,
        ...data.transcript,
      };
    }
  }
  if (state.decorationProject) {
    syncDecorationEventsFromSubtitles({ path: state.decorationProject.source_srt, subtitles: decorationSourceSubtitles() });
    await saveDecorationProject();
  }
  return state.editPlan || state.transcript || {};
}

function editPlanRequestSignatureFromCurrent() {
  let range = null;
  try {
    range = currentRange();
  } catch {
    range = state.editPlan?.source_range || null;
  }
  return JSON.stringify({
    range,
    silence_count: (state.silences || []).length,
    manual_cut_segments: normalizeIntervalList(state.manualCutSegments || []),
    protected_segments: normalizeIntervalList(state.protectedSegments || []),
    subtitles: subtitleSignatureItems(),
  });
}

function editPlanRequestSignatureFromPlan(plan) {
  if (!plan) return "";
  return JSON.stringify({
    range: plan.source_range || null,
    silence_count: (state.silences || []).length,
    manual_cut_segments: normalizeIntervalList(plan.manual_cut_segments || []),
    protected_segments: normalizeIntervalList(plan.protected_segments || []),
    subtitles: subtitleSignatureItems(plan.subtitles || []),
  });
}

async function ensureEditPlanForCurrentProject(options = {}) {
  if (!state.projectId) throw new Error("先に動画を読み込んでください");
  const currentSignature = editPlanRequestSignatureFromCurrent();
  const existingSignature = state.editPlanBuildSignature || editPlanRequestSignatureFromPlan(state.editPlan);
  if (!options.force && state.editPlanPath && state.editPlan && existingSignature === currentSignature) return state.editPlan;
  const data = await api("/api/edit-plan/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: state.projectId,
      source_range: currentRange(),
      silences: state.silences || [],
      transcript: transcriptForEditPlanRequest(),
      settings: settings(),
    }),
  });
  state.editPlanPath = data.edit_plan_path || state.editPlanPath || "edit_plan.json";
  state.editPlan = data.edit_plan || state.editPlan;
  state.editPlanBuildSignature = currentSignature;
  state.manualCutSegments = state.editPlan?.manual_cut_segments || state.manualCutSegments || [];
  state.protectedSegments = state.editPlan?.protected_segments || state.protectedSegments || [];
  renderSubtitles();
  renderWaveformEditor();
  drawTimeline();
  $("paths").textContent = state.editPlanPath;
  return state.editPlan;
}

function addManualSceneFromCurrentRange() {
  const range = currentRange();
  const startSec = Math.min(range.start_sec, range.end_sec);
  const endSec = Math.max(range.start_sec, range.end_sec);
  const sceneId = `scene_${String(Date.now()).slice(-8)}`;
  const emotion = $("defaultEmotionPreset")?.value || "neutral";
  const style = $("defaultSubtitleStylePreset")?.value || "subtitle_standard";
  state.projectScenes = [
    ...(state.projectScenes || []),
    {
      id: sceneId,
      start_sec: roundTime(startSec),
      end_sec: roundTime(endSec),
      emotion,
      effect_group_id: "",
      subtitle_style_preset_id: style,
      comment_ids: [],
    },
  ].sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
  saveProjectScenes().catch(() => {});
  renderScenes();
}

function resyncScenesFromSubtitles() {
  syncProjectScenesFromSubtitles();
  saveProjectScenes().catch(() => {});
  renderScenes();
}

function reassignSubtitlesToScenes() {
  const scenes = ((state.projectScenes || []).length ? state.projectScenes : state.presets.scenes || []).filter((scene) => scene.id);
  if (!scenes.length) return { reassigned: 0 };
  let reassigned = 0;
  for (const sub of subtitleItems()) {
    const start = Number(sub.start_sec ?? sub.output_start_sec ?? 0) || 0;
    const end = Number(sub.end_sec ?? sub.output_end_sec ?? start) || start;
    let bestScene = null;
    let bestScore = -1;
    let bestGap = Number.POSITIVE_INFINITY;
    for (const scene of scenes) {
      const sceneStart = Number(scene.start_sec) || 0;
      const sceneEnd = Number(scene.end_sec) || sceneStart;
      const overlap = Math.min(end, sceneEnd) - Math.max(start, sceneStart);
      const gap = overlap > 0 ? 0 : Math.max(sceneStart - end, start - sceneEnd);
      const score = overlap > 0 ? overlap : -gap;
      if (score > bestScore || (score === bestScore && gap < bestGap)) {
        bestScore = score;
        bestGap = gap;
        bestScene = scene;
      }
    }
    if (bestScene) {
      sub.scene_id = bestScene.id;
      if (bestScene.emotion) sub.emotion = bestScene.emotion;
      if (bestScene.subtitle_style_preset_id) sub.subtitle_style_preset_id = bestScene.subtitle_style_preset_id;
      reassigned += 1;
    }
  }
  syncProjectScenesFromSubtitles();
  return { reassigned };
}

function sceneListForEditing() {
  return sceneCatalog().slice().sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
}

function persistSceneAndSubtitleChanges() {
  syncProjectScenesFromSubtitles();
  saveProjectScenes().catch(() => {});
  persistCurrentSubtitles().catch(() => {});
  renderSubtitles();
  renderScenes();
  updateOverlay();
}

function splitSceneEntry(scene) {
  const scenes = sceneListForEditing();
  const index = scenes.findIndex((item) => item.id === scene.id);
  if (index < 0) return;
  const current = scenes[index];
  const splitAt = Math.max(current.start_sec + 0.05, Math.min(current.end_sec - 0.05, (current.start_sec + current.end_sec) / 2));
  const newId = `scene_${String(Date.now()).slice(-8)}`;
  const nextScene = {
    id: newId,
    start_sec: roundTime(splitAt),
    end_sec: roundTime(current.end_sec),
    emotion: current.emotion || "neutral",
    effect_group_id: current.effect_group_id || "",
    subtitle_style_preset_id: current.subtitle_style_preset_id || "",
    comment_ids: [],
  };
  const updatedCurrent = {
    ...current,
    end_sec: roundTime(splitAt),
    comment_ids: [],
  };
  const nextProjectScenes = (state.projectScenes || []).filter((item) => item.id !== current.id);
  nextProjectScenes.push(updatedCurrent, nextScene);
  state.projectScenes = nextProjectScenes.sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
  for (const sub of subtitleItems()) {
    const start = Number(sub.start_sec ?? sub.output_start_sec ?? 0) || 0;
    if (sub.scene_id === current.id && start >= splitAt) {
      sub.scene_id = newId;
      sub.emotion = nextScene.emotion;
      sub.subtitle_style_preset_id = nextScene.subtitle_style_preset_id;
    }
  }
  persistSceneAndSubtitleChanges();
}

function mergeSceneEntry(scene, direction = "prev") {
  const scenes = sceneListForEditing();
  const index = scenes.findIndex((item) => item.id === scene.id);
  if (index < 0) return;
  const neighbor = direction === "prev" ? scenes[index - 1] : scenes[index + 1];
  if (!neighbor) return;
  const target = direction === "prev" ? scene : neighbor;
  const source = direction === "prev" ? neighbor : scene;
  const merged = {
    ...target,
    start_sec: roundTime(Math.min(Number(target.start_sec) || 0, Number(source.start_sec) || 0)),
    end_sec: roundTime(Math.max(Number(target.end_sec) || 0, Number(source.end_sec) || 0)),
    emotion: target.emotion || source.emotion || "neutral",
    effect_group_id: target.effect_group_id || source.effect_group_id || "",
    subtitle_style_preset_id: target.subtitle_style_preset_id || source.subtitle_style_preset_id || "",
    comment_ids: [...new Set([...(target.comment_ids || []), ...(source.comment_ids || [])])],
  };
  state.projectScenes = (state.projectScenes || []).filter((item) => item.id !== target.id && item.id !== source.id);
  state.projectScenes.push(merged);
  for (const sub of subtitleItems()) {
    if (sub.scene_id === source.id) {
      sub.scene_id = target.id;
      sub.emotion = merged.emotion;
      sub.subtitle_style_preset_id = merged.subtitle_style_preset_id;
    }
  }
  persistSceneAndSubtitleChanges();
}

async function saveProjectSettings() {
  if (!state.projectId) return;
  const payload = {
    project_id: state.projectId,
    project_name: $("projectName")?.value?.trim() || state.projectName || state.projectId,
    default_emotion_preset_id: $("defaultEmotionPreset")?.value || "emotion_neutral",
    default_subtitle_style_preset_id: $("defaultSubtitleStylePreset")?.value || "subtitle_standard",
    output_profile: $("outputProfile")?.value || "mp4_compat",
    final_output_mode: $("finalOutputMode")?.value || "video_srt",
    audio_timing: audioTimingSettings(),
  };
  const data = await api("/api/projects/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.projectSettings = data.project?.ui_state || state.projectSettings;
  state.projectName = data.project?.project_name || payload.project_name || state.projectName;
  syncProjectSettingsForm();
  syncProjectNameInput(state.projectName);
  renderProjectLabel();
}

async function saveCurrentProject() {
  if (!state.projectId) throw new Error("先に動画を読み込んでください");
  await saveProjectSettings();
  if (subtitleItems().length) {
    await persistCurrentSubtitles();
  }
  await saveProjectScenes();
  if (state.decorationProject) {
    await saveDecorationProject();
  }
  if (state.appPage === "projects") {
    await loadProjectList().catch(() => {});
  }
}

function renderVideoInfo() {
  const parts = [];
  if (state.videoInfo) {
    parts.push(`動画情報\n${JSON.stringify(state.videoInfo, null, 2)}`);
  }
  if (state.processingSummary) {
    parts.push(`処理情報\n${JSON.stringify(state.processingSummary, null, 2)}`);
  }
  $("videoInfo").textContent = parts.length ? parts.join("\n\n") : "未取得";
  const body = $("videoInfoBody");
  const toggle = $("videoInfoToggleBtn");
  if (body) body.classList.toggle("hidden-panel", !state.videoInfoExpanded);
  if (toggle) toggle.textContent = state.videoInfoExpanded ? "折りたたむ" : "詳細を表示";
}

function emotionLabelForScene(sceneId, subtitles) {
  const found = (subtitles || []).find((sub) => sub.scene_id === sceneId && sub.emotion);
  return found?.emotion || "neutral";
}

function stylePresetForScene(sceneId, subtitles) {
  const found = (subtitles || []).find((sub) => sub.scene_id === sceneId && sub.subtitle_style_preset_id);
  return found?.subtitle_style_preset_id || "";
}

function subtitleSceneId(index) {
  return `scene_${String((Number(index) || 0) + 1).padStart(4, "0")}`;
}

function subtitleSceneLabel(index) {
  return `#${(Number(index) || 0) + 1}`;
}

function sceneCatalogFromSubtitles(subtitles) {
  return (subtitles || []).map((sub, index) => {
    const sceneId = subtitleSceneId(index);
    const start = Number(sub.start_sec ?? sub.output_start_sec ?? 0) || 0;
    const end = Number(sub.end_sec ?? sub.output_end_sec ?? start) || start;
    sub.scene_id = sceneId;
    return {
      id: sceneId,
      label: subtitleSceneLabel(index),
      start_sec: start,
      end_sec: end,
      emotion: sub.emotion || "neutral",
      effect_group_id: sub.effect_group_id || "",
      screen_effect_stack_ids: [...(sub.screen_effect_stack_ids || [])],
      subtitle_style_preset_id: sub.subtitle_style_preset_id || "",
      comment_ids: [sub.id || sub.subtitle_id || `sub_${String(index + 1).padStart(4, "0")}`],
      text: sub.text || "",
    };
  }).sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec || a.id.localeCompare(b.id));
}

function sceneCatalog() {
  const subtitles = subtitleItems();
  if (subtitles.length) return sceneCatalogFromSubtitles(subtitles);
  if (state.decorationProject?.events?.length) return sceneCatalogFromSubtitles(state.decorationProject.events.filter((item) => !isGlobalDecorationEvent(item)));
  return [];
}

function renderScenes() {
  const list = $("sceneList");
  if (!list) return;
  const scenes = sceneCatalog();
  const sceneCount = $("sceneCount");
  if (sceneCount) sceneCount.textContent = `${scenes.length}件`;
  list.textContent = "";
  scenes.forEach((scene) => {
    const item = document.createElement("div");
    item.className = `scene-item${scene.id === (selectedSubtitle()?.scene_id || "") ? " selected" : ""}`;
    const idx = document.createElement("strong");
    idx.textContent = scene.id;
    const meta = document.createElement("div");
    meta.className = "scene-meta";
    const title = document.createElement("span");
    title.textContent = `${fmtTime(scene.start_sec)} - ${fmtTime(scene.end_sec)}`;
    const subline = document.createElement("small");
    subline.textContent = `感情: ${emotionLabelForScene(scene.id, subtitleItems())} / スタイル: ${stylePresetForScene(scene.id, subtitleItems()) || "-"}`;
    meta.appendChild(title);
    meta.appendChild(subline);
    const action = document.createElement("span");
    action.textContent = `${scene.comment_ids?.length || 0}件`;
    const bounds = document.createElement("div");
    bounds.className = "scene-bounds";
    const startInput = document.createElement("input");
    startInput.dataset.sceneField = "start_sec";
    startInput.value = fmtTime(scene.start_sec);
    startInput.placeholder = "start";
    const endInput = document.createElement("input");
    endInput.dataset.sceneField = "end_sec";
    endInput.value = fmtTime(scene.end_sec);
    endInput.placeholder = "end";
    const setStartFromPreview = document.createElement("button");
    setStartFromPreview.type = "button";
    setStartFromPreview.textContent = "現在値を開始へ";
    setStartFromPreview.addEventListener("click", (event) => {
      event.stopPropagation();
      startInput.value = fmtTime(video.currentTime || 0);
    });
    const setEndFromPreview = document.createElement("button");
    setEndFromPreview.type = "button";
    setEndFromPreview.textContent = "現在値を終了へ";
    setEndFromPreview.addEventListener("click", (event) => {
      event.stopPropagation();
      endInput.value = fmtTime(video.currentTime || 0);
    });
    const updateBounds = document.createElement("button");
    updateBounds.type = "button";
    updateBounds.textContent = "区間保存";
    updateBounds.addEventListener("click", (event) => {
      event.stopPropagation();
      const nextStart = parseTime(startInput.value);
      const nextEnd = parseTime(endInput.value);
      const safeStart = Math.min(nextStart, nextEnd);
      const safeEnd = Math.max(nextStart, nextEnd);
      state.projectScenes = (state.projectScenes || []).map((item) =>
        item.id === scene.id
          ? { ...item, start_sec: roundTime(safeStart), end_sec: roundTime(safeEnd) }
          : item,
      );
      syncProjectScenesFromSubtitles();
      saveProjectScenes().catch(() => {});
      renderScenes();
    });
    bounds.appendChild(startInput);
    bounds.appendChild(endInput);
    bounds.appendChild(setStartFromPreview);
    bounds.appendChild(setEndFromPreview);
    bounds.appendChild(updateBounds);
    const sceneControls = document.createElement("div");
    sceneControls.className = "scene-controls";
    const sceneEmotion = presetOptions(
      (state.presets.emotion_labels || []).map((emotion) => ({ id: emotion, name: emotion })),
      scene.emotion || "neutral",
      "",
    );
    sceneEmotion.dataset.sceneField = "emotion";
    const sceneStyle = presetOptions(
      state.presets.subtitle_style_presets || [],
      scene.subtitle_style_preset_id || "",
      "",
    );
    sceneStyle.dataset.sceneField = "subtitle_style_preset_id";
    const sceneSave = document.createElement("button");
    sceneSave.type = "button";
    sceneSave.textContent = "保存";
    sceneSave.addEventListener("click", (event) => {
      event.stopPropagation();
      const nextEmotion = sceneEmotion.value || "neutral";
      const nextStyle = sceneStyle.value || "";
      const nextScenes = (state.projectScenes || []).filter((item) => item.id !== scene.id);
      nextScenes.push({
        ...scene,
        emotion: nextEmotion,
        subtitle_style_preset_id: nextStyle,
      });
      state.projectScenes = nextScenes.sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
      for (const sub of subtitleItems()) {
        if (sub.scene_id === scene.id) {
          sub.emotion = nextEmotion;
          sub.subtitle_style_preset_id = nextStyle;
        }
      }
      persistCurrentSubtitles().catch(() => {});
      saveProjectScenes().catch(() => {});
      renderSubtitles();
      updateOverlay();
    });
    sceneControls.appendChild(sceneEmotion);
    sceneControls.appendChild(sceneStyle);
    sceneControls.appendChild(sceneSave);
    const splitBtn = document.createElement("button");
    splitBtn.type = "button";
    splitBtn.textContent = "分割";
    splitBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      splitSceneEntry(scene);
    });
    const mergePrevBtn = document.createElement("button");
    mergePrevBtn.type = "button";
    mergePrevBtn.textContent = "前に結合";
    mergePrevBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      mergeSceneEntry(scene, "prev");
    });
    const mergeNextBtn = document.createElement("button");
    mergeNextBtn.type = "button";
    mergeNextBtn.textContent = "次に結合";
    mergeNextBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      mergeSceneEntry(scene, "next");
    });
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.textContent = "反映";
    applyBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      const emotion = $("defaultEmotionPreset")?.value || "neutral";
      const style = $("defaultSubtitleStylePreset")?.value || "subtitle_standard";
      for (const sub of subtitleItems()) {
        if (sub.scene_id === scene.id) {
          sub.emotion = emotion;
          sub.subtitle_style_preset_id = style;
        }
      }
      renderSubtitles();
      updateOverlay();
    });
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "削除";
    removeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      state.projectScenes = (state.projectScenes || []).filter((item) => item.id !== scene.id);
      for (const sub of subtitleItems()) {
        if (sub.scene_id === scene.id) {
          sub.scene_id = "";
        }
      }
      persistCurrentSubtitles().catch(() => {});
      saveProjectScenes().catch(() => {});
      renderSubtitles();
      updateOverlay();
    });
    const sceneOps = document.createElement("div");
    sceneOps.className = "scene-ops";
    sceneOps.appendChild(splitBtn);
    sceneOps.appendChild(mergePrevBtn);
    sceneOps.appendChild(mergeNextBtn);
    sceneOps.appendChild(applyBtn);
    sceneOps.appendChild(removeBtn);
    item.appendChild(idx);
    item.appendChild(meta);
    item.appendChild(action);
    item.appendChild(bounds);
    item.appendChild(sceneControls);
    item.appendChild(sceneOps);
    item.addEventListener("click", () => {
      const first = subtitleItems().find((sub) => sub.scene_id === scene.id);
      if (first) {
        state.selectedSubtitleId = first.id;
        state.loopSubtitleId = first.id;
        seekToSubtitle(first);
      } else {
        video.currentTime = Math.min(video.duration || 0, Number(scene.start_sec) || 0);
      }
      renderScenes();
      renderSubtitles();
    });
    list.appendChild(item);
  });
}

function setAppPage(page) {
  if (page === "scenes") page = "editor";
  const previousPage = state.appPage;
  state.appPage = page;
  if (page === "subtitles" && video && !video.paused) video.pause();
  if (previousPage === "subtitles" && page !== "subtitles" && subtitlePageVideo && !subtitlePageVideo.paused) subtitlePageVideo.pause();
  if (page === "previewCheck" && subtitlePageVideo && !subtitlePageVideo.paused) subtitlePageVideo.pause();
  updatePreviewAudioRouting();
  $("editorPageBtn").classList.toggle("active", page === "editor");
  $("subtitlePageBtn").classList.toggle("active", page === "subtitles");
  $("projectListPageBtn").classList.toggle("active", page === "projects");
  $("settingsPageBtn").classList.toggle("active", page === "settings");
  $("decorationPageBtn").classList.toggle("active", page === "decoration");
  $("previewCheckPageBtn").classList.toggle("active", page === "previewCheck");
  const mainLayout = document.querySelector("main.layout");
  if (mainLayout) mainLayout.classList.toggle("hidden-panel", page !== "editor");
  $("videoShellWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorControlsWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorModeWrap").classList.toggle("hidden-panel", page !== "editor");
  $("processWrap").classList.toggle("hidden-panel", page !== "editor");
  $("workspaceWrap").classList.toggle("hidden-panel", page !== "editor");
  $("subtitle-panel")?.classList.add("hidden-panel");
  $("subtitlePage")?.classList.toggle("hidden-panel", page !== "subtitles");
  $("projectListPage").classList.toggle("hidden-panel", page !== "projects");
  $("settingsPage").classList.toggle("hidden-panel", page !== "settings");
  $("decorationPage").classList.toggle("hidden-panel", page !== "decoration");
  $("previewCheckPage")?.classList.toggle("hidden-panel", page !== "previewCheck");
  const isDecorationWorkspace = page === "decoration" || page === "previewCheck";
  if (isDecorationWorkspace && !(state.decorationProject?.events?.length) && subtitleItems().length) {
    buildDecorationProjectFromSubtitles();
  } else if (isDecorationWorkspace && state.decorationProject?.events?.length && subtitleItems().length) {
    syncDecorationEventsFromSubtitles({ path: state.decorationProject.source_srt, subtitles: decorationSourceSubtitles() });
  }
  if (page === "projects") {
    renderProjectListPage();
  }
  if (page === "subtitles") {
    renderSubtitles();
  }
  if (page === "subtitles") {
    syncAllMirroredPreviews();
  }
  if (page === "decoration" || page === "previewCheck") renderDecorationPage();
  if (page === "previewCheck") {
    updateDecorationPreviewFilters();
    renderDecorationShaderFrame();
  }
  updateZoomBoxOverlay();
  window.scrollTo(0, 0);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    throw new Error(data.detail || "APIエラー");
  }
  return data;
}

async function runStep(label, fn) {
  let succeeded = false;
  try {
    setBusy(true);
    startTaskProgress(label);
    setStatus(`${label}中...`);
    const result = await fn();
    succeeded = true;
    setStatus(`${label}が完了しました`);
    return result;
  } catch (err) {
    setStatus(err.message || String(err), true);
    return null;
  } finally {
    finishTaskProgress(succeeded);
    setBusy(false);
  }
}

function parseTime(value) {
  const text = String(value).trim();
  if (!text.includes(":")) return Number(text || 0);
  const [h, m, s] = text.split(":");
  return Number(h) * 3600 + Number(m) * 60 + Number(s);
}

function fmtTime(sec) {
  sec = Math.max(0, Number(sec) || 0);
  const ms = Math.round(sec * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const milli = ms % 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(milli).padStart(3, "0")}`;
}

function settings() {
  const timing = audioTimingSettings();
  return {
    compute_profile: $("computeProfile").value,
    ...timing,
    default_emotion_preset_id: $("defaultEmotionPreset")?.value || "emotion_neutral",
    default_subtitle_style_preset_id: $("defaultSubtitleStylePreset")?.value || "subtitle_standard",
    output_profile: $("outputProfile")?.value || "mp4_compat",
    final_output_mode: $("finalOutputMode")?.value || "video_srt",
    subtitle_font_name: $("subtitleFontName").value.trim() || "Meiryo",
    subtitle_font_size: Number($("subtitleFontSize").value) || 42,
    subtitle_outline_width: Number($("subtitleOutlineWidth").value) || 0,
    manual_cut_segments: normalizeIntervalList(state.manualCutSegments),
    protected_segments: normalizeIntervalList(state.protectedSegments),
  };
}

function currentRange() {
  const start = parseTime($("startTime").value);
  const end = parseTime($("endTime").value);
  if (end <= start) throw new Error("終了時間は開始時間より後にしてください");
  return { start_sec: start, end_sec: end };
}

function buildSourceRanges(duration, splitMinutes = 20) {
  const total = Math.max(0, Number(duration) || 0);
  const chunk = Math.max(10, Math.min(30, Number(splitMinutes) || 20)) * 60;
  if (!total || total <= chunk) {
    return [{ id: "src_001", start_sec: 0, end_sec: total || 0 }];
  }
  const ranges = [];
  let cursor = 0;
  let index = 1;
  while (cursor < total) {
    const end = Math.min(total, cursor + chunk);
    ranges.push({ id: `src_${String(index).padStart(3, "0")}`, start_sec: roundTime(cursor), end_sec: roundTime(end) });
    cursor = end;
    index += 1;
  }
  return ranges;
}

function roundTime(value) {
  return Math.round((Number(value) || 0) * 1000) / 1000;
}

function defaultZoomBoxPresets() {
  return [
    { id: "wide_133", name: "ワイド 1.33x", centerX: 0.5, centerY: 0.5, widthRatio: 0.75 },
    { id: "medium_178", name: "標準 1.78x", centerX: 0.5, centerY: 0.5, widthRatio: 0.5625 },
    { id: "close_238", name: "寄り 2.38x", centerX: 0.5, centerY: 0.5, widthRatio: 0.42 },
    { id: "face_top", name: "上寄せ 1.78x", centerX: 0.5, centerY: 0.38, widthRatio: 0.5625 },
    { id: "left_focus", name: "左寄せ 1.78x", centerX: 0.35, centerY: 0.5, widthRatio: 0.5625 },
    { id: "right_focus", name: "右寄せ 1.78x", centerX: 0.65, centerY: 0.5, widthRatio: 0.5625 },
  ];
}

function customZoomBoxPresets() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ZOOM_BOX_PRESETS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function zoomBoxPresets() {
  return [...defaultZoomBoxPresets(), ...customZoomBoxPresets()];
}

function saveCustomZoomBoxPreset(preset) {
  const current = customZoomBoxPresets();
  current.push({
    id: preset.id || `zoom_box_${Date.now()}`,
    name: preset.name || "拡大枠プリセット",
    centerX: Math.max(0, Math.min(1, Number(preset.centerX) || 0.5)),
    centerY: Math.max(0, Math.min(1, Number(preset.centerY) || 0.5)),
    widthRatio: Math.max(0.2, Math.min(1, Number(preset.widthRatio) || 0.75)),
  });
  localStorage.setItem(ZOOM_BOX_PRESETS_KEY, JSON.stringify(current));
}

function clampZoomBox(box = state.zoomBox) {
  const widthRatio = Math.max(0.2, Math.min(1, Number(box.widthRatio) || 0.75));
  const heightRatio = widthRatio * 9 / 16;
  return {
    active: box.active !== false,
    centerX: Math.max(widthRatio / 2, Math.min(1 - widthRatio / 2, Number(box.centerX) || 0.5)),
    centerY: Math.max(heightRatio / 2, Math.min(1 - heightRatio / 2, Number(box.centerY) || 0.5)),
    widthRatio,
  };
}

function syncZoomInputsFromBox() {
  const box = clampZoomBox();
  const zoomScale = $("zoomBoxScaleInput");
  const zoomX = $("zoomBoxXInput");
  const zoomY = $("zoomBoxYInput");
  if (zoomScale) zoomScale.value = (1 / box.widthRatio).toFixed(2);
  if (zoomX) zoomX.value = box.centerX.toFixed(2);
  if (zoomY) zoomY.value = box.centerY.toFixed(2);
}

function updateZoomBoxOverlay() {
  const overlay = $("zoomBoxOverlay");
  const frame = $("zoomBoxFrame");
  const stage = $("decorationPreviewStage");
  const previewVideo = $("decorationPreviewVideo");
  if (!overlay || !frame || !stage || !previewVideo) return;
  const visible = state.decorationEditTab === "zoom" && state.appPage === "previewCheck";
  overlay.classList.toggle("hidden-panel", !visible);
  if (!visible) return;
  const stageRect = stage.getBoundingClientRect();
  const videoRect = previewVideo.getBoundingClientRect();
  const left = Math.max(0, videoRect.left - stageRect.left);
  const top = Math.max(0, videoRect.top - stageRect.top);
  const width = Math.max(1, videoRect.width);
  const height = Math.max(1, videoRect.height);
  overlay.style.left = `${left}px`;
  overlay.style.top = `${top}px`;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  overlay.style.right = "auto";
  overlay.style.bottom = "auto";
  state.zoomBox = clampZoomBox(state.zoomBox);
  const box = state.zoomBox;
  const frameWidth = width * box.widthRatio;
  const frameHeight = frameWidth * 9 / 16;
  frame.style.left = `${box.centerX * width}px`;
  frame.style.top = `${box.centerY * height}px`;
  frame.style.width = `${frameWidth}px`;
  frame.style.height = `${frameHeight}px`;
  syncZoomInputsFromBox();
}

function setZoomBoxFromInputs() {
  state.zoomBox = clampZoomBox({
    active: true,
    centerX: Number($("zoomBoxXInput")?.value) || state.zoomBox.centerX,
    centerY: Number($("zoomBoxYInput")?.value) || state.zoomBox.centerY,
    widthRatio: 1 / Math.max(0.25, Math.min(5, Number($("zoomBoxScaleInput")?.value) || 1.25)),
  });
  updateZoomBoxOverlay();
}

function bindZoomBoxOverlayInteraction() {
  const overlay = $("zoomBoxOverlay");
  const frame = $("zoomBoxFrame");
  const handle = $("zoomBoxHandle");
  if (!overlay || !frame || !handle || overlay.dataset.bound === "1") return;
  overlay.dataset.bound = "1";
  let dragMode = "";
  let startPointer = null;
  let startBox = null;
  const normalizedPoint = (event) => {
    const rect = overlay.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width))),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / Math.max(1, rect.height))),
    };
  };
  const beginDrag = (event, mode) => {
    event.preventDefault();
    event.stopPropagation();
    dragMode = mode;
    startPointer = normalizedPoint(event);
    startBox = clampZoomBox(state.zoomBox);
    overlay.setPointerCapture?.(event.pointerId);
  };
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === handle) {
      beginDrag(event, "resize");
      return;
    }
    if (event.target === frame || frame.contains(event.target)) {
      beginDrag(event, "move");
      return;
    }
    const point = normalizedPoint(event);
    state.zoomBox = clampZoomBox({ ...state.zoomBox, active: true, centerX: point.x, centerY: point.y });
    updateZoomBoxOverlay();
  });
  overlay.addEventListener("pointermove", (event) => {
    if (!dragMode || !startPointer || !startBox) return;
    const point = normalizedPoint(event);
    if (dragMode === "move") {
      state.zoomBox = clampZoomBox({
        ...startBox,
        centerX: startBox.centerX + (point.x - startPointer.x),
        centerY: startBox.centerY + (point.y - startPointer.y),
      });
    } else if (dragMode === "resize") {
      const maxWidthByX = Math.max(0.2, 2 * Math.min(startBox.centerX, 1 - startBox.centerX));
      const maxWidthByY = Math.max(0.2, 2 * Math.min(startBox.centerY, 1 - startBox.centerY) * 16 / 9);
      const maxWidth = Math.max(0.2, Math.min(1, maxWidthByX, maxWidthByY));
      const nextWidth = Math.max(0.2, Math.min(maxWidth, Math.abs(point.x - startBox.centerX) * 2));
      state.zoomBox = clampZoomBox({ ...startBox, widthRatio: nextWidth });
    }
    updateZoomBoxOverlay();
  });
  const endDrag = (event) => {
    if (!dragMode) return;
    overlay.releasePointerCapture?.(event.pointerId);
    dragMode = "";
    startPointer = null;
    startBox = null;
  };
  overlay.addEventListener("pointerup", endDrag);
  overlay.addEventListener("pointercancel", endDrag);
  window.addEventListener("resize", updateZoomBoxOverlay);
}

function setSourceRanges(ranges, selectIndex = 0) {
  state.sourceRanges = normalizeIntervalList(
    (ranges || []).map((item) => ({ src_start: item.start_sec, src_end: item.end_sec })),
  ).map((item, index) => ({ id: `src_${String(index + 1).padStart(3, "0")}`, start_sec: item.src_start, end_sec: item.src_end }));
  state.selectedSourceRangeIndex = Math.min(Math.max(0, selectIndex), Math.max(0, state.sourceRanges.length - 1));
  renderSourceRanges();
}

function selectSourceRange(index) {
  if (!state.sourceRanges.length) return;
  const item = state.sourceRanges[Math.min(Math.max(0, index), state.sourceRanges.length - 1)];
  if (!item) return;
  state.selectedSourceRangeIndex = index;
  $("startTime").value = fmtTime(item.start_sec);
  $("endTime").value = fmtTime(item.end_sec);
  renderSourceRanges();
}

function restoreProjectSourceRange(durationSec) {
  const planRange = state.editPlan?.source_range || null;
  const splitMinutes = Number($("splitMinutes")?.value) || 20;
  const ranges = buildSourceRanges(durationSec, splitMinutes);
  if (!planRange || !(Number(planRange.end_sec) > Number(planRange.start_sec))) {
    setSourceRanges(ranges, 0);
    selectSourceRange(0);
    return;
  }
  const restored = {
    id: "src_current",
    start_sec: roundTime(Number(planRange.start_sec) || 0),
    end_sec: roundTime(Number(planRange.end_sec) || 0),
  };
  const exactIndex = ranges.findIndex(
    (item) => Math.abs(Number(item.start_sec) - restored.start_sec) < 0.001 && Math.abs(Number(item.end_sec) - restored.end_sec) < 0.001,
  );
  const nextRanges = exactIndex >= 0 ? ranges : [restored, ...ranges];
  setSourceRanges(nextRanges, exactIndex >= 0 ? exactIndex : 0);
  const restoredIndex = state.sourceRanges.findIndex(
    (item) => Math.abs(Number(item.start_sec) - restored.start_sec) < 0.001 && Math.abs(Number(item.end_sec) - restored.end_sec) < 0.001,
  );
  selectSourceRange(restoredIndex >= 0 ? restoredIndex : 0);
}

function applyCurrentRangeToSelection() {
  const range = currentRange();
  const normalized = {
    start_sec: roundTime(range.start_sec),
    end_sec: roundTime(range.end_sec),
  };
  if (!state.sourceRanges.length) {
    setSourceRanges([{ start_sec: normalized.start_sec, end_sec: normalized.end_sec }], 0);
    return;
  }
  if (state.selectedSourceRangeIndex >= 0 && state.selectedSourceRangeIndex < state.sourceRanges.length) {
    state.sourceRanges[state.selectedSourceRangeIndex] = {
      ...state.sourceRanges[state.selectedSourceRangeIndex],
      ...normalized,
    };
  } else {
    state.sourceRanges.push({
      id: `src_${String(state.sourceRanges.length + 1).padStart(3, "0")}`,
      ...normalized,
    });
    state.selectedSourceRangeIndex = state.sourceRanges.length - 1;
  }
  renderSourceRanges();
}

function renderSourceRanges() {
  const list = $("sourceRangeList");
  if (!list) return;
  list.textContent = "";
  $("sourceRangeCount").textContent = `${state.sourceRanges.length}件`;
  state.sourceRanges.forEach((item, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `source-range-item${index === state.selectedSourceRangeIndex ? " selected" : ""}`;
    const indexEl = document.createElement("strong");
    indexEl.textContent = `#${index + 1}`;
    const label = document.createElement("span");
    label.textContent = `${fmtTime(item.start_sec)} - ${fmtTime(item.end_sec)}`;
    const duration = document.createElement("span");
    duration.textContent = `${Math.max(0, item.end_sec - item.start_sec).toFixed(1)}s`;
    row.appendChild(indexEl);
    row.appendChild(label);
    row.appendChild(duration);
    row.addEventListener("click", () => selectSourceRange(index));
    list.appendChild(row);
  });
}

async function ensureAudioExtracted() {
  requireProject();
  if (state.audioPath) return state.audioPath;
  const range = currentRange();
  const data = await api("/api/audio/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: state.projectId, video_path: state.sourceVideo, compute_profile: $("computeProfile").value, ...range }),
  });
  state.audioPath = data.audio_path;
  $("paths").textContent = data.audio_path;
  return state.audioPath;
}

function requireProject() {
  if (!state.projectId || !state.sourceVideo) throw new Error("先に動画を読み込んでください");
}

function activeSubtitles() {
  return (state.editPlan?.subtitles || state.transcript?.subtitles || []).filter((sub) => sub.enabled !== false);
}

function subtitleBoundsForMode(sub, mode = state.mode) {
  const sourceMode = mode === "source";
  const start = sourceMode
    ? Number(sub.range_relative_start_sec ?? sub.start_sec ?? sub.output_start_sec ?? 0) || 0
    : Number(sub.output_start_sec ?? sub.start_sec ?? sub.range_relative_start_sec ?? 0) || 0;
  const end = sourceMode
    ? Number(sub.range_relative_end_sec ?? sub.end_sec ?? sub.output_end_sec ?? start) || start
    : Number(sub.output_end_sec ?? sub.end_sec ?? sub.range_relative_end_sec ?? start) || start;
  return { start, end: Math.max(start, end) };
}

function subtitleAtTimelineTime(timeSec, mode = state.mode) {
  const t = Math.max(0, Number(timeSec) || 0);
  return activeSubtitles().find((sub) => {
    const { start, end } = subtitleBoundsForMode(sub, mode);
    return t >= start && t <= end;
  }) || null;
}

function subtitleAtTime(timeSec = video.currentTime) {
  return subtitleAtTimelineTime(timeSec, state.mode);
}

function sourceRangeBounds() {
  const start = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  const end = state.editPlan?.source_range?.end_sec ?? parseTime($("endTime").value);
  return { start, end, duration: Math.max(0.001, end - start) };
}

function audioSettings() {
  const timing = audioTimingSettings();
  return {
    compute_profile: $("computeProfile").value,
    ...timing,
  };
}

function syncAudioSettingsControls() {
  const enabled = $("voiceIsolationEnabled").checked;
  $("useIsolatedVoiceForVad").disabled = !enabled;
  $("useIsolatedVoiceForWhisper").disabled = !enabled;
  if (!enabled) {
    $("useIsolatedVoiceForVad").checked = false;
    $("useIsolatedVoiceForWhisper").checked = false;
  } else if (!$("useIsolatedVoiceForVad").checked && !$("useIsolatedVoiceForWhisper").checked) {
    $("useIsolatedVoiceForVad").checked = true;
  }
}

function normalizeIntervalList(intervals) {
  return (intervals || [])
    .map((item) => ({
      src_start: Math.min(Number(item.src_start) || 0, Number(item.src_end) || 0),
      src_end: Math.max(Number(item.src_start) || 0, Number(item.src_end) || 0),
    }))
    .filter((item) => Number.isFinite(item.src_start) && Number.isFinite(item.src_end) && item.src_end > item.src_start)
    .sort((a, b) => a.src_start - b.src_start || a.src_end - b.src_end);
}

function formatInterval(interval) {
  return `${fmtTime(interval.src_start)} - ${fmtTime(interval.src_end)}`;
}

function waveformIntervals() {
  const manual = state.manualCutSegments?.length ? state.manualCutSegments : (state.editPlan?.manual_cut_segments || []);
  return { manual: normalizeIntervalList(manual) };
}

function subtractIntervals(baseIntervals, removeIntervals) {
  const bases = normalizeIntervalList(baseIntervals);
  const removals = normalizeIntervalList(removeIntervals);
  if (!bases.length) return [];
  if (!removals.length) return bases;
  const result = [];
  for (const base of bases) {
    let cursor = base.src_start;
    for (const removal of removals) {
      if (removal.src_end <= cursor) continue;
      if (removal.src_start >= base.src_end) break;
      if (removal.src_start > cursor) {
        result.push({ src_start: cursor, src_end: Math.min(removal.src_start, base.src_end) });
      }
      cursor = Math.max(cursor, removal.src_end);
      if (cursor >= base.src_end) break;
    }
    if (cursor < base.src_end) {
      result.push({ src_start: cursor, src_end: base.src_end });
    }
  }
  return normalizeIntervalList(result);
}

function sourceRelativeTime(media = video) {
  const rangeStart = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  return Math.max(0, (media?.currentTime || 0) - rangeStart);
}

function plannedOutputTimeFromVideo(media = video) {
  if (!state.editPlan) return 0;
  const rel = sourceRelativeTime(media);
  let elapsed = 0;
  for (const seg of state.editPlan.segments || []) {
    if (seg.enabled === false) continue;
    if (rel >= seg.range_relative_start_sec && rel <= seg.range_relative_end_sec) {
      return elapsed + (rel - seg.range_relative_start_sec);
    }
    elapsed += seg.range_relative_end_sec - seg.range_relative_start_sec;
  }
  return elapsed;
}

function sourceMediaTimeFromOutputTime(outputTimeSec) {
  const outputTime = Math.max(0, Number(outputTimeSec) || 0);
  const rangeStart = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  if (!state.editPlan?.segments?.length) return rangeStart + outputTime;
  for (const seg of state.editPlan.segments || []) {
    if (seg.enabled === false) continue;
    const outStart = Number(seg.output_start_sec) || 0;
    const outEnd = Number(seg.output_end_sec) || outStart;
    if (outputTime >= outStart && outputTime <= outEnd) {
      return rangeStart + (Number(seg.range_relative_start_sec) || 0) + (outputTime - outStart);
    }
  }
  const enabledSegments = (state.editPlan.segments || []).filter((seg) => seg.enabled !== false);
  const last = enabledSegments[enabledSegments.length - 1];
  if (!last) return rangeStart + outputTime;
  return rangeStart + (Number(last.range_relative_end_sec) || 0);
}

function plannedOutputDuration() {
  const plan = state.editPlan;
  if (!plan) return Math.max(1, video.duration || 1);
  return Math.max(
    0.1,
    ...[...(plan.segments || []).map((seg) => Number(seg.output_end_sec) || 0), ...(plan.subtitles || []).map((sub) => Number(sub.output_end_sec) || 0)],
  );
}

function subtitleTimebase(media = video) {
  if (state.mode === "source") return sourceRelativeTime(media);
  if (state.mode === "planned") return plannedOutputTimeFromVideo(media);
  return media?.currentTime || 0;
}

function updateOverlay() {
  const mainMedia = primaryPlaybackVideo();
  const t = subtitleTimebase(mainMedia);
  const sub = subtitleAtTimelineTime(t, state.mode);
  $("subtitleOverlay").textContent = sub ? (sub.speaker_label ? `${sub.speaker_label}: ${sub.text}` : sub.text) : "";
  const subtitlePageT = subtitlePageVideo ? subtitleTimebase(subtitlePageVideo) : t;
  const overlaySub = subtitleAtTimelineTime(subtitlePageT, state.mode) || sub || subtitleAtTime(video.currentTime);
  const subtitlePageOverlay = $("subtitlePagePreviewOverlay");
  if (subtitlePageOverlay) subtitlePageOverlay.textContent = overlaySub ? (overlaySub.speaker_label ? `${overlaySub.speaker_label}: ${overlaySub.text}` : overlaySub.text) : "";
  $("timeReadout").textContent = fmtTime(t);
  if (state.editorView === "waveform") updateWaveformPlayhead();
  drawTimeline();
}

function subtitleRangeInCurrentMode(sub) {
  const rangeStart = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  if (state.mode === "rendered") {
    return {
      start: Number(sub.output_start_sec) || 0,
      end: Number(sub.output_end_sec) || Number(sub.output_start_sec) || 0,
    };
  }
  return {
    start: rangeStart + (Number(sub.range_relative_start_sec ?? sub.output_start_sec) || 0),
    end: rangeStart + (Number(sub.range_relative_end_sec ?? sub.output_end_sec) || 0),
  };
}

function subtitlePlaybackRange(sub) {
  const startOutput = Number(sub.output_start_sec ?? sub.start_sec ?? sub.range_relative_start_sec ?? 0) || 0;
  const endOutput = Math.max(startOutput, Number(sub.output_end_sec ?? sub.end_sec ?? sub.range_relative_end_sec ?? startOutput) || startOutput);
  if (state.mode === "rendered") {
    return { start: startOutput, end: endOutput };
  }
  return {
    start: sourceMediaTimeFromOutputTime(startOutput),
    end: sourceMediaTimeFromOutputTime(endOutput),
  };
}

function currentSubtitleEditTime() {
  return Math.max(0, subtitleTimebase(primaryPlaybackVideo()));
}

function selectedDecorationPreviewWindow() {
  const selectedEvent = currentDecorationEvent && currentDecorationEvent();
  const selectedSub = selectedSubtitle();
  const target = selectedEvent && !isGlobalDecorationEvent(selectedEvent) ? selectedEvent : selectedSub;
  if (!target) return null;
  const rawStart = Number(target.start_sec ?? target.output_start_sec ?? target.range_relative_start_sec ?? 0) || 0;
  const rawEnd = Number(target.end_sec ?? target.output_end_sec ?? target.range_relative_end_sec ?? rawStart + 5) || rawStart + 5;
  const start = Math.max(0, rawStart - 1.0);
  const end = Math.max(start + 5.0, rawEnd + 1.0);
  return {
    start_sec: start,
    duration_sec: Math.min(60, end - start),
    label: target.text ? String(target.text).slice(0, 24) : target.id || "現在字幕",
  };
}

function loopSubtitleTick() {
  const media = primaryPlaybackVideo();
  if (!state.loopSubtitleId || media.paused) return;
  const sub = activeSubtitles().find((item) => item.id === state.loopSubtitleId);
  if (!sub) return;
  const { start, end } = subtitlePlaybackRange(sub);
  if (media.currentTime < start) {
    media.currentTime = start;
    return;
  }
  if (media.currentTime >= end - 0.03) {
    media.currentTime = start;
    media.play().catch(() => {});
  }
}

function waveformLoopTick() {
  const range = state.waveformLoopRange;
  if (!range || video.paused) return;
  if (video.currentTime < range.start) {
    video.currentTime = range.start;
    return;
  }
  if (video.currentTime >= range.end - 0.03) {
    video.currentTime = range.start;
    video.play().catch(() => {});
  }
}

function updateWaveformPlayhead() {
  const overlay = $("waveformOverlay");
  if (!overlay) return;
  let playhead = overlay.querySelector(".waveform-playhead");
  if (!playhead) {
    playhead = document.createElement("div");
    playhead.className = "waveform-playhead";
    overlay.appendChild(playhead);
  }
  const { start, duration } = sourceRangeBounds();
  const rel = Math.max(0, video.currentTime - start);
  playhead.style.left = `${Math.min(100, Math.max(0, (rel / duration) * 100))}%`;
}

function seekToSubtitle(sub) {
  const media = primaryPlaybackVideo();
  state.selectedSubtitleId = sub.id;
  state.loopSubtitleId = sub.id;
  media.currentTime = subtitlePlaybackRange(sub).start;
  renderSubtitles();
  media.play().catch(() => {});
}

function renderSubtitles() {
  const list = state.appPage === "subtitles" ? $("subtitleListPage") : ($("subtitleList") || $("subtitleListPage"));
  const subtitles = subtitleItems();
  const subtitleCount = state.appPage === "subtitles" ? $("subtitleCountPage") : $("subtitleCount");
  if (subtitleCount) subtitleCount.textContent = `${subtitles.length}件`;
  const subtitleCountPage = $("subtitleCountPage");
  if (subtitleCountPage && subtitleCountPage !== subtitleCount) subtitleCountPage.textContent = `${subtitles.length}件`;
  if (!list) return;
  list.textContent = "";
  const selectedSub = subtitles.find((item) => item.id === state.selectedSubtitleId) || subtitles[0] || null;
  const selectedDeco = decorationEventForSubtitle(selectedSub);
  if (selectedDeco) {
    const preview = buildDecorationPreviewNode(selectedDeco, { compact: true, includeMeta: false, includeChips: true });
    if (preview) {
      preview.classList.add("subtitle-preview-sync");
      preview.style.margin = "0 0 12px 0";
      list.appendChild(preview);
    }
  }
  subtitles.forEach((sub, index) => {
    const item = document.createElement("div");
    item.className = `subtitle-item${sub.id === state.selectedSubtitleId ? " selected" : ""}`;
    const meta = document.createElement("div");
    meta.className = "subtitle-meta";

    const strong = document.createElement("strong");
    strong.textContent = `#${index + 1}`;
    meta.appendChild(strong);

    const speakerInput = document.createElement("input");
    speakerInput.dataset.field = "speaker_label";
    speakerInput.value = sub.speaker_label || sub.speaker_id || "";
    speakerInput.placeholder = "speaker";
    meta.appendChild(speakerInput);

    const sceneInput = document.createElement("input");
    sceneInput.dataset.field = "scene_id";
    sceneInput.value = sub.scene_id || "";
    sceneInput.placeholder = "scene";
    meta.appendChild(sceneInput);

    const startInput = document.createElement("input");
    startInput.dataset.field = "output_start_sec";
    startInput.value = fmtTime(sub.output_start_sec);
    meta.appendChild(startInput);

    const endInput = document.createElement("input");
    endInput.dataset.field = "output_end_sec";
    endInput.value = fmtTime(sub.output_end_sec);
    meta.appendChild(endInput);

    const enabledLabel = document.createElement("label");
    const enabledInput = document.createElement("input");
    enabledInput.dataset.field = "enabled";
    enabledInput.type = "checkbox";
    enabledInput.checked = sub.enabled !== false;
    enabledLabel.appendChild(enabledInput);
    enabledLabel.appendChild(document.createTextNode(" 有効"));
    meta.appendChild(enabledLabel);

    const speakerInfo = document.createElement("div");
    speakerInfo.className = "subtitle-speaker-info";
    const confidenceText = sub.speaker_confidence != null ? ` / ${Math.round((Number(sub.speaker_confidence) || 0) * 100)}%` : "";
    speakerInfo.textContent = `${sub.speaker_id || ""}${confidenceText}`;

    const timeInfo = document.createElement("div");
    timeInfo.className = "subtitle-time-info";
    timeInfo.textContent = `元: ${fmtTime(sub.original_start_sec ?? sub.source_start_sec ?? sub.output_start_sec)} - ${fmtTime(sub.original_end_sec ?? sub.source_end_sec ?? sub.output_end_sec)} / 出力: ${fmtTime(sub.output_start_sec)} - ${fmtTime(sub.output_end_sec)}`;

    const textarea = document.createElement("textarea");
    textarea.dataset.field = "text";
    textarea.value = sub.text || "";

    const actions = document.createElement("div");
    actions.className = "subtitle-actions";
    [
      ["jump", "移動"],
      ["start", "現在を開始"],
      ["end", "現在を終了"],
      ["loop", "ループ"],
      ["loop-off", "解除"],
      ["merge-prev", "前と結合"],
      ["split", "分割"],
      ["delete", "削除"],
    ].forEach(([action, label]) => {
      const button = document.createElement("button");
      button.dataset.action = action;
      button.type = "button";
      button.textContent = label;
      actions.appendChild(button);
    });

    item.appendChild(meta);
    item.appendChild(speakerInfo);
    item.appendChild(timeInfo);
    item.appendChild(textarea);
    item.appendChild(actions);

    item.addEventListener("input", (event) => {
      const target = event.target;
      const field = target.dataset.field;
      if (!field) return;
      if (field === "enabled") sub.enabled = target.checked;
      else if (field === "text") sub.text = target.value;
      else if (field === "speaker_label") sub.speaker_label = target.value;
      else if (field === "scene_id") sub.scene_id = target.value;
      else sub[field] = parseTime(target.value);
      updateOverlay();
      drawTimeline();
      saveProjectScenes().catch(() => {});
    });
    item.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      const action = button?.dataset.action;
      if (!action) {
        if (event.target === item) {
          state.selectedSubtitleId = sub.id;
          state.loopSubtitleId = sub.id;
          item.classList.add("selected");
          seekToSubtitle(sub);
        }
        return;
      }
      state.selectedSubtitleId = sub.id;
      if (action === "jump" || action === "loop") seekToSubtitle(sub);
      if (action === "loop-off") {
        state.loopSubtitleId = null;
      }
      if (action === "start") {
        const current = currentSubtitleEditTime();
        sub.output_start_sec = current;
        if ((Number(sub.output_end_sec) || 0) < current) sub.output_end_sec = current;
      }
      if (action === "end") {
        const current = currentSubtitleEditTime();
        sub.output_end_sec = current;
        if ((Number(sub.output_start_sec) || 0) > current) sub.output_start_sec = current;
      }
      if (action === "merge-prev" && index > 0) {
        const prev = subtitles[index - 1];
        prev.text = `${prev.text || ""}${prev.text ? "\n" : ""}${sub.text || ""}`;
        prev.output_end_sec = Math.max(Number(prev.output_end_sec) || 0, Number(sub.output_end_sec) || 0);
        prev.enabled = prev.enabled !== false || sub.enabled !== false;
        subtitles.splice(index, 1);
        state.selectedSubtitleId = prev.id;
        state.loopSubtitleId = prev.id;
        if (state.decorationProject) {
          syncDecorationEventsFromSubtitles({ path: state.decorationProject.source_srt, subtitles: decorationSourceSubtitles() });
        }
      }
      if (action === "split") {
        const midpoint = (sub.output_start_sec + sub.output_end_sec) / 2;
        const half = Math.ceil((sub.text || "").length / 2);
        const next = { ...sub, id: `sub_${Date.now()}`, output_start_sec: midpoint, text: (sub.text || "").slice(half).trim() };
        sub.output_end_sec = midpoint;
        sub.text = (sub.text || "").slice(0, half).trim();
        subtitles.splice(index + 1, 0, next);
      }
      if (action === "delete") {
        subtitles.splice(index, 1);
        if (state.selectedSubtitleId === sub.id) {
          const next = subtitles[index] || subtitles[index - 1] || null;
          state.selectedSubtitleId = next?.id || null;
          state.loopSubtitleId = next?.id || null;
        }
        if (state.decorationProject) {
          syncDecorationEventsFromSubtitles({ path: state.decorationProject.source_srt, subtitles: decorationSourceSubtitles() });
        }
      }
      renderSubtitles();
      updateOverlay();
      saveProjectScenes().catch(() => {});
    });
    list.appendChild(item);
  });
  renderScenes();
  renderDecorationPage();
}

function extendAllSubtitleDisplayTimes(paddingSec = 0.5) {
  const subtitles = subtitleItems();
  if (!subtitles.length) return 0;
  const padding = Math.max(0, Number(paddingSec) || 0);
  const ordered = [...subtitles].sort((a, b) => (Number(a.output_start_sec ?? a.start_sec ?? 0) || 0) - (Number(b.output_start_sec ?? b.start_sec ?? 0) || 0));
  for (const sub of ordered) {
    const start = Number(sub.output_start_sec ?? sub.start_sec ?? 0) || 0;
    const end = Number(sub.output_end_sec ?? sub.end_sec ?? start) || start;
    sub.output_start_sec = roundTime(Math.max(0, start - padding));
    sub.output_end_sec = roundTime(Math.max(sub.output_start_sec + 0.001, end + padding));
  }
  for (let index = 1; index < ordered.length; index += 1) {
    const prev = ordered[index - 1];
    const current = ordered[index];
    const prevEnd = Number(prev.output_end_sec) || 0;
    const currentStart = Number(current.output_start_sec) || 0;
    if (prevEnd <= currentStart) continue;
    const boundary = (prevEnd + currentStart) / 2;
    const prevStart = Number(prev.output_start_sec) || 0;
    const currentEnd = Number(current.output_end_sec) || currentStart;
    prev.output_end_sec = roundTime(Math.max(prevStart + 0.001, boundary - 0.0005));
    current.output_start_sec = roundTime(Math.min(currentEnd - 0.001, boundary + 0.0005));
    if (current.output_start_sec < 0) current.output_start_sec = 0;
    if (current.output_end_sec <= current.output_start_sec) current.output_end_sec = roundTime(current.output_start_sec + 0.001);
  }
  for (const sub of ordered) {
    sub.edited_start_sec = sub.output_start_sec;
    sub.edited_end_sec = sub.output_end_sec;
  }
  if (state.decorationProject) {
    syncDecorationEventsFromSubtitles({ path: state.decorationProject.source_srt, subtitles: decorationSourceSubtitles() });
  }
  renderSubtitles();
  updateOverlay();
  drawTimeline();
  saveProjectScenes().catch(() => {});
  return subtitles.length;
}

function decorationSourceSubtitles() {
  return subtitleItems().map((sub, index) => ({
    id: sub.id,
    subtitle_id: sub.id,
    index: index + 1,
    start_sec: Number(sub.output_start_sec ?? sub.start_sec ?? 0) || 0,
    end_sec: Number(sub.output_end_sec ?? sub.end_sec ?? 0) || 0,
    text: sub.text || "",
    scene_id: sub.scene_id || "",
    speaker_label: sub.speaker_label || sub.speaker_id || "",
    emotion: sub.emotion || "neutral",
    subtitle_style_preset_id: sub.subtitle_style_preset_id || "",
    effect_group_id: sub.effect_group_id || "",
    seed: Number(sub.seed ?? 0) || (index + 1) * 101,
    enabled: sub.enabled !== false,
  }));
}

function selectedDecorationSourceKind() {
  return $("decorationSourceSelect")?.value || "edited";
}

async function fetchDecorationSourceSubtitles() {
  if (!state.projectId) return [];
  const kind = selectedDecorationSourceKind();
  const data = await api(`/api/projects/${state.projectId}/subtitles?kind=${encodeURIComponent(kind)}`, { method: "GET" });
  return {
    kind: data.kind || kind,
    path: data.path || "",
    subtitles: data.subtitles || [],
  };
}

function decorationEffectGroups() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  return (project.effect_groups && project.effect_groups.length ? project.effect_groups : presets.effect_groups || []).map((group) => ({
    id: group.id || `effect_group_${Math.random().toString(16).slice(2, 8)}`,
    name: group.name || group.id || "無題",
    effects: Array.isArray(group.effects) ? [...group.effects] : String(group.effects || "").split(",").map((item) => item.trim()).filter(Boolean),
    description: group.description || "",
  }));
}

function decorationFramePresets() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  const numberOr = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const fallback = [
    { id: "frame_manga_round", name: "漫画吹き出し", effects: ["bubble_round"], border_enabled: true, border_width: 5, border_color: "#111111", bg_color: "#ffffff", bg_opacity: 0.95, shadow_depth: 2, default_layout_id: "layout_bottom_center", clearance_px: 18, clearance_factor: 0.5, wrap_ratio: 0.88, halftone_enabled: false, halftone_scale: 16, halftone_dot_size: 2, halftone_opacity: 0.24, halftone_color: "#ffffff", description: "普通の漫画の吹き出し" },
    { id: "frame_manga_jagged", name: "ギザギザ吹き出し", effects: ["bubble_round", "jagged"], border_enabled: true, border_width: 5, border_color: "#111111", bg_color: "#ffffff", bg_opacity: 0.95, shadow_depth: 2, default_layout_id: "layout_bottom_center", clearance_px: 18, clearance_factor: 0.5, wrap_ratio: 0.88, jagged_outer_px: 14, jagged_inner_px: 5, jagged_spacing_px: 28, jagged_spacing_min_jitter_px: 4, jagged_spacing_max_jitter_px: 6, jagged_pattern: "alternate", halftone_enabled: false, halftone_scale: 16, halftone_dot_size: 2, halftone_opacity: 0.24, halftone_color: "#ffffff", description: "普通の吹き出しの外側をギザギザにした枠" },
    { id: "frame_cloud_soft", name: "ふわふわ吹き出し", effects: ["bubble_soft"], border_enabled: true, border_width: 4, border_color: "#222222", bg_color: "#fffdf7", bg_opacity: 0.9, shadow_depth: 1, default_layout_id: "layout_bottom_center", clearance_px: 22, clearance_factor: 0.5, wrap_ratio: 0.86, halftone_enabled: false, halftone_scale: 16, halftone_dot_size: 2, halftone_opacity: 0.24, halftone_color: "#fffdf7", description: "雲のようなふわふわした吹き出し" },
    { id: "frame_narration_top", name: "ナレーション上", effects: [], border_enabled: false, border_width: 0, border_color: "#000000", bg_color: "#ffffff", bg_opacity: 0, shadow_depth: 0, default_layout_id: "layout_top_center", clearance_px: 10, clearance_factor: 0.5, wrap_ratio: 0.92, halftone_enabled: false, halftone_scale: 16, halftone_dot_size: 2, halftone_opacity: 0.24, halftone_color: "#ffffff", description: "上配置の縁無しナレーション" },
    { id: "frame_narration_bottom", name: "ナレーション下", effects: [], border_enabled: false, border_width: 0, border_color: "#000000", bg_color: "#ffffff", bg_opacity: 0, shadow_depth: 0, default_layout_id: "layout_bottom_center", clearance_px: 10, clearance_factor: 0.5, wrap_ratio: 0.92, halftone_enabled: false, halftone_scale: 16, halftone_dot_size: 2, halftone_opacity: 0.24, halftone_color: "#ffffff", description: "下配置の縁無しナレーション" },
  ];
  const source = presets.frame_presets && presets.frame_presets.length ? presets.frame_presets : fallback;
  const merged = new Map(source.map((preset) => [preset.id, preset]));
  for (const preset of project.frame_presets || []) {
    const id = preset.id || `frame_${Math.random().toString(16).slice(2, 8)}`;
    merged.set(id, { ...(merged.get(id) || {}), ...preset, id });
  }
  return [...merged.values()].map((preset) => ({
    id: preset.id || `frame_${Math.random().toString(16).slice(2, 8)}`,
    name: preset.name || preset.id || "枠",
    effects: Array.isArray(preset.effects) ? [...preset.effects] : [],
    border_enabled: preset.border_enabled ?? true,
    border_width: numberOr(preset.border_width, 4),
    border_color: preset.border_color || "#000000",
    bg_color: preset.bg_color || "#ffffff",
    bg_opacity: numberOr(preset.bg_opacity, 0.9),
    shadow_depth: numberOr(preset.shadow_depth, 2),
    default_layout_id: preset.default_layout_id || "",
    clearance_px: numberOr(preset.clearance_px, 0),
    clearance_factor: Number.isFinite(Number(preset.clearance_factor)) ? Number(preset.clearance_factor) : null,
    wrap_ratio: Math.max(0.4, Math.min(0.98, numberOr(preset.wrap_ratio, 0.88))),
    jagged_outer_px: numberOr(preset.jagged_outer_px, 14),
    jagged_inner_px: numberOr(preset.jagged_inner_px, 5),
    jagged_spacing_px: numberOr(preset.jagged_spacing_px, 28),
    jagged_spacing_min_jitter_px: numberOr(preset.jagged_spacing_min_jitter_px, 4),
    jagged_spacing_max_jitter_px: numberOr(preset.jagged_spacing_max_jitter_px, 6),
    jagged_pattern: preset.jagged_pattern || "alternate",
    halftone_enabled: preset.halftone_enabled === true,
    halftone_scale: numberOr(preset.halftone_scale, 16),
    halftone_dot_size: numberOr(preset.halftone_dot_size, 2),
    halftone_opacity: Math.max(0, Math.min(1, numberOr(preset.halftone_opacity, 0.24))),
    halftone_color: preset.halftone_color || preset.bg_color || "#222222",
    description: preset.description || "",
  }));
}

const DECORATION_GLOBAL_ID = "__global_decoration__";

function defaultGlobalDecorationEvent() {
  const fontPreset = decorationFontPresets()[0] || {};
  const framePreset = decorationFramePresets().find((item) => item.id === "frame_manga_round") || decorationFramePresets()[0] || {};
  const group = decorationEffectGroups()[0] || {};
  const layoutId = framePreset.default_layout_id || "layout_bottom_center";
  const layoutPreset = decorationLayoutPresets().find((preset) => preset.id === layoutId) || {};
  return {
    id: DECORATION_GLOBAL_ID,
    subtitle_id: "",
    enabled: true,
    is_global: true,
    text: "全体シーンへ適用",
    scene_id: "ALL",
    speaker_label: "",
    emotion: "neutral",
    start_sec: 0,
    end_sec: 0,
    font_preset_id: fontPreset.id || "font_standard",
    frame_preset_id: framePreset.id || "frame_manga_round",
    text_effect_group_id: group.id || "",
    effect_group_id: group.id || "",
    layout_preset_id: layoutId,
    layout_offset_x_px: layoutPreset.offset_x_px ?? 0,
    layout_offset_y_px: layoutPreset.offset_y_px ?? 18,
    seed: 0,
  };
}

function globalDecorationEvent() {
  if (!state.decorationProject) return defaultGlobalDecorationEvent();
  if (!state.decorationProject.global_event) {
    state.decorationProject.global_event = defaultGlobalDecorationEvent();
  }
  return state.decorationProject.global_event;
}

function isGlobalDecorationEvent(eventItem) {
  return eventItem?.is_global === true || eventItem?.id === DECORATION_GLOBAL_ID;
}

function markDecorationEventOverride(eventItem) {
  if (!eventItem || isGlobalDecorationEvent(eventItem)) return;
  eventItem.style_override_enabled = true;
}

function decorationStyleFields() {
  return [
    "font_preset_id",
    "font_family",
    "font_size",
    "font_color",
    "font_outline_enabled",
    "font_outline_color",
    "font_outline_width",
    "frame_preset_id",
    "frame_border_enabled",
    "frame_border_width",
    "frame_border_color",
    "frame_bg_color",
    "frame_bg_opacity",
    "frame_shadow_depth",
    "frame_clearance_factor",
    "frame_clearance_px",
    "frame_wrap_ratio",
    "frame_jagged_outer_px",
    "frame_jagged_inner_px",
    "frame_jagged_spacing_px",
    "frame_jagged_spacing_min_jitter_px",
    "frame_jagged_spacing_max_jitter_px",
    "frame_jagged_pattern",
    "frame_halftone_enabled",
    "frame_halftone_scale",
    "frame_halftone_dot_size",
    "frame_halftone_opacity",
    "frame_halftone_color",
    "layout_preset_id",
    "layout_offset_x_px",
    "layout_offset_y_px",
    "text_effect_group_id",
    "effect_group_id",
  ];
}

function effectiveDecorationForEvent(eventItem) {
  if (!eventItem) return globalDecorationEvent();
  if (isGlobalDecorationEvent(eventItem)) return eventItem;
  const global = globalDecorationEvent();
  if (eventItem.style_override_enabled !== true) {
    return { ...eventItem, ...Object.fromEntries(decorationStyleFields().map((key) => [key, global[key]])) };
  }
  return { ...global, ...eventItem };
}

function applyGlobalDecorationToAllEvents() {
  if (!state.decorationProject) return 0;
  const global = globalDecorationEvent();
  let count = 0;
  for (const eventItem of state.decorationProject.events || []) {
    eventItem.style_override_enabled = false;
    for (const key of decorationStyleFields()) {
      delete eventItem[key];
    }
    eventItem.text_effect_group_id = "";
    eventItem.effect_group_id = "";
    count += 1;
  }
  state.decorationProject.global_event = global;
  return count;
}

function effectiveFrameForEvent(eventItem) {
  const effectiveEvent = effectiveDecorationForEvent(eventItem);
  const preset = decorationFramePresets().find((item) => item.id === effectiveEvent?.frame_preset_id) || decorationFramePresets()[0] || {};
  const numberOr = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const bgOpacity = numberOr(effectiveEvent?.frame_bg_opacity, numberOr(preset.bg_opacity, 0.9));
  const clearanceFactor = Number.isFinite(Number(effectiveEvent?.frame_clearance_factor))
    ? Number(effectiveEvent.frame_clearance_factor)
    : Number.isFinite(Number(preset.clearance_factor))
      ? Number(preset.clearance_factor)
      : null;
  const clearancePx = clearanceFactor !== null
    ? Math.max(0, Math.round((Number(effectiveEvent?.font_size) || Number(preset.font_size) || 44) * clearanceFactor))
    : numberOr(effectiveEvent?.frame_clearance_px, numberOr(preset.clearance_px, 0));
  const wrapRatio = Math.max(0.4, Math.min(0.98, numberOr(effectiveEvent?.frame_wrap_ratio, numberOr(preset.wrap_ratio, 0.88))));
  const jaggedOuterPx = Math.max(1, numberOr(effectiveEvent?.frame_jagged_outer_px, numberOr(preset.jagged_outer_px, 14)));
  const jaggedInnerPx = Math.max(0, numberOr(effectiveEvent?.frame_jagged_inner_px, numberOr(preset.jagged_inner_px, 5)));
  const jaggedSpacingPx = Math.max(6, numberOr(effectiveEvent?.frame_jagged_spacing_px, numberOr(preset.jagged_spacing_px, 28)));
  const jaggedSpacingMinJitterPx = Math.max(0, numberOr(effectiveEvent?.frame_jagged_spacing_min_jitter_px, numberOr(preset.jagged_spacing_min_jitter_px, 4)));
  const jaggedSpacingMaxJitterPx = Math.max(0, numberOr(effectiveEvent?.frame_jagged_spacing_max_jitter_px, numberOr(preset.jagged_spacing_max_jitter_px, 6)));
  const jaggedPattern = String(effectiveEvent?.frame_jagged_pattern || preset.jagged_pattern || "alternate").trim() || "alternate";
  const halftoneEnabled = effectiveEvent?.frame_halftone_enabled ?? preset.halftone_enabled ?? false;
  const halftoneScale = numberOr(effectiveEvent?.frame_halftone_scale, numberOr(preset.halftone_scale, 16));
  const halftoneDotSize = numberOr(effectiveEvent?.frame_halftone_dot_size, numberOr(preset.halftone_dot_size, 2));
  const halftoneOpacity = Math.max(0, Math.min(1, numberOr(effectiveEvent?.frame_halftone_opacity, numberOr(preset.halftone_opacity, 0.24))));
  const frameHasFill = bgOpacity > 0 || halftoneEnabled;
  const borderEnabled = frameHasFill ? (effectiveEvent?.frame_border_enabled ?? preset.border_enabled ?? true) : false;
  const borderWidth = frameHasFill ? numberOr(effectiveEvent?.frame_border_width, numberOr(preset.border_width, 4)) : 0;
  const shadowDepth = frameHasFill ? numberOr(effectiveEvent?.frame_shadow_depth, numberOr(preset.shadow_depth, 2)) : 0;
  return {
    id: effectiveEvent?.frame_preset_id || preset.id || "frame_none",
    name: preset.name || preset.id || "枠",
    effects: Array.isArray(preset.effects) ? [...preset.effects] : [],
    border_enabled: borderEnabled,
    border_width: borderWidth,
    border_color: effectiveEvent?.frame_border_color || preset.border_color || "#000000",
    bg_color: effectiveEvent?.frame_bg_color || preset.bg_color || "#ffffff",
    bg_opacity: bgOpacity,
    shadow_depth: shadowDepth,
    default_layout_id: preset.default_layout_id || "",
    clearance_px: clearancePx,
    clearance_factor: clearanceFactor,
    wrap_ratio: wrapRatio,
    jagged_outer_px: jaggedOuterPx,
    jagged_inner_px: jaggedInnerPx,
    jagged_spacing_px: jaggedSpacingPx,
    jagged_spacing_min_jitter_px: jaggedSpacingMinJitterPx,
    jagged_spacing_max_jitter_px: jaggedSpacingMaxJitterPx,
    jagged_pattern: jaggedPattern,
    halftone_enabled: !!halftoneEnabled,
    halftone_scale: halftoneScale,
    halftone_dot_size: halftoneDotSize,
    halftone_opacity: halftoneOpacity,
    halftone_color: effectiveEvent?.frame_halftone_color || preset.halftone_color || effectiveEvent?.frame_bg_color || preset.bg_color || "#222222",
    description: preset.description || "",
  };
}

function applyFramePresetToEvent(eventItem, presetId) {
  const preset = decorationFramePresets().find((item) => item.id === presetId);
  if (!eventItem || !preset) return;
  eventItem.frame_preset_id = preset.id;
  eventItem.frame_border_enabled = preset.border_enabled ?? true;
  eventItem.frame_border_width = Number.isFinite(Number(preset.border_width)) ? Number(preset.border_width) : 4;
  eventItem.frame_border_color = preset.border_color || "#000000";
  eventItem.frame_bg_color = preset.bg_color || "#ffffff";
  eventItem.frame_bg_opacity = Number.isFinite(Number(preset.bg_opacity)) ? Number(preset.bg_opacity) : 0.9;
  eventItem.frame_shadow_depth = Number.isFinite(Number(preset.shadow_depth)) ? Number(preset.shadow_depth) : 2;
  eventItem.frame_clearance_factor = Number.isFinite(Number(preset.clearance_factor)) ? Number(preset.clearance_factor) : null;
  eventItem.frame_clearance_px = Number.isFinite(Number(preset.clearance_px)) ? Number(preset.clearance_px) : 0;
  eventItem.frame_wrap_ratio = Math.max(0.4, Math.min(0.98, Number.isFinite(Number(preset.wrap_ratio)) ? Number(preset.wrap_ratio) : 0.88));
  eventItem.frame_jagged_outer_px = Number.isFinite(Number(preset.jagged_outer_px)) ? Number(preset.jagged_outer_px) : 14;
  eventItem.frame_jagged_inner_px = Number.isFinite(Number(preset.jagged_inner_px)) ? Number(preset.jagged_inner_px) : 5;
  eventItem.frame_jagged_spacing_px = Number.isFinite(Number(preset.jagged_spacing_px)) ? Number(preset.jagged_spacing_px) : 28;
  eventItem.frame_jagged_spacing_min_jitter_px = Number.isFinite(Number(preset.jagged_spacing_min_jitter_px)) ? Number(preset.jagged_spacing_min_jitter_px) : 4;
  eventItem.frame_jagged_spacing_max_jitter_px = Number.isFinite(Number(preset.jagged_spacing_max_jitter_px)) ? Number(preset.jagged_spacing_max_jitter_px) : 6;
  eventItem.frame_jagged_pattern = preset.jagged_pattern || "alternate";
  eventItem.frame_halftone_enabled = preset.halftone_enabled === true;
  eventItem.frame_halftone_scale = Number.isFinite(Number(preset.halftone_scale)) ? Number(preset.halftone_scale) : 16;
  eventItem.frame_halftone_dot_size = Number.isFinite(Number(preset.halftone_dot_size)) ? Number(preset.halftone_dot_size) : 2;
  eventItem.frame_halftone_opacity = Math.max(0, Math.min(1, Number.isFinite(Number(preset.halftone_opacity)) ? Number(preset.halftone_opacity) : 0.24));
  eventItem.frame_halftone_color = preset.halftone_color || preset.bg_color || "#222222";
  if (preset.default_layout_id) {
    eventItem.layout_preset_id = preset.default_layout_id;
    const layoutPreset = decorationLayoutPresets().find((layoutItem) => layoutItem.id === preset.default_layout_id);
    const layoutDefaultOffsetY = String(layoutPreset?.anchor || "").startsWith("bottom_") ? 18 : 0;
    eventItem.layout_offset_x_px = Number.isFinite(Number(preset.default_layout_offset_x_px))
      ? Number(preset.default_layout_offset_x_px)
      : Number.isFinite(Number(layoutPreset?.offset_x_px))
        ? Number(layoutPreset.offset_x_px)
        : 0;
    eventItem.layout_offset_y_px = Number.isFinite(Number(preset.default_layout_offset_y_px))
      ? Number(preset.default_layout_offset_y_px)
      : Number.isFinite(Number(layoutPreset?.offset_y_px))
        ? Number(layoutPreset.offset_y_px)
        : layoutDefaultOffsetY;
  }
}

function syncFramePresetToLinkedEvents(sourceEvent, force = false) {
  if (!force && state.frameSyncMode !== "live") return 0;
  if (isGlobalDecorationEvent(sourceEvent)) return 0;
  if (!state.decorationProject || !sourceEvent?.frame_preset_id) return 0;
  const presetId = String(sourceEvent.frame_preset_id || "").trim();
  if (!presetId) return 0;
  let updatedCount = 0;
  for (const eventItem of state.decorationProject.events || []) {
    if (String(eventItem.frame_preset_id || "").trim() !== presetId) continue;
    eventItem.frame_preset_id = presetId;
    eventItem.frame_border_enabled = sourceEvent.frame_border_enabled;
    eventItem.frame_border_width = Number(sourceEvent.frame_border_width);
    eventItem.frame_border_color = sourceEvent.frame_border_color;
    eventItem.frame_bg_color = sourceEvent.frame_bg_color;
    eventItem.frame_bg_opacity = Number(sourceEvent.frame_bg_opacity);
    eventItem.frame_shadow_depth = Number(sourceEvent.frame_shadow_depth);
    eventItem.frame_clearance_factor = sourceEvent.frame_clearance_factor ?? null;
    eventItem.frame_clearance_px = Number(sourceEvent.frame_clearance_px);
    eventItem.frame_wrap_ratio = Number(sourceEvent.frame_wrap_ratio);
    eventItem.frame_jagged_outer_px = Number(sourceEvent.frame_jagged_outer_px);
    eventItem.frame_jagged_inner_px = Number(sourceEvent.frame_jagged_inner_px);
    eventItem.frame_jagged_spacing_px = Number(sourceEvent.frame_jagged_spacing_px);
    eventItem.frame_jagged_spacing_min_jitter_px = Number(sourceEvent.frame_jagged_spacing_min_jitter_px);
    eventItem.frame_jagged_spacing_max_jitter_px = Number(sourceEvent.frame_jagged_spacing_max_jitter_px);
    eventItem.frame_jagged_pattern = sourceEvent.frame_jagged_pattern || "alternate";
    eventItem.frame_halftone_enabled = sourceEvent.frame_halftone_enabled;
    eventItem.frame_halftone_scale = Number(sourceEvent.frame_halftone_scale);
    eventItem.frame_halftone_dot_size = Number(sourceEvent.frame_halftone_dot_size);
    eventItem.frame_halftone_opacity = Number(sourceEvent.frame_halftone_opacity);
    eventItem.frame_halftone_color = sourceEvent.frame_halftone_color;
    eventItem.layout_preset_id = sourceEvent.layout_preset_id || eventItem.layout_preset_id || "layout_bottom_center";
    eventItem.layout_offset_x_px = Number(sourceEvent.layout_offset_x_px) || 0;
    eventItem.layout_offset_y_px = Number(sourceEvent.layout_offset_y_px) || 0;
    updatedCount += 1;
  }
  return updatedCount;
}

function framePresetFromEvent(eventItem, name, id = null) {
  const currentFrame = effectiveFrameForEvent(eventItem);
  return {
    id: id || `frame_custom_${String(Date.now()).slice(-8)}`,
    name: name || "枠プリセット",
    effects: [...(currentFrame.effects || [])],
    border_enabled: currentFrame.border_enabled !== false,
    border_width: currentFrame.border_width ?? 4,
    border_color: currentFrame.border_color || "#000000",
    bg_color: currentFrame.bg_color || "#ffffff",
    bg_opacity: currentFrame.bg_opacity ?? 0.9,
    shadow_depth: currentFrame.shadow_depth ?? 2,
    default_layout_id: eventItem.layout_preset_id || currentFrame.default_layout_id || "",
    default_layout_offset_x_px: Number(eventItem.layout_offset_x_px) || 0,
    default_layout_offset_y_px: Number(eventItem.layout_offset_y_px) || 0,
    clearance_px: currentFrame.clearance_px ?? 0,
    clearance_factor: currentFrame.clearance_factor ?? null,
    wrap_ratio: currentFrame.wrap_ratio ?? 0.88,
    jagged_outer_px: currentFrame.jagged_outer_px ?? 14,
    jagged_inner_px: currentFrame.jagged_inner_px ?? 5,
    jagged_spacing_px: currentFrame.jagged_spacing_px ?? 28,
    jagged_spacing_min_jitter_px: currentFrame.jagged_spacing_min_jitter_px ?? 4,
    jagged_spacing_max_jitter_px: currentFrame.jagged_spacing_max_jitter_px ?? 6,
    jagged_pattern: currentFrame.jagged_pattern || "alternate",
    halftone_enabled: currentFrame.halftone_enabled === true,
    halftone_scale: currentFrame.halftone_scale ?? 16,
    halftone_dot_size: currentFrame.halftone_dot_size ?? 2,
    halftone_opacity: currentFrame.halftone_opacity ?? 0.24,
    halftone_color: currentFrame.halftone_color || currentFrame.bg_color || "#222222",
    description: currentFrame.description || "",
  };
}

function jaggedFrameClipPath(frame) {
  const spacing = Math.max(4, (Number(frame?.jagged_spacing_px) || 28) * 0.25);
  const outer = Math.max(1, (Number(frame?.jagged_outer_px) || 14) * 0.25);
  const inner = Math.max(0, (Number(frame?.jagged_inner_px) || 5) * 0.25);
  const minJitter = Math.max(0, (Number(frame?.jagged_spacing_min_jitter_px) || 0) * 0.25);
  const maxJitter = Math.max(0, (Number(frame?.jagged_spacing_max_jitter_px) || 0) * 0.25);
  const pattern = String(frame?.jagged_pattern || "alternate").trim().toLowerCase();
  const seed = Number(frame?.seed) || 0;
  const pad = Math.max(outer, inner, 1);
  const left = pad;
  const top = pad;
  const right = 100 - pad;
  const bottom = 100 - pad;
  const edgePositions = (length, edgeIndex) => {
    const positions = [0];
    let current = 0;
    let stepIndex = 0;
    while (current < length) {
      const span = minJitter + maxJitter + 1;
      const jitter = span > 0 ? ((seed + edgeIndex * 97 + stepIndex * 31) % span) - minJitter : 0;
      current += Math.max(4, spacing + jitter);
      if (current < length) positions.push(current);
      stepIndex += 1;
    }
    if (positions[positions.length - 1] !== length) positions.push(length);
    return positions;
  };
  const points = [];
  let pointIndex = 0;
  const push = (x, y) => {
    points.push(`${x.toFixed(2)}% ${y.toFixed(2)}%`);
    pointIndex += 1;
  };
  const isOuter = () => {
    if (pattern === "random" || pattern === "rand" || pattern === "randomized") {
      return ((seed + pointIndex * 53) % 2) === 0;
    }
    if (pattern === "short_long_short" || pattern === "short-long-short" || pattern === "sls") {
      return pointIndex % 3 === 1;
    }
    return pointIndex % 2 === 0;
  };
  const topPositions = edgePositions(right - left, 0).slice(0, -1);
  topPositions.forEach((pos) => push(left + pos, isOuter() ? top - outer : top + inner));
  const rightPositions = edgePositions(bottom - top, 1).slice(0, -1);
  rightPositions.forEach((pos) => push(isOuter() ? right + outer : right - inner, top + pos));
  const bottomPositions = edgePositions(right - left, 2).slice(0, -1);
  bottomPositions.forEach((pos) => push(right - pos, isOuter() ? bottom + outer : bottom - inner));
  const leftPositions = edgePositions(bottom - top, 3).slice(0, -1);
  leftPositions.forEach((pos) => push(isOuter() ? left - outer : left + inner, bottom - pos));
  return `polygon(${points.join(", ")})`;
}

function suggestedWrapRatioForClearance(fontSize, factor) {
  const size = Math.max(8, Number(fontSize) || 44);
  const value = Math.max(0.5, Math.min(2.5, Number(factor) || 0.5));
  const sizePenalty = Math.max(0, Math.min(0.12, (size - 44) / 400));
  return Math.max(0.4, Math.min(0.98, 0.88 - value * 0.05 - sizePenalty));
}

function screenEffectLibrary() {
  const presets = state.presets.decoration_presets || {};
  const library = presets.screen_effect_library || [];
  const fallback = [
    { id: "shutter_24fps", name: "24fpsシャッター" },
    { id: "sepia", name: "セピア" },
    { id: "disco", name: "ディスコ" },
    { id: "vignette", name: "ビネット" },
    { id: "cinema", name: "シネマ" },
    { id: "monochrome", name: "モノクロ" },
    { id: "old_tv", name: "古いテレビ" },
    { id: "vhs", name: "VHS" },
    { id: "crt", name: "CRT" },
    { id: "retro_game", name: "レトロゲーム" },
    { id: "neon", name: "ネオン" },
    { id: "cyberpunk", name: "サイバーパンク" },
    { id: "horror", name: "ホラー" },
    { id: "dream", name: "ドリーム" },
    { id: "rainy", name: "雨の日" },
    { id: "sunset", name: "夕焼け" },
    { id: "docu_low_sat", name: "ドキュメンタリー低彩度" },
    { id: "pop_high_sat", name: "ポップ高彩度" },
    { id: "noise", name: "ノイズ" },
    { id: "film_grain", name: "フィルム粒子" },
    { id: "scanlines", name: "走査線" },
    { id: "chromatic_aberration", name: "色ずれ" },
    { id: "edge_blur", name: "周辺ぼかし" },
    { id: "background_blur", name: "背景ぼかし" },
    { id: "highlight_subject", name: "中央強調" },
    { id: "shadow_boost", name: "暗部持ち上げ" },
    { id: "highlight_suppress", name: "白飛び抑制" },
    { id: "sharpen", name: "シャープ" },
    { id: "cinematic_border", name: "シネマ帯" },
    { id: "glitch", name: "グリッチ" },
    { id: "rgb_shift", name: "RGBシフト" },
    { id: "flash", name: "フラッシュ" },
    { id: "strobe", name: "ストロボ" },
    { id: "fade", name: "フェード" },
    { id: "shake", name: "シェイク" },
    { id: "hand_tremor", name: "手ぶれ" },
    { id: "miniature", name: "ミニチュア" },
    { id: "fisheye", name: "魚眼" },
    { id: "speed_lines", name: "集中線" },
    { id: "speed_lines_sparse", name: "集中線 荒め" },
    { id: "speed_lines_white", name: "集中線 白抜き" },
    { id: "speed_lines_slash", name: "斜めスピード線" },
    { id: "speed_lines_frame", name: "外周集中線" },
    { id: "speed_lines_burst", name: "爆発集中線" },
    { id: "speed_lines_outward", name: "外向き放射線" },
    { id: "anime_edge", name: "アニメ輪郭" },
    { id: "halftone", name: "単色ハーフトーン" },
    { id: "video_zoom", name: "拡大・縮小" },
    { id: "zoom_blur", name: "ズームブラー" },
    { id: "radial_blur", name: "放射ブラー" },
    { id: "impact_flash", name: "衝撃フラッシュ" },
    { id: "action_shake", name: "アクション揺れ" },
    { id: "mirror", name: "ミラー" },
    { id: "split_mirror", name: "分割ミラー" },
    { id: "kaleidoscope", name: "万華鏡" },
    { id: "pixelate", name: "ドット化" },
    { id: "posterize", name: "階調削減" },
    { id: "oil_paint", name: "油絵" },
    { id: "watercolor", name: "水彩" },
    { id: "pencil_sketch", name: "鉛筆スケッチ" },
    { id: "pseudo_hdr", name: "擬似HDR" },
    { id: "skin_tone", name: "肌色補正" },
    { id: "auto_brightness", name: "自動明るさ" },
    { id: "game_sharp", name: "ゲーム鮮明化" },
    { id: "text_readability", name: "文字視認性" },
    { id: "dark_game", name: "暗いゲーム補正" },
    { id: "white_balance", name: "ホワイトバランス" },
    { id: "spotlight", name: "スポットライト" },
    { id: "iris_out", name: "丸絞り暗転" },
    { id: "drifting_stars", name: "流れ星" },
    { id: "drifting_hearts", name: "ハート漂い" },
    { id: "heart_wipe", name: "ハートワイプ" },
    { id: "heart_burst", name: "広がって消えるハート" },
    { id: "heart_rain", name: "ハート雨" },
    { id: "heart_float_up", name: "ハート浮上" },
    { id: "heart_confetti", name: "ハート紙吹雪" },
    { id: "heart_sparkle", name: "ハートきらめき" },
    { id: "heart_tunnel", name: "ハートトンネル" },
    { id: "heart_orbit_burst", name: "回転ハートバースト" },
    { id: "hearts", name: "ハート" },
    { id: "balloons", name: "風船" },
    { id: "stars", name: "流星" },
    { id: "snow", name: "雪" },
  ];
  const byId = new Map();
  [...fallback, ...library].forEach((effect) => {
    if (!effect?.id) return;
    byId.set(effect.id, { ...effect, category: effect.category || screenEffectCategory(effect.id) });
  });
  return Array.from(byId.values());
}

function speedLineEffectIds() {
  return new Set(["speed_lines", "speed_lines_sparse", "speed_lines_white", "speed_lines_slash", "speed_lines_frame", "speed_lines_burst", "speed_lines_outward"]);
}

function screenEffectCategories() {
  return [
    { id: "all", name: "すべて" },
    { id: "zoom", name: "拡大・縮小" },
    { id: "video_shader", name: "動画加工" },
    { id: "overlay", name: "重ねる効果" },
  ];
}

function screenEffectCategory(effectId) {
  if (String(effectId || "").trim() === "video_zoom") return "zoom";
  const overlayIds = new Set([
    "speed_lines",
    "speed_lines_sparse",
    "speed_lines_white",
    "speed_lines_slash",
    "speed_lines_frame",
    "speed_lines_burst",
    "speed_lines_outward",
    "hearts",
    "balloons",
    "stars",
    "snow",
    "cinematic_border",
    "impact_flash",
    "drifting_stars",
    "drifting_hearts",
    "heart_wipe",
    "heart_burst",
    "heart_rain",
    "heart_float_up",
    "heart_confetti",
    "heart_sparkle",
    "heart_tunnel",
    "heart_orbit_burst",
  ]);
  return overlayIds.has(String(effectId || "").trim()) ? "overlay" : "video_shader";
}

function screenEffectCategoryName(categoryId) {
  return screenEffectCategories().find((item) => item.id === categoryId)?.name || categoryId || "";
}

function screenEffectName(effectId) {
  const item = screenEffectLibrary().find((effect) => effect.id === effectId);
  return item?.name || effectId;
}

function screenEffectStackCategory(stack) {
  const categories = new Set((stack?.effects || []).map((effect) => screenEffectCategory(effect.id)));
  if (categories.size === 1) return [...categories][0];
  if (categories.size > 1) return "mixed";
  return "none";
}

function screenEffectStackCategoryName(stack) {
  const category = screenEffectStackCategory(stack);
  if (category === "mixed") return "混在";
  if (category === "none") return "未設定";
  return screenEffectCategoryName(category);
}


function screenEffectTemplates() {
  const presets = state.presets.decoration_presets || {};
  const fallback = [
    {
      id: "screen_stack_manga_impact",
      name: "漫画インパクト",
      description: "集中線と衝撃フラッシュで強調する",
      effects: [
        { id: "speed_lines", intensity: 0.85, speed: 1.0, color: "#000000" },
        { id: "impact_flash", intensity: 0.55, speed: 1.2, color: "#ffffff" },
        { id: "action_shake", intensity: 0.35, speed: 1.4, color: "#ffffff" },
      ],
    },
    {
      id: "screen_stack_anime_line",
      name: "アニメ輪郭",
      description: "輪郭と漫画トーンを重ねる",
      effects: [
        { id: "anime_edge", intensity: 0.65, speed: 1.0, color: "#000000" },
        { id: "halftone", intensity: 0.35, speed: 1.0, color: "#ffffff" },
      ],
    },
    {
      id: "screen_stack_halftone_coarse",
      name: "網点粗め",
      description: "粗い印刷っぽい単色ハーフトーン",
      effects: [
        { id: "halftone", intensity: 0.9, speed: 1.0, color: "#101010", background_color: "#f7f1e3", dot_density: 14, dot_scale: 1.4, contrast: 1.0, rotation: 0.0 },
      ],
    },
    {
      id: "screen_stack_halftone_manga",
      name: "マンガトーン",
      description: "漫画のスクリーントーン風の単色網点",
      effects: [
        { id: "halftone", intensity: 0.95, speed: 1.0, color: "#111111", background_color: "#ffffff", dot_density: 28, dot_scale: 0.95, contrast: 1.18, rotation: 0.785398 },
        { id: "anime_edge", intensity: 0.35, speed: 1.0, color: "#000000" },
      ],
    },
    {
      id: "screen_stack_halftone_cdlabel",
      name: "CDレーベル",
      description: "昔のCD印刷っぽい細かい網点",
      effects: [
        { id: "halftone", intensity: 0.85, speed: 1.0, color: "#202020", background_color: "#fefefe", dot_density: 42, dot_scale: 0.68, contrast: 0.95, rotation: 0.261799 },
        { id: "vignette", intensity: 0.18, speed: 1.0, color: "#000000" },
      ],
    },
    {
      id: "screen_stack_fisheye_motion",
      name: "魚眼モーション",
      description: "魚眼と手ブレで動きを出す",
      effects: [
        { id: "fisheye", intensity: 0.45, speed: 1.0, color: "#ffffff" },
        { id: "hand_tremor", intensity: 0.35, speed: 1.2, color: "#ffffff" },
      ],
    },
    {
      id: "screen_stack_zoom_action",
      name: "ズームアクション",
      description: "ズームブラーと集中線のアクション表現",
      effects: [
        { id: "zoom_blur", intensity: 0.55, speed: 1.0, color: "#ffffff" },
        { id: "speed_lines", intensity: 0.55, speed: 1.0, color: "#000000" },
      ],
    },
    {
      id: "screen_stack_spotlight",
      name: "スポットライト注目",
      description: "指定位置だけ明るく残して周囲を暗くする",
      effects: [
        { id: "spotlight", intensity: 0.72, position_x: 0.5, position_y: 0.45, radius: 0.34, color: "#000000" },
      ],
    },
    {
      id: "screen_stack_iris_out",
      name: "丸絞り暗転",
      description: "アニメの終わりのように丸く絞って暗転する",
      effects: [
        { id: "iris_out", intensity: 1.0, speed: 1.0, position_x: 0.5, position_y: 0.5, radius: 0.65, color: "#000000" },
      ],
    },
    {
      id: "screen_stack_kawaii_float",
      name: "ハートと星の漂い",
      description: "ハートや星が指定方向へ流れる重ね効果",
      effects: [
        { id: "drifting_hearts", intensity: 0.8, speed: 0.75, direction_angle: -80, symbol_count: 8, color: "#ff5ca8" },
        { id: "drifting_stars", intensity: 0.7, speed: 1.0, direction_angle: -25, symbol_count: 8, color: "#fff176" },
      ],
    },
    {
      id: "screen_stack_heart_wipe",
      name: "ハートワイプ",
      description: "中心からハート形に画面を覆う",
      effects: [
        { id: "heart_wipe", intensity: 0.9, position_x: 0.5, position_y: 0.5, expansion_speed: 1.0, color: "#ff5ca8" },
      ],
    },
    {
      id: "screen_stack_heart_burst",
      name: "広がって消えるハート",
      description: "ハートの輪郭が広がりながらフェードアウトする",
      effects: [
        { id: "heart_burst", intensity: 0.9, position_x: 0.5, position_y: 0.5, radius: 0.18, expansion_speed: 1.0, color: "#ff5ca8" },
      ],
    },
    {
      id: "screen_stack_heart_rain",
      name: "ハート雨",
      description: "画面上から小さなハートが降る",
      effects: [
        { id: "heart_rain", intensity: 0.78, speed: 0.85, symbol_count: 28, radius: 0.055, color: "#ff5ca8" },
      ],
    },
    {
      id: "screen_stack_heart_float",
      name: "ハート浮上",
      description: "下からハートがふわっと浮かぶ",
      effects: [
        { id: "heart_float_up", intensity: 0.72, speed: 0.7, symbol_count: 22, radius: 0.06, color: "#ff83bd" },
      ],
    },
    {
      id: "screen_stack_heart_confetti",
      name: "ハート紙吹雪",
      description: "中心からハートが弾ける",
      effects: [
        { id: "heart_confetti", intensity: 0.85, speed: 1.25, symbol_count: 34, radius: 0.045, position_x: 0.5, position_y: 0.5, color: "#ff5ca8" },
      ],
    },
    {
      id: "screen_stack_heart_sparkle",
      name: "ハートきらめき",
      description: "画面内で小さなハートが点滅する",
      effects: [
        { id: "heart_sparkle", intensity: 0.72, speed: 1.0, symbol_count: 26, radius: 0.04, color: "#ff7ec8" },
      ],
    },
    {
      id: "screen_stack_heart_tunnel",
      name: "ハートトンネル",
      description: "ハートの輪郭が奥から迫るように広がる",
      effects: [
        { id: "heart_tunnel", intensity: 0.8, speed: 1.0, position_x: 0.5, position_y: 0.5, color: "#ff5ca8" },
      ],
    },
  ];
  const merged = new Map();
  [...fallback, ...(presets.screen_effect_stacks || [])].forEach((stack) => {
    if (!stack?.id) return;
    merged.set(stack.id, {
      id: stack.id,
      name: stack.name || stack.id || "無題",
      effects: Array.isArray(stack.effects) ? stack.effects.map(normalizeScreenEffectItem) : [],
      description: stack.description || "",
    });
  });
  return Array.from(merged.values()).map((stack) => ({
    id: stack.id || `screen_stack_${Math.random().toString(16).slice(2, 8)}`,
    name: stack.name || stack.id || "無題",
    effects: Array.isArray(stack.effects) ? stack.effects.map(normalizeScreenEffectItem) : [],
    description: stack.description || "",
  }));
}

function normalizeScreenEffectItem(effect) {
  if (typeof effect === "string") {
    const defaults = screenEffectItemDefaults(effect);
    return { id: effect, ...defaults };
  }
  const id = String(effect?.id || "").trim();
  const defaults = screenEffectItemDefaults(id);
  const numberOrDefault = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : Number(fallback || 0);
  };
  return {
    id,
    intensity: numberOrDefault(effect?.intensity, defaults.intensity),
    speed: numberOrDefault(effect?.speed, defaults.speed),
    color: String(effect?.color || "#ffffff"),
    spokes: numberOrDefault(effect?.spokes, defaults.spokes),
    line_width: numberOrDefault(effect?.line_width, defaults.line_width),
    edge_bias: numberOrDefault(effect?.edge_bias, defaults.edge_bias),
    center_gap: numberOrDefault(effect?.center_gap, defaults.center_gap),
    fisheye_strength: numberOrDefault(effect?.fisheye_strength, defaults.fisheye_strength),
    shake_strength: numberOrDefault(effect?.shake_strength, defaults.shake_strength),
    shake_speed: numberOrDefault(effect?.shake_speed, defaults.shake_speed),
    glitch_band_count: numberOrDefault(effect?.glitch_band_count, defaults.glitch_band_count),
    glitch_shift: numberOrDefault(effect?.glitch_shift, defaults.glitch_shift),
    blur_samples: numberOrDefault(effect?.blur_samples, defaults.blur_samples),
    blur_amount: numberOrDefault(effect?.blur_amount, defaults.blur_amount),
    flash_frequency: numberOrDefault(effect?.flash_frequency, defaults.flash_frequency),
    flash_power: numberOrDefault(effect?.flash_power, defaults.flash_power),
    grain_strength: numberOrDefault(effect?.grain_strength, defaults.grain_strength),
    line_density: numberOrDefault(effect?.line_density, defaults.line_density),
    line_opacity: numberOrDefault(effect?.line_opacity, defaults.line_opacity),
    color_shift: numberOrDefault(effect?.color_shift, defaults.color_shift),
    pixel_size: numberOrDefault(effect?.pixel_size, defaults.pixel_size),
    posterize_levels: numberOrDefault(effect?.posterize_levels, defaults.posterize_levels),
    edge_threshold: numberOrDefault(effect?.edge_threshold, defaults.edge_threshold),
    tone_size: numberOrDefault(effect?.tone_size, defaults.tone_size),
    dot_density: numberOrDefault(effect?.dot_density, defaults.dot_density),
    dot_scale: numberOrDefault(effect?.dot_scale, defaults.dot_scale),
    contrast: numberOrDefault(effect?.contrast, defaults.contrast),
    rotation: numberOrDefault(effect?.rotation, defaults.rotation),
    mirror_split: numberOrDefault(effect?.mirror_split, defaults.mirror_split),
    mirror_offset: numberOrDefault(effect?.mirror_offset, defaults.mirror_offset),
    blur_amount: numberOrDefault(effect?.blur_amount, defaults.blur_amount),
    blur_samples: numberOrDefault(effect?.blur_samples, defaults.blur_samples),
    border_thickness: numberOrDefault(effect?.border_thickness, defaults.border_thickness),
    border_color: String(effect?.border_color || defaults.border_color || "#000000"),
    border_opacity: numberOrDefault(effect?.border_opacity, defaults.border_opacity),
    color_temperature: numberOrDefault(effect?.color_temperature, defaults.color_temperature),
    brightness_shift: numberOrDefault(effect?.brightness_shift, defaults.brightness_shift),
    saturation_shift: numberOrDefault(effect?.saturation_shift, defaults.saturation_shift),
    shadow_strength: numberOrDefault(effect?.shadow_strength, defaults.shadow_strength),
    position_x: numberOrDefault(effect?.position_x, defaults.position_x),
    position_y: numberOrDefault(effect?.position_y, defaults.position_y),
    radius: numberOrDefault(effect?.radius, defaults.radius),
    zoom_scale: numberOrDefault(effect?.zoom_scale, defaults.zoom_scale),
    direction_angle: numberOrDefault(effect?.direction_angle, defaults.direction_angle),
    symbol_count: numberOrDefault(effect?.symbol_count, defaults.symbol_count),
    expansion_speed: numberOrDefault(effect?.expansion_speed, defaults.expansion_speed),
    background_color: String(effect?.background_color || defaults.background_color || effect?.bg_color || "#ffffff"),
  };
}

function screenEffectItemDefaults(effectId) {
  const base = {
    intensity: 1,
    speed: 1,
    color: "#ffffff",
    spokes: 0,
    line_width: 0,
    edge_bias: 0,
    center_gap: 0,
    fisheye_strength: 0,
    shake_strength: 0,
    shake_speed: 1,
    glitch_band_count: 0,
    glitch_shift: 0,
    blur_samples: 0,
    blur_amount: 0,
    flash_frequency: 0,
    flash_power: 0,
    grain_strength: 0,
    line_density: 0,
    line_opacity: 0,
    color_shift: 0,
    pixel_size: 0,
    posterize_levels: 0,
    edge_threshold: 0,
    tone_size: 0,
    dot_density: 24,
    dot_scale: 1,
    contrast: 1,
    rotation: 0.785398,
    mirror_split: 0.5,
    mirror_offset: 0,
    blur_amount: 0,
    blur_samples: 0,
    border_thickness: 0,
    border_color: "#000000",
    border_opacity: 0.0,
    color_temperature: 0,
    brightness_shift: 0,
    saturation_shift: 0,
    shadow_strength: 0,
    position_x: 0.5,
    position_y: 0.5,
    radius: 0.35,
    zoom_scale: 1.25,
    direction_angle: -35,
    symbol_count: 8,
    expansion_speed: 1,
    contrast: 1,
    background_color: "#ffffff",
  };
  switch (String(effectId || "").trim()) {
    case "video_zoom":
      return { ...base, intensity: 1, speed: 1, zoom_scale: 1.25, position_x: 0.5, position_y: 0.5, color: "#000000" };
    case "speed_lines":
      return { ...base, intensity: 0.85, speed: 1, color: "#000000", spokes: 96, line_width: 0.01, edge_bias: 0.18, center_gap: 0.10, glitch_band_count: 22, glitch_shift: 0.06, blur_samples: 6, blur_amount: 0.18, flash_frequency: 10, flash_power: 5 };
    case "speed_lines_sparse":
      return { ...base, intensity: 0.85, speed: 1, color: "#000000", spokes: 42, line_width: 0.018, edge_bias: 0.10, center_gap: 0.22 };
    case "speed_lines_white":
      return { ...base, intensity: 0.78, speed: 1, color: "#ffffff", spokes: 110, line_width: 0.012, edge_bias: 0.18, center_gap: 0.18 };
    case "speed_lines_slash":
      return { ...base, intensity: 0.82, speed: 1, color: "#000000", spokes: 72, line_width: 0.009, edge_bias: 0.30, center_gap: 0.00 };
    case "speed_lines_frame":
      return { ...base, intensity: 0.9, speed: 1, color: "#000000", spokes: 120, line_width: 0.014, edge_bias: 0.16, center_gap: 0.42 };
    case "speed_lines_burst":
      return { ...base, intensity: 0.9, speed: 1, color: "#000000", spokes: 84, line_width: 0.02, edge_bias: 0.08, center_gap: 0.08 };
    case "speed_lines_outward":
      return { ...base, intensity: 0.9, speed: 1, color: "#000000", spokes: 96, line_width: 0.014, edge_bias: 0.08, center_gap: 0.08 };
    case "fisheye":
      return {
        intensity: 0.55,
        speed: 1,
        color: "#ffffff",
        spokes: 0,
        line_width: 0,
        edge_bias: 0,
        center_gap: 0,
        fisheye_strength: 0.45,
        shake_strength: 0,
        shake_speed: 1,
        glitch_band_count: 22,
        glitch_shift: 0.06,
        blur_samples: 6,
        blur_amount: 0.18,
        flash_frequency: 10,
        flash_power: 5,
      };
    case "shake":
    case "hand_tremor":
    case "action_shake":
      return {
        intensity: 0.6,
        speed: 1.2,
        color: "#ffffff",
        spokes: 0,
        line_width: 0,
        edge_bias: 0,
        center_gap: 0,
        fisheye_strength: 0,
        shake_strength: 1,
        shake_speed: effectId === "hand_tremor" ? 1.6 : 1.0,
        glitch_band_count: 22,
        glitch_shift: 0.06,
        blur_samples: 6,
        blur_amount: 0.18,
        flash_frequency: 10,
        flash_power: 5,
      };
    case "glitch":
      return {
        intensity: 0.35,
        speed: 1.1,
        color: "#ffffff",
        spokes: 0,
        line_width: 0,
        edge_bias: 0,
        center_gap: 0,
        fisheye_strength: 0,
        shake_strength: 0,
        shake_speed: 1,
        glitch_band_count: 22,
        glitch_shift: 0.06,
        blur_samples: 6,
        blur_amount: 0.18,
        flash_frequency: 10,
        flash_power: 5,
      };
    case "zoom_blur":
    case "radial_blur":
      return {
        intensity: 0.55,
        speed: 1,
        color: "#ffffff",
        spokes: 0,
        line_width: 0,
        edge_bias: 0,
        center_gap: 0,
        fisheye_strength: 0,
        shake_strength: 0,
        shake_speed: 1,
        glitch_band_count: 22,
        glitch_shift: 0.06,
        blur_samples: 6,
        blur_amount: 0.18,
        flash_frequency: 10,
        flash_power: 5,
      };
    case "impact_flash":
      return {
        intensity: 0.55,
        speed: 1.2,
        color: "#ffffff",
        spokes: 0,
        line_width: 0,
        edge_bias: 0,
        center_gap: 0,
        fisheye_strength: 0,
        shake_strength: 0,
        shake_speed: 1,
        glitch_band_count: 22,
        glitch_shift: 0.06,
        blur_samples: 6,
        blur_amount: 0.18,
        flash_frequency: 10,
        flash_power: 5,
      };
    case "noise":
      return { ...base, intensity: 0.5, grain_strength: 0.28 };
    case "film_grain":
      return { ...base, intensity: 0.35, grain_strength: 0.18 };
    case "scanlines":
    case "crt":
      return { ...base, intensity: 0.65, line_density: 1, line_opacity: 0.22 };
    case "rgb_shift":
    case "chromatic_aberration":
    case "vhs":
      return { ...base, intensity: 0.5, color_shift: 0.012 };
    case "pixelate":
      return { ...base, intensity: 0.8, pixel_size: 12 };
    case "posterize":
      return { ...base, intensity: 0.8, posterize_levels: 6 };
    case "anime_edge":
      return { ...base, intensity: 0.65, edge_threshold: 0.18 };
    case "halftone":
      return { ...base, intensity: 0.6, dot_density: 24, dot_scale: 0.9, contrast: 1.12, rotation: 0.785398, color: "#101010", background_color: "#ffffff" };
    case "edge_blur":
    case "background_blur":
      return { ...base, intensity: 0.45, blur_amount: 6, blur_samples: 4 };
    case "highlight_subject":
      return { ...base, intensity: 0.6, brightness_shift: 0.08, saturation_shift: 0.12 };
    case "shadow_boost":
      return { ...base, intensity: 0.5, brightness_shift: -0.12, saturation_shift: 0.05 };
    case "highlight_suppress":
      return { ...base, intensity: 0.55, brightness_shift: -0.05, color_temperature: -0.05 };
    case "sharpen":
      return { ...base, intensity: 0.55 };
    case "cinematic_border":
      return { ...base, intensity: 0.6, border_thickness: 8, border_color: "#000000", border_opacity: 1 };
    case "miniature":
      return { ...base, intensity: 0.55, blur_amount: 0.08, saturation_shift: -0.08 };
    case "mirror":
      return { ...base, intensity: 0.5, mirror_split: 0.5, mirror_offset: 0 };
    case "split_mirror":
      return { ...base, intensity: 0.5, mirror_split: 0.35, mirror_offset: 0.08 };
    case "kaleidoscope":
      return { ...base, intensity: 0.55, spokes: 6, mirror_split: 0.5 };
    case "oil_paint":
      return { ...base, intensity: 0.5, blur_amount: 0.12, posterize_levels: 8 };
    case "watercolor":
      return { ...base, intensity: 0.45, blur_amount: 0.1, saturation_shift: -0.1 };
    case "pencil_sketch":
      return { ...base, intensity: 0.6, edge_threshold: 0.16, brightness_shift: 0.04 };
    case "pseudo_hdr":
      return { ...base, intensity: 0.7, brightness_shift: 0.08, saturation_shift: 0.12 };
    case "auto_brightness":
      return { ...base, intensity: 0.45, brightness_shift: 0.08 };
    case "game_sharp":
      return { ...base, intensity: 0.65, edge_threshold: 0.12 };
    case "text_readability":
      return { ...base, intensity: 0.65, contrast: 1.15 };
    case "dark_game":
      return { ...base, intensity: 0.55, brightness_shift: -0.12, saturation_shift: 0.08 };
    case "white_balance":
      return { ...base, intensity: 0.45, color_temperature: 0.06 };
    case "spotlight":
      return { ...base, intensity: 0.72, position_x: 0.5, position_y: 0.45, radius: 0.34, color: "#000000" };
    case "iris_out":
      return { ...base, intensity: 1.0, position_x: 0.5, position_y: 0.5, radius: 0.65, speed: 1, color: "#000000" };
    case "drifting_stars":
      return { ...base, intensity: 0.85, color: "#fff176", direction_angle: -25, speed: 1.0, symbol_count: 10 };
    case "drifting_hearts":
      return { ...base, intensity: 0.85, color: "#ff5ca8", direction_angle: -80, speed: 0.75, symbol_count: 8 };
    case "heart_wipe":
    case "heart_expand":
      return { ...base, intensity: 0.9, color: "#ff5ca8", position_x: 0.5, position_y: 0.5, radius: 0.18, expansion_speed: 1.0, symbol_count: 24 };
    case "heart_burst":
      return { ...base, intensity: 0.9, color: "#ff5ca8", position_x: 0.5, position_y: 0.5, radius: 0.18, expansion_speed: 1.0 };
    case "heart_rain":
      return { ...base, intensity: 0.78, speed: 0.85, color: "#ff5ca8", radius: 0.055, symbol_count: 28 };
    case "heart_float_up":
      return { ...base, intensity: 0.72, speed: 0.7, color: "#ff83bd", radius: 0.06, symbol_count: 22 };
    case "heart_confetti":
      return { ...base, intensity: 0.85, speed: 1.25, color: "#ff5ca8", position_x: 0.5, position_y: 0.5, radius: 0.045, symbol_count: 34 };
    case "heart_sparkle":
      return { ...base, intensity: 0.72, speed: 1.0, color: "#ff7ec8", radius: 0.04, symbol_count: 26 };
    case "heart_tunnel":
      return { ...base, intensity: 0.8, speed: 1.0, color: "#ff5ca8", position_x: 0.5, position_y: 0.5, radius: 0.12, symbol_count: 7 };
    case "heart_orbit_burst":
      return { ...base, intensity: 0.88, speed: 1.0, color: "#ff5ca8", position_x: 0.5, position_y: 0.5, radius: 0.055, symbol_count: 14 };
    default:
      return base;
  }
}

function screenEffectParameterSpecs(effectId) {
  switch (String(effectId || "").trim()) {
    case "video_zoom":
      return [
        { key: "zoom_scale", label: "拡大率", min: 0.25, max: 3.0, step: 0.01, format: (v) => `${Number(v).toFixed(2)}x` },
        { key: "position_x", label: "中心X", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "中心Y", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "speed_lines":
    case "speed_lines_sparse":
    case "speed_lines_white":
    case "speed_lines_slash":
    case "speed_lines_frame":
    case "speed_lines_burst":
    case "speed_lines_outward":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "spokes", label: "本数", min: 16, max: 180, step: 1, format: (v) => `${Math.round(Number(v))} 本`, integer: true },
        { key: "line_width", label: "太さ", min: 0.001, max: 0.03, step: 0.001, format: (v) => Number(v).toFixed(3) },
        { key: "center_gap", label: "中央空き", min: 0, max: 0.6, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "fisheye":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "fisheye_strength", label: "歪み", min: 0, max: 0.8, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "shake":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "shake_strength", label: "揺れ", min: 0, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "hand_tremor":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "shake_strength", label: "揺れ", min: 0, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "shake_speed", label: "速度", min: 0.2, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "action_shake":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "shake_strength", label: "揺れ", min: 0, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "glitch":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "glitch_band_count", label: "帯数", min: 4, max: 60, step: 1, format: (v) => `${Math.round(Number(v))} 本`, integer: true },
        { key: "glitch_shift", label: "横ずれ", min: 0, max: 0.15, step: 0.001, format: (v) => Number(v).toFixed(3) },
      ];
    case "zoom_blur":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "blur_samples", label: "サンプル", min: 2, max: 8, step: 1, format: (v) => `${Math.round(Number(v))} 回`, integer: true },
        { key: "blur_amount", label: "広がり", min: 0, max: 0.4, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "radial_blur":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "blur_samples", label: "サンプル", min: 2, max: 8, step: 1, format: (v) => `${Math.round(Number(v))} 回`, integer: true },
        { key: "blur_amount", label: "回転量", min: 0, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "impact_flash":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "flash_frequency", label: "周波数", min: 1, max: 20, step: 0.1, format: (v) => Number(v).toFixed(1) },
        { key: "flash_power", label: "鋭さ", min: 1, max: 10, step: 0.1, format: (v) => Number(v).toFixed(1) },
      ];
    case "spotlight":
      return [
        { key: "intensity", label: "暗さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_x", label: "X位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "Y位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "radius", label: "半径", min: 0.05, max: 0.9, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "iris_out":
      return [
        { key: "intensity", label: "暗さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_x", label: "X位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "Y位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "radius", label: "初期半径", min: 0.1, max: 1.2, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "speed", label: "速度", min: 0.2, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "drifting_stars":
    case "drifting_hearts":
      return [
        { key: "intensity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "direction_angle", label: "方向", min: -180, max: 180, step: 1, format: (v) => `${Math.round(Number(v))}°`, integer: true },
        { key: "speed", label: "速度", min: 0.1, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "symbol_count", label: "数", min: 1, max: 30, step: 1, format: (v) => `${Math.round(Number(v))} 個`, integer: true },
      ];
    case "heart_wipe":
    case "heart_expand":
    case "heart_burst":
      return [
        { key: "intensity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_x", label: "X位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "Y位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "radius", label: "開始サイズ", min: 0.05, max: 0.6, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "expansion_speed", label: "拡大速度", min: 0.2, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "heart_rain":
    case "heart_float_up":
    case "heart_sparkle":
    case "heart_orbit_burst":
      return [
        { key: "intensity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "speed", label: "速度", min: 0.1, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "symbol_count", label: "数", min: 4, max: 96, step: 1, format: (v) => `${Math.round(Number(v))} 個`, integer: true },
        { key: "radius", label: "サイズ", min: 0.02, max: 0.18, step: 0.005, format: (v) => Number(v).toFixed(3) },
      ];
    case "heart_confetti":
      return [
        { key: "intensity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_x", label: "X位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "Y位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "speed", label: "速度", min: 0.1, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "symbol_count", label: "数", min: 4, max: 96, step: 1, format: (v) => `${Math.round(Number(v))} 個`, integer: true },
        { key: "radius", label: "サイズ", min: 0.02, max: 0.18, step: 0.005, format: (v) => Number(v).toFixed(3) },
      ];
    case "heart_tunnel":
      return [
        { key: "intensity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_x", label: "X位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "position_y", label: "Y位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "speed", label: "速度", min: 0.1, max: 3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "noise":
    case "film_grain":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "grain_strength", label: "粒量", min: 0, max: 0.6, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "scanlines":
    case "crt":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "line_density", label: "密度", min: 0.5, max: 4, step: 0.1, format: (v) => Number(v).toFixed(1) },
        { key: "line_opacity", label: "濃さ", min: 0, max: 0.6, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "rgb_shift":
    case "chromatic_aberration":
    case "vhs":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "color_shift", label: "ずれ", min: 0, max: 0.04, step: 0.001, format: (v) => Number(v).toFixed(3) },
      ];
    case "pixelate":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "pixel_size", label: "粒径", min: 4, max: 40, step: 1, format: (v) => `${Math.round(Number(v))} px`, integer: true },
      ];
    case "posterize":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "posterize_levels", label: "階調", min: 2, max: 24, step: 1, format: (v) => `${Math.round(Number(v))} 段`, integer: true },
      ];
    case "anime_edge":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "edge_threshold", label: "輪郭", min: 0.02, max: 0.5, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "halftone":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "dot_density", label: "密度", min: 8, max: 64, step: 1, format: (v) => `${Math.round(Number(v))} セル`, integer: true },
        { key: "dot_scale", label: "サイズ倍率", min: 0.25, max: 2.0, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "contrast", label: "コントラスト", min: 0.5, max: 2.0, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "rotation", label: "回転", min: -3.14159, max: 3.14159, step: 0.01, format: (v) => `${Number(v).toFixed(2)} rad` },
        { key: "background_color", label: "背景色", kind: "color", default: "#ffffff" },
      ];
    case "edge_blur":
    case "background_blur":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "blur_amount", label: "ぼかし", min: 0, max: 16, step: 0.1, format: (v) => Number(v).toFixed(1) },
        { key: "blur_samples", label: "回数", min: 1, max: 8, step: 1, format: (v) => `${Math.round(Number(v))} 回`, integer: true },
      ];
    case "highlight_subject":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "brightness_shift", label: "明るさ", min: -0.2, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "saturation_shift", label: "彩度", min: -0.2, max: 0.4, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "shadow_boost":
    case "highlight_suppress":
    case "auto_brightness":
    case "dark_game":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "brightness_shift", label: "明るさ", min: -0.3, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "sharpen":
    case "game_sharp":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "edge_threshold", label: "輪郭", min: 0.02, max: 0.4, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "text_readability":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "contrast", label: "コントラスト", min: 0.8, max: 1.6, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "cinematic_border":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "border_thickness", label: "帯幅", min: 0, max: 24, step: 1, format: (v) => `${Math.round(Number(v))} px`, integer: true },
        { key: "border_opacity", label: "濃さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "miniature":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "blur_amount", label: "ぼかし", min: 0, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "saturation_shift", label: "彩度", min: -0.3, max: 0.2, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "mirror":
    case "split_mirror":
    case "kaleidoscope":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "mirror_split", label: "分割位置", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "mirror_offset", label: "ずれ", min: -0.25, max: 0.25, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    case "oil_paint":
    case "watercolor":
    case "pencil_sketch":
    case "pseudo_hdr":
    case "white_balance":
      return [
        { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "blur_amount", label: "ぼかし", min: 0, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
        { key: "saturation_shift", label: "彩度", min: -0.3, max: 0.3, step: 0.01, format: (v) => Number(v).toFixed(2) },
      ];
    default:
      return [];
  }
}

function shaderParamsForScreenEffect(effect) {
  const item = normalizeScreenEffectItem(effect);
  switch (item.id) {
    case "speed_lines":
      return [item.spokes, item.line_width, item.edge_bias, item.center_gap];
    case "fisheye":
      return [item.fisheye_strength, 0, 0, 0];
    case "shake":
    case "action_shake":
      return [item.shake_strength, 0, 0, 0];
    case "hand_tremor":
      return [item.shake_strength, item.shake_speed, 0, 0];
    case "glitch":
      return [item.glitch_band_count, item.glitch_shift, 0.72, 0];
    case "zoom_blur":
      return [item.blur_samples, item.blur_amount, 0, 0];
    case "radial_blur":
      return [item.blur_samples, item.blur_amount, item.blur_amount, 0];
    case "impact_flash":
      return [item.flash_frequency, item.flash_power, 0, 0];
    case "noise":
    case "film_grain":
      return [item.grain_strength, 0, 0, 0];
    case "scanlines":
    case "crt":
      return [item.line_density, item.line_opacity, 0, 0];
    case "rgb_shift":
    case "chromatic_aberration":
    case "vhs":
      return [item.color_shift, 0, 0, 0];
    case "pixelate":
      return [item.pixel_size, 0, 0, 0];
    case "posterize":
      return [item.posterize_levels, 0, 0, 0];
    case "anime_edge":
      return [item.edge_threshold, 0, 0, 0];
    case "halftone":
      return [item.dot_density, item.dot_scale, item.contrast, item.rotation];
    default:
      return [0, 0, 0, 0];
  }
}

function screenEffectStacks() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  const stacks = Array.isArray(project.screen_effect_stacks) ? project.screen_effect_stacks : presets.screen_effect_stacks || [];
  return stacks.map((stack) => ({
    id: stack.id || `screen_stack_${Math.random().toString(16).slice(2, 8)}`,
    name: stack.name || stack.id || "無題",
    effects: Array.isArray(stack.effects) ? stack.effects.map(normalizeScreenEffectItem) : [],
    description: stack.description || "",
    timing_mode: stack.timing_mode || "full",
    timing_basis: stack.timing_basis || "relative",
    effect_start_sec: Number(stack.effect_start_sec ?? 0) || 0,
    effect_end_sec: Number(stack.effect_end_sec ?? 0) || 0,
  }));
}

function screenEffectTargets() {
  const project = state.decorationProject || {};
  const targets = project.screen_effect_targets || {};
  return {
    global_stack_ids: [...new Set((targets.global_stack_ids || []).map((item) => String(item || "").trim()).filter(Boolean))],
    scene_stack_ids: Object.fromEntries(
      Object.entries(targets.scene_stack_ids || {}).map(([sceneId, stackIds]) => [
        String(sceneId || "").trim(),
        [...new Set((stackIds || []).map((item) => String(item || "").trim()).filter(Boolean))],
      ]),
    ),
  };
}

function updateScreenEffectTargets(nextTargets) {
  if (!state.decorationProject) return;
  state.decorationProject.screen_effect_targets = {
    global_stack_ids: [...new Set((nextTargets.global_stack_ids || []).filter(Boolean))],
    scene_stack_ids: Object.fromEntries(
      Object.entries(nextTargets.scene_stack_ids || {}).map(([sceneId, stackIds]) => [
        String(sceneId || "").trim(),
        [...new Set((stackIds || []).map((item) => String(item || "").trim()).filter(Boolean))],
      ]),
    ),
  };
}

function addScreenEffectStackToTarget(stackId, targetType, sceneId = "") {
  if (!state.decorationProject) return 0;
  const targets = screenEffectTargets();
  const nextStackId = String(stackId || "").trim();
  if (!nextStackId) return 0;
  if (targetType === "global") {
    targets.global_stack_ids = [...new Set([...targets.global_stack_ids, nextStackId])];
    updateScreenEffectTargets(targets);
    return 1;
  }
  const nextSceneId = String(sceneId || "").trim();
  if (!nextSceneId) return 0;
  const sceneStacks = [...new Set([...(targets.scene_stack_ids[nextSceneId] || []), nextStackId])];
  targets.scene_stack_ids[nextSceneId] = sceneStacks;
  updateScreenEffectTargets(targets);
  return 1;
}

function removeScreenEffectStackFromTarget(stackId, targetType, sceneId = "") {
  if (!state.decorationProject) return 0;
  const targets = screenEffectTargets();
  const nextStackId = String(stackId || "").trim();
  if (!nextStackId) return 0;
  if (targetType === "global") {
    targets.global_stack_ids = targets.global_stack_ids.filter((item) => item !== nextStackId);
    updateScreenEffectTargets(targets);
    return 1;
  }
  const nextSceneId = String(sceneId || "").trim();
  if (!nextSceneId || !targets.scene_stack_ids[nextSceneId]) return 0;
  targets.scene_stack_ids[nextSceneId] = targets.scene_stack_ids[nextSceneId].filter((item) => item !== nextStackId);
  if (!targets.scene_stack_ids[nextSceneId].length) delete targets.scene_stack_ids[nextSceneId];
  updateScreenEffectTargets(targets);
  return 1;
}

function removeScreenEffectStackEverywhere(stackId) {
  if (!state.decorationProject) return 0;
  const targets = screenEffectTargets();
  const nextStackId = String(stackId || "").trim();
  if (!nextStackId) return 0;
  targets.global_stack_ids = targets.global_stack_ids.filter((item) => item !== nextStackId);
  for (const [sceneId, stackIds] of Object.entries(targets.scene_stack_ids || {})) {
    targets.scene_stack_ids[sceneId] = (stackIds || []).filter((item) => item !== nextStackId);
    if (!targets.scene_stack_ids[sceneId].length) delete targets.scene_stack_ids[sceneId];
  }
  updateScreenEffectTargets(targets);
  return 1;
}

function screenEffectStackById(stackId) {
  return screenEffectStacks().find((stack) => stack.id === stackId) || null;
}

function screenEffectStackTemplateFromStack(stack, name = null, id = null) {
  const source = stack || {};
  return {
    id: id || source.id || `screen_stack_${String(Date.now()).slice(-8)}`,
    name: name || source.name || source.id || "無題",
    description: source.description || "",
    effects: Array.isArray(source.effects) ? source.effects.map((effect) => normalizeScreenEffectItem(effect)) : [],
    timing_mode: source.timing_mode || "full",
    timing_basis: source.timing_basis || "relative",
    effect_start_sec: Number(source.effect_start_sec ?? 0) || 0,
    effect_end_sec: Number(source.effect_end_sec ?? 0) || 0,
  };
}

function updateScreenEffectStack(stackId, updater) {
  if (!state.decorationProject) return null;
  const current = state.decorationProject.screen_effect_stacks || [];
  let updated = null;
  state.decorationProject.screen_effect_stacks = current.map((stack) => {
    if (stack.id !== stackId) return stack;
    updated = updater({ ...stack, effects: [...(stack.effects || [])].map(normalizeScreenEffectItem) });
    return updated;
  });
  return updated;
}

function updateScreenEffectStackEffectAt(stackId, effectIndex, updater) {
  return updateScreenEffectStack(stackId, (stack) => {
    const effects = [...(stack.effects || [])];
    const index = Number(effectIndex);
    if (!Number.isInteger(index) || index < 0 || index >= effects.length) return stack;
    const current = normalizeScreenEffectItem(effects[index]);
    effects[index] = normalizeScreenEffectItem(updater(current, index) || current);
    return { ...stack, effects };
  });
}

function resetScreenEffectStackToDefaults(stackId) {
  return updateScreenEffectStack(stackId, (stack) => ({
    ...stack,
    effects: (stack.effects || []).map((effect) => normalizeScreenEffectItem({ id: effect.id, ...screenEffectItemDefaults(effect.id) })),
  }));
}

function resetScreenEffectStackEffectToDefaults(stackId, effectIndex) {
  return updateScreenEffectStackEffectAt(stackId, effectIndex, (currentEffect) => normalizeScreenEffectItem({ id: currentEffect.id, ...screenEffectItemDefaults(currentEffect.id) }));
}

function screenEffectSceneIdForCurrentSelection() {
  const current = currentDecorationEvent();
  const directSceneId = String(current?.scene_id || "").trim();
  if (directSceneId) return directSceneId;
  const scenes = sceneCatalog() || [];
  const sceneAtTime = (timeSec) => scenes.find((item) => {
    const start = Number(item.start_sec) || 0;
    const end = Number(item.end_sec) || start;
    return Number(timeSec) >= start && Number(timeSec) < end;
  });
  if (current && !isGlobalDecorationEvent(current)) {
    const start = Number(current.start_sec ?? current.output_start_sec ?? 0) || 0;
    const end = Number(current.end_sec ?? current.output_end_sec ?? start) || start;
    const found = sceneAtTime((start + end) / 2);
    if (found?.id) return String(found.id);
  }
  const previewVideo = $("decorationPreviewVideo");
  if (previewVideo && Number.isFinite(Number(previewVideo.currentTime))) {
    const found = sceneAtTime(Number(previewVideo.currentTime) || 0);
    if (found?.id) return String(found.id);
  }
  const selected = selectedSubtitle();
  if (selected?.scene_id) return String(selected.scene_id);
  const firstEventSceneId = String((state.decorationProject?.events || []).find((item) => item.scene_id)?.scene_id || "").trim();
  return firstEventSceneId;
}

function ensureScreenEffectSceneIdForCurrentSelection() {
  const existing = screenEffectSceneIdForCurrentSelection();
  if (existing) return existing;
  const current = currentDecorationEvent();
  if (!current || isGlobalDecorationEvent(current)) return "";
  const eventIndex = Math.max(0, (state.decorationProject?.events || []).findIndex((item) => item.id === current.id));
  const sceneId = subtitleSceneId(eventIndex);
  const start = Number(current.start_sec ?? current.output_start_sec ?? 0) || 0;
  const end = Number(current.end_sec ?? current.output_end_sec ?? start + 1) || (start + 1);
  current.scene_id = sceneId;
  const scene = {
    id: sceneId,
    label: subtitleSceneLabel(eventIndex),
    start_sec: start,
    end_sec: end,
    emotion: current.emotion || "neutral",
    effect_group_id: current.effect_group_id || "",
    subtitle_style_preset_id: current.subtitle_style_preset_id || "",
    comment_ids: [current.id].filter(Boolean),
  };
  if (state.decorationProject) {
    const scenes = state.decorationProject.scenes || [];
    state.decorationProject.scenes = scenes.some((item) => item.id === sceneId) ? scenes : [...scenes, scene];
  }
  state.projectScenes = (state.projectScenes || []).some((item) => item.id === sceneId) ? state.projectScenes : [...(state.projectScenes || []), scene];
  return sceneId;
}

function screenEffectStackIdsForScene(sceneId) {
  const targets = screenEffectTargets();
  return [...(targets.scene_stack_ids[String(sceneId || "").trim()] || [])];
}

function activeScreenEffectStackIdsAtTime(timeSec) {
  const targets = screenEffectTargets();
  const active = new Set(targets.global_stack_ids || []);
  const currentTime = Number(timeSec) || 0;
  const scene = (sceneCatalog() || []).find((item) => {
    const start = Number(item.start_sec) || 0;
    const end = Number(item.end_sec) || start;
    return currentTime >= start && currentTime < end;
  });
  if (scene?.id) {
    for (const stackId of targets.scene_stack_ids?.[scene.id] || []) {
      active.add(stackId);
    }
  }
  return [...active];
}

function screenEffectCssForEffect(effect) {
  const item = normalizeScreenEffectItem(effect);
  const intensity = Math.max(0, Number(item.intensity) || 0);
  switch (item.id) {
    case "sepia":
      return `sepia(${Math.min(1, intensity)})`;
    case "disco":
      return `hue-rotate(${Math.round(160 * intensity)}deg) saturate(${(1 + intensity * 0.7).toFixed(2)})`;
    case "vignette":
      return `brightness(${(1 - intensity * 0.08).toFixed(2)}) contrast(${(1 + intensity * 0.08).toFixed(2)})`;
    case "cinema":
      return `contrast(${(1 + intensity * 0.18).toFixed(2)}) saturate(${(1 + intensity * 0.12).toFixed(2)})`;
    case "monochrome":
      return `grayscale(${Math.min(1, intensity)})`;
    case "old_tv":
      return `contrast(${(1 + intensity * 0.1).toFixed(2)}) saturate(${(1 - intensity * 0.2).toFixed(2)})`;
    case "vhs":
      return `saturate(${(1 + intensity * 0.35).toFixed(2)}) hue-rotate(${Math.round(3 * intensity)}deg) contrast(${(1 + intensity * 0.25).toFixed(2)})`;
    case "crt":
      return `contrast(${(1 + intensity * 0.12).toFixed(2)}) brightness(${(1 - intensity * 0.04).toFixed(2)})`;
    case "neon":
      return `saturate(${(1 + intensity * 0.8).toFixed(2)}) brightness(${(1 + intensity * 0.08).toFixed(2)})`;
    case "cyberpunk":
      return `saturate(${(1 + intensity * 0.95).toFixed(2)}) contrast(${(1 + intensity * 0.2).toFixed(2)}) hue-rotate(${Math.round(25 * intensity)}deg)`;
    case "horror":
      return `sepia(${(0.45 * intensity).toFixed(2)}) saturate(${(1 + intensity * 0.45).toFixed(2)}) contrast(${(1 + intensity * 0.2).toFixed(2)}) brightness(${(1 - intensity * 0.12).toFixed(2)})`;
    case "dream":
      return `blur(${(1.8 * intensity).toFixed(2)}px) opacity(${(1 - intensity * 0.06).toFixed(2)})`;
    case "noise":
      return `contrast(${(1 + intensity * 0.06).toFixed(2)})`;
    case "film_grain":
      return `contrast(${(1 + intensity * 0.05).toFixed(2)})`;
    case "scanlines":
      return `contrast(${(1 + intensity * 0.04).toFixed(2)})`;
    case "chromatic_aberration":
      return `saturate(${(1 + intensity * 0.15).toFixed(2)})`;
    case "glitch":
      return `contrast(${(1 + intensity * 0.1).toFixed(2)}) hue-rotate(${Math.round(5 * intensity)}deg)`;
    case "rgb_shift":
      return `saturate(${(1 + intensity * 0.12).toFixed(2)})`;
    case "flash":
      return `brightness(${(1 + intensity * 0.25).toFixed(2)})`;
    case "strobe":
      return `brightness(${(1 + intensity * 0.18).toFixed(2)})`;
    case "fade":
      return `opacity(${(1 - intensity * 0.04).toFixed(2)})`;
    case "shake":
    case "hand_tremor":
      return `contrast(${(1 + intensity * 0.02).toFixed(2)})`;
    case "miniature":
      return `saturate(${(1 - intensity * 0.14).toFixed(2)}) blur(${(Number(item.blur_amount || 0) * intensity).toFixed(2)}px)`;
    case "fisheye":
      return `contrast(${(1 + intensity * 0.04).toFixed(2)})`;
    case "pixelate":
      return `contrast(${(1 + intensity * 0.04).toFixed(2)})`;
    case "posterize":
      return `contrast(${(1 + intensity * 0.08).toFixed(2)})`;
    case "pseudo_hdr":
      return `contrast(${(1 + intensity * 0.18).toFixed(2)}) saturate(${(1 + intensity * 0.12).toFixed(2)}) brightness(${(1 + intensity * 0.06).toFixed(2)})`;
    case "white_balance":
      return `saturate(${(1 + intensity * 0.1).toFixed(2)}) hue-rotate(${Math.round(item.color_temperature * 45)}deg)`;
    case "edge_blur":
    case "background_blur":
      return `blur(${(Number(item.blur_amount || 0) * intensity).toFixed(2)}px)`;
    case "highlight_subject":
      return `brightness(${(1 + Number(item.brightness_shift || 0)).toFixed(2)}) saturate(${(1 + Number(item.saturation_shift || 0)).toFixed(2)})`;
    case "shadow_boost":
      return `brightness(${(1 + Number(item.brightness_shift || 0)).toFixed(2)}) saturate(${(1 + Number(item.saturation_shift || 0)).toFixed(2)})`;
    case "highlight_suppress":
      return `brightness(${(1 + Number(item.brightness_shift || 0)).toFixed(2)}) sepia(${Math.max(0, -Number(item.color_temperature || 0)).toFixed(2)})`;
    case "sharpen":
    case "game_sharp":
      return `contrast(${(1 + intensity * 0.14).toFixed(2)})`;
    case "cinematic_border":
      return `brightness(${(1 - intensity * 0.04).toFixed(2)})`;
    case "mirror":
    case "split_mirror":
    case "kaleidoscope":
      return `contrast(${(1 + intensity * 0.02).toFixed(2)})`;
    case "oil_paint":
      return `saturate(${(1 - intensity * 0.05).toFixed(2)}) blur(${(Number(item.blur_amount || 0) * intensity).toFixed(2)}px)`;
    case "watercolor":
      return `saturate(${(1 - intensity * 0.08).toFixed(2)}) blur(${(Number(item.blur_amount || 0) * intensity).toFixed(2)}px)`;
    case "pencil_sketch":
      return `grayscale(${Math.min(1, intensity * 0.8)}) contrast(${(1 + intensity * 0.2).toFixed(2)})`;
    default:
      return "";
  }
}

function screenEffectCssForStack(stack) {
  return (stack?.effects || [])
    .map((effect) => screenEffectCssForEffect(effect))
    .filter(Boolean)
    .join(" ");
}

function updateDecorationPreviewFilters() {
  const previewVideo = $("decorationPreviewVideo");
  if (!previewVideo) return;
  if (state.decorationPreviewUrl) {
    previewVideo.style.filter = "none";
    updateDecorationShaderEffects([]);
    return;
  }
  const activeStackIds = activeScreenEffectStackIdsAtTime(previewVideo.currentTime || 0);
  const stacks = activeStackIds.map((stackId) => screenEffectStackById(stackId)).filter(Boolean);
  const filter = stacks.map((stack) => screenEffectCssForStack(stack)).filter(Boolean).join(" ");
  previewVideo.style.filter = filter || "none";
  updateDecorationShaderEffects(stacks);
}

function screenEffectShaderCode(effectId) {
  const map = {
    sepia: 1,
    disco: 2,
    vignette: 3,
    cinema: 4,
    monochrome: 5,
    horror: 6,
    dream: 7,
    noise: 8,
    film_grain: 9,
    scanlines: 10,
    rgb_shift: 11,
    chromatic_aberration: 11,
    glitch: 12,
    flash: 13,
    strobe: 14,
    fade: 15,
    pixelate: 16,
    posterize: 17,
    pseudo_hdr: 18,
    old_tv: 19,
    vhs: 20,
    crt: 21,
    neon: 22,
    cyberpunk: 23,
    fisheye: 24,
    shake: 25,
    hand_tremor: 26,
    speed_lines: 27,
    anime_edge: 28,
    halftone: 29,
    zoom_blur: 30,
    radial_blur: 31,
    impact_flash: 32,
    action_shake: 33,
    miniature: 34,
  };
  return map[effectId] || 0;
}

function decorationShaderSource() {
  return {
    vertex: `
      attribute vec2 aPosition;
      varying vec2 vUv;
      void main() {
        vUv = (aPosition + 1.0) * 0.5;
        gl_Position = vec4(aPosition, 0.0, 1.0);
      }
    `,
    fragment: `
      precision mediump float;
      uniform sampler2D uImage;
      uniform float uTime;
      uniform vec2 uResolution;
      uniform int uEffectCount;
      uniform int uEffectIds[8];
      uniform float uIntensity[8];
      uniform float uSpeed[8];
      uniform vec4 uParams[8];
      uniform vec3 uColor[8];
      uniform vec3 uBgColor[8];
      varying vec2 vUv;

      float rand(vec2 co) {
        return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
      }

      vec3 hueShift(vec3 color, float angle) {
        float s = sin(angle);
        float c = cos(angle);
        mat3 m = mat3(
          0.299 + 0.701 * c + 0.168 * s, 0.587 - 0.587 * c + 0.330 * s, 0.114 - 0.114 * c - 0.497 * s,
          0.299 - 0.299 * c - 0.328 * s, 0.587 + 0.413 * c + 0.035 * s, 0.114 - 0.114 * c + 0.292 * s,
          0.299 - 0.300 * c + 1.250 * s, 0.587 - 0.588 * c - 1.050 * s, 0.114 + 0.886 * c - 0.203 * s
        );
        return clamp(m * color, 0.0, 1.0);
      }

      vec2 warpUv(vec2 uv, int id, float amount, float speed, vec4 params) {
        float t = uTime * max(speed, 0.0);
        vec2 center = vec2(0.5);
        vec2 p = uv - center;
        if (id == 24) {
          float r2 = dot(p, p);
          float curve = max(0.0, params.x);
          uv = center + p * (1.0 + r2 * amount * (0.8 + curve * 1.8));
        } else if (id == 25 || id == 33) {
          float n = rand(vec2(floor(t * 18.0), floor(t * 7.0)));
          float amp = max(0.0, params.x);
          float shakeScale = id == 33 ? 0.035 : 0.02;
          vec2 shake = vec2(sin(t * 38.0 + n * 6.0), cos(t * 29.0 + n * 4.0)) * amount * shakeScale * amp;
          uv += shake;
        } else if (id == 26) {
          float amp = max(0.0, params.x);
          float speedMul = max(0.2, params.y);
          uv += vec2(sin(t * 7.1 * speedMul), sin(t * 5.3 * speedMul + 1.7)) * amount * 0.012 * amp;
        } else if (id == 34) {
          uv.y = mix(uv.y, 0.5 + (uv.y - 0.5) * 0.92, amount * smoothstep(0.18, 0.48, abs(uv.y - 0.5)));
        }
        return uv;
      }

      vec3 applyEffect(vec2 uv, vec3 color, int id, float amount, float speed, vec3 tint, vec3 bgTint, vec4 params) {
        float t = uTime * max(speed, 0.0);
        float lum = dot(color, vec3(0.299, 0.587, 0.114));
        if (id == 1) {
          vec3 sepia = vec3(
            dot(color, vec3(0.393, 0.769, 0.189)),
            dot(color, vec3(0.349, 0.686, 0.168)),
            dot(color, vec3(0.272, 0.534, 0.131))
          );
          color = mix(color, sepia, amount);
        } else if (id == 2) {
          color = mix(color, hueShift(color, t * 3.14159), amount);
        } else if (id == 3) {
          float d = distance(uv, vec2(0.5));
          color *= 1.0 - smoothstep(0.25, 0.75, d) * amount * 0.75;
        } else if (id == 4) {
          vec3 graded = vec3(color.r * 1.08, color.g * 1.02, color.b * 0.92);
          graded = mix(graded, vec3(0.05, 0.35, 0.45) + graded * vec3(1.18, 0.98, 0.78), 0.22);
          color = mix(color, graded, amount);
        } else if (id == 5) {
          color = mix(color, vec3(lum), amount);
        } else if (id == 6) {
          vec3 horror = vec3(lum * 0.8 + color.r * 0.25, lum * 0.48, lum * 0.42);
          float d = distance(uv, vec2(0.5));
          horror *= 1.0 - smoothstep(0.2, 0.78, d) * 0.55;
          color = mix(color, horror, amount);
        } else if (id == 7) {
          vec2 px = 1.0 / uResolution;
          vec3 blur = (
            texture2D(uImage, uv + vec2(px.x * 2.0, 0.0)).rgb +
            texture2D(uImage, uv - vec2(px.x * 2.0, 0.0)).rgb +
            texture2D(uImage, uv + vec2(0.0, px.y * 2.0)).rgb +
            texture2D(uImage, uv - vec2(0.0, px.y * 2.0)).rgb
          ) * 0.25;
          color = mix(color, blur * 1.08, amount);
        } else if (id == 8 || id == 9) {
          float n = rand(uv * uResolution + vec2(t * 37.0));
          color += (n - 0.5) * amount * max(0.0, params.x);
        } else if (id == 10 || id == 21) {
          float density = max(0.1, params.x);
          float opacity = max(0.0, params.y);
          float line = sin(uv.y * uResolution.y * 3.14159 * density);
          color *= 1.0 - (0.5 + 0.5 * line) * amount * opacity;
        } else if (id == 11 || id == 20) {
          float off = amount * max(0.0, params.x);
          color.r = texture2D(uImage, uv + vec2(off, 0.0)).r;
          color.b = texture2D(uImage, uv - vec2(off, 0.0)).b;
        } else if (id == 12) {
          float bandCount = max(4.0, params.x);
          float band = floor(uv.y * bandCount);
          float shiftScale = max(0.0, params.y);
          float chance = clamp(params.z, 0.05, 1.0);
          float enable = step(chance, rand(vec2(band, floor(t * 18.0))));
          float shift = (rand(vec2(band, floor(t * 18.0) + 2.0)) - 0.5) * amount * shiftScale;
          color = mix(color, texture2D(uImage, uv + vec2(shift, 0.0)).rgb, enable);
        } else if (id == 13) {
          float pulse = pow(max(0.0, sin(t * 8.0)), 6.0);
          color = mix(color, vec3(1.0), pulse * amount);
        } else if (id == 14) {
          float onoff = step(0.5, fract(t * 8.0));
          color *= mix(1.0, 0.3 + onoff * 1.4, amount);
        } else if (id == 15) {
          color *= 1.0 - amount * 0.18 * (0.5 + 0.5 * sin(t * 2.0));
        } else if (id == 16) {
          float pixelSize = max(2.0, params.x);
          vec2 cells = max(vec2(1.0), uResolution / pixelSize);
          vec2 puv = floor(uv * cells) / cells;
          color = mix(color, texture2D(uImage, puv).rgb, amount);
        } else if (id == 17) {
          float levels = max(2.0, params.x);
          vec3 poster = floor(color * levels) / levels;
          color = mix(color, poster, amount);
        } else if (id == 18) {
          vec3 hdr = pow(color, vec3(0.78));
          hdr = (hdr - 0.5) * 1.18 + 0.5;
          color = mix(color, hdr, amount);
        } else if (id == 19) {
          float d = distance(uv, vec2(0.5));
          color *= 1.0 - smoothstep(0.2, 0.78, d) * amount * 0.5;
          color += (rand(uv * uResolution + vec2(t * 15.0)) - 0.5) * amount * 0.16;
        } else if (id == 22 || id == 23) {
          color = mix(color, hueShift(color * (1.0 + amount * 0.45), amount * 2.2), amount);
          color += tint * amount * 0.08;
        } else if (id == 27) {
          vec2 p = uv - vec2(0.5);
          float radius = length(p);
          float angle = atan(p.y, p.x);
          float twoPi = 6.2831853;
          float spokes = max(12.0, params.x);
          float sector = floor((angle + 3.14159265) / twoPi * spokes);
          float enable = step(0.34, rand(vec2(sector, floor(t * 1.4))));
          float centerAngle = (sector + 0.5) / spokes * twoPi - 3.14159265;
          float angleDelta = abs(angle - centerAngle);
          angleDelta = min(angleDelta, twoPi - angleDelta);
          float lineWidth = clamp(params.y, 0.0015, 0.06);
          float spoke = 1.0 - smoothstep(lineWidth, lineWidth * 2.6, angleDelta);
          float edgeBias = clamp(params.z, 0.02, 0.98);
          float outerMask = smoothstep(1.02, edgeBias, radius);
          float centerGap = clamp(params.w, 0.0, 0.9);
          float innerMask = smoothstep(centerGap, centerGap + 0.10, radius);
          float grain = 0.78 + 0.22 * rand(vec2(floor(p.x * 180.0), floor(p.y * 180.0 + t * 18.0)));
          float line = spoke * outerMask * innerMask * enable * grain;
          color = mix(color, vec3(0.0), line * amount * 0.98);
        } else if (id == 28) {
          vec2 px = 1.0 / uResolution;
          vec3 c1 = texture2D(uImage, uv + vec2(px.x, 0.0)).rgb;
          vec3 c2 = texture2D(uImage, uv - vec2(px.x, 0.0)).rgb;
          vec3 c3 = texture2D(uImage, uv + vec2(0.0, px.y)).rgb;
          vec3 c4 = texture2D(uImage, uv - vec2(0.0, px.y)).rgb;
          float edge = length((c1 - c2) + (c3 - c4));
          float threshold = clamp(params.x, 0.01, 0.9);
          color = mix(color, mix(color, tint, smoothstep(threshold, threshold + 0.24, edge)), amount);
        } else if (id == 29) {
          // 単色ハーフトーン
          // セル中心を基準にサンプリングし、時間で揺れない網点を作る
          float density = max(2.0, params.x);
          float scale = max(0.05, params.y);
          float contrast = max(0.1, params.z);
          float rotation = params.w;
          mat2 rm = mat2(cos(rotation), -sin(rotation), sin(rotation), cos(rotation));
          mat2 irm = mat2(cos(rotation), sin(rotation), -sin(rotation), cos(rotation));
          vec2 p = uv - vec2(0.5);
          float aspect = uResolution.x / max(1.0, uResolution.y);
          p.x *= aspect;
          vec2 rp = rm * p;
          float cellSize = 1.0 / density;
          vec2 cellId = floor(rp / cellSize);
          vec2 cellCenterRot = (cellId + 0.5) * cellSize;
          vec2 samplePos = irm * cellCenterRot;
          samplePos.x /= aspect;
          vec2 sampleUv = samplePos + vec2(0.5);
          vec3 sampleColor = texture2D(uImage, sampleUv).rgb;
          float sampleLum = dot(sampleColor, vec3(0.299, 0.587, 0.114));
          sampleLum = clamp((sampleLum - 0.5) * contrast + 0.5, 0.0, 1.0);
          float radius = (cellSize * 0.5) * scale * (1.0 - sampleLum);
          float dist = length(rp - cellCenterRot);
          float aa = max(cellSize * 0.085, 0.0015);
          float dotMask = 1.0 - smoothstep(radius - aa, radius + aa, dist);
          vec3 mono = mix(bgTint, tint, dotMask);
          color = mix(color, mono, amount);
        } else if (id == 30 || id == 31) {
          vec2 center = vec2(0.5);
          vec3 blur = vec3(0.0);
          float sampleCount = max(2.0, params.x);
          float rotationScale = max(0.0, params.z);
          float zoomScale = max(0.0, params.y);
          for (int j = 0; j < 8; j++) {
            if (float(j) >= sampleCount) break;
            float f = float(j) / max(1.0, sampleCount - 1.0);
            vec2 sampleUv = mix(uv, center, f * amount * 0.18);
            if (id == 31) {
              float a = (f - 0.5) * amount * rotationScale;
              vec2 p = uv - center;
              sampleUv = center + vec2(p.x * cos(a) - p.y * sin(a), p.x * sin(a) + p.y * cos(a));
            } else {
              sampleUv = mix(uv, center, f * amount * zoomScale);
            }
            blur += texture2D(uImage, sampleUv).rgb;
          }
          color = mix(color, blur / max(1.0, sampleCount), amount);
        } else if (id == 32) {
          float pulse = pow(max(0.0, sin(t * max(1.0, params.x))), max(1.0, params.y));
          color = mix(color, tint, pulse * amount * 0.75);
        }
        return clamp(color, 0.0, 1.0);
      }

      void main() {
        vec2 uv = vUv;
        for (int i = 0; i < 8; i++) {
          if (i >= uEffectCount) break;
          uv = warpUv(uv, uEffectIds[i], uIntensity[i], uSpeed[i], uParams[i]);
        }
        vec3 color = texture2D(uImage, uv).rgb;
        for (int i = 0; i < 8; i++) {
          if (i >= uEffectCount) break;
          color = applyEffect(uv, color, uEffectIds[i], uIntensity[i], uSpeed[i], uColor[i], uBgColor[i], uParams[i]);
        }
        gl_FragColor = vec4(color, 1.0);
      }
    `,
  };
}

function compileDecorationShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
  }
  return shader;
}

function initDecorationShaderPreview() {
  const canvas = $("decorationShaderCanvas");
  const videoEl = $("decorationPreviewVideo");
  if (!canvas || !videoEl) return null;
  if (state.decorationShaderPreview.gl) return state.decorationShaderPreview;
  const gl = canvas.getContext("webgl", { premultipliedAlpha: false, preserveDrawingBuffer: false });
  if (!gl) return null;
  const source = decorationShaderSource();
  const vertex = compileDecorationShader(gl, gl.VERTEX_SHADER, source.vertex);
  const fragment = compileDecorationShader(gl, gl.FRAGMENT_SHADER, source.fragment);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || "shader link failed");
  }
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  // 動画の初回フレームが来るまでの間、未定義テクスチャ扱いにならないようダミー1x1を入れる
  gl.texImage2D(
    gl.TEXTURE_2D,
    0,
    gl.RGBA,
    1,
    1,
    0,
    gl.RGBA,
    gl.UNSIGNED_BYTE,
    new Uint8Array([0, 0, 0, 255])
  );
  state.decorationShaderPreview = {
    gl,
    program,
    texture,
    buffer,
    raf: null,
    active: false,
    effects: [],
  };
  return state.decorationShaderPreview;
}

function hexToRgb01(value) {
  const raw = String(value || "#ffffff").replace("#", "");
  const hex = /^[0-9a-fA-F]{6}$/.test(raw) ? raw : "ffffff";
  return [
    parseInt(hex.slice(0, 2), 16) / 255,
    parseInt(hex.slice(2, 4), 16) / 255,
    parseInt(hex.slice(4, 6), 16) / 255,
  ];
}

function hexToRgba(value, opacity = 1) {
  const raw = String(value || "#ffffff").replace("#", "");
  const hex = /^[0-9a-fA-F]{6}$/.test(raw) ? raw : "ffffff";
  const alpha = Math.max(0, Math.min(1, Number(opacity) || 0));
  return `rgba(${parseInt(hex.slice(0, 2), 16)}, ${parseInt(hex.slice(2, 4), 16)}, ${parseInt(hex.slice(4, 6), 16)}, ${alpha.toFixed(3)})`;
}

function flattenScreenShaderEffects(stacks) {
  return stacks
    .flatMap((stack) => stack.effects || [])
    .map(normalizeScreenEffectItem)
    .filter((effect) => screenEffectShaderCode(effect.id) > 0)
    .slice(0, 8);
}

function updateDecorationShaderEffects(stacks) {
  const stage = $("decorationPreviewStage");
  let shader = null;
  try {
    shader = initDecorationShaderPreview();
  } catch (err) {
    if (stage) stage.classList.remove("shader-active");
    setStatus(`画面シェーダー初期化に失敗しました: ${err.message || err}`, true);
    return;
  }
  const effects = flattenScreenShaderEffects(stacks || []);
  if (!shader || !stage || !effects.length) {
    if (stage) stage.classList.remove("shader-active");
    if (shader) shader.effects = [];
    stopDecorationShaderLoop();
    return;
  }
  shader.effects = effects;
  stage.classList.add("shader-active");
  renderDecorationShaderFrame();
}

function renderDecorationShaderFrame() {
  const shader = state.decorationShaderPreview;
  const videoEl = $("decorationPreviewVideo");
  const canvas = $("decorationShaderCanvas");
  if (!shader?.gl || !videoEl || !canvas || !shader.effects?.length) return;
  if (videoEl.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !videoEl.videoWidth || !videoEl.videoHeight) return;
  const gl = shader.gl;
  const width = videoEl.videoWidth || 1280;
  const height = videoEl.videoHeight || 720;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(shader.program);
  gl.bindBuffer(gl.ARRAY_BUFFER, shader.buffer);
  const pos = gl.getAttribLocation(shader.program, "aPosition");
  gl.enableVertexAttribArray(pos);
  gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
  gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D, shader.texture);
  try {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, videoEl);
  } catch {
    return;
  } finally {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  }
  const effects = shader.effects.slice(0, 8);
  const ids = new Int32Array(8);
  const intensities = new Float32Array(8);
  const speeds = new Float32Array(8);
  const params = new Float32Array(32);
  const colors = new Float32Array(24);
  const bgColors = new Float32Array(24);
  effects.forEach((effect, index) => {
    ids[index] = screenEffectShaderCode(effect.id);
    intensities[index] = Math.max(0, Math.min(1, Number(effect.intensity ?? 1) || 0));
    speeds[index] = Math.max(0, Number(effect.speed ?? 1) || 0);
    params.set(shaderParamsForScreenEffect(effect), index * 4);
    colors.set(hexToRgb01(effect.color), index * 3);
    bgColors.set(hexToRgb01(effect.background_color || "#ffffff"), index * 3);
  });
  gl.uniform1i(gl.getUniformLocation(shader.program, "uImage"), 0);
  gl.uniform1f(gl.getUniformLocation(shader.program, "uTime"), videoEl.currentTime || 0);
  gl.uniform2f(gl.getUniformLocation(shader.program, "uResolution"), canvas.width, canvas.height);
  gl.uniform1i(gl.getUniformLocation(shader.program, "uEffectCount"), effects.length);
  gl.uniform1iv(gl.getUniformLocation(shader.program, "uEffectIds[0]"), ids);
  gl.uniform1fv(gl.getUniformLocation(shader.program, "uIntensity[0]"), intensities);
  gl.uniform1fv(gl.getUniformLocation(shader.program, "uSpeed[0]"), speeds);
  gl.uniform4fv(gl.getUniformLocation(shader.program, "uParams[0]"), params);
  gl.uniform3fv(gl.getUniformLocation(shader.program, "uColor[0]"), colors);
  gl.uniform3fv(gl.getUniformLocation(shader.program, "uBgColor[0]"), bgColors);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
}

function startDecorationShaderLoop() {
  const shader = initDecorationShaderPreview();
  if (!shader || shader.raf) return;
  const tick = () => {
    renderDecorationShaderFrame();
    shader.raf = requestAnimationFrame(tick);
  };
  shader.raf = requestAnimationFrame(tick);
}

function stopDecorationShaderLoop() {
  const shader = state.decorationShaderPreview;
  if (shader?.raf) {
    cancelAnimationFrame(shader.raf);
    shader.raf = null;
  }
}

function createDecorationEffectGroupFromCurrentEvent() {
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  const current = currentDecorationEvent();
  if (!current) return null;
  const preset = emotionPresetForEmotion(current.emotion);
  const sourceGroupId = current.text_effect_group_id || current.effect_group_id || preset.effect_group_id || state.presets.decoration_presets?.effect_groups?.[0]?.id || "";
  const sourceGroup = decorationEffectGroups().find((group) => group.id === sourceGroupId) || {
    id: sourceGroupId || "effect_group_custom",
    name: preset.name || current.emotion || "演出セット",
    description: `${current.emotion || "neutral"} 用の演出セット`,
    effects: ["bubble_round", "sparkle"],
  };
  const newId = `effect_group_${String(Date.now()).slice(-8)}`;
  const newGroup = {
    id: newId,
    name: `${sourceGroup.name || preset.name || current.emotion || "演出セット"} copy`,
    description: sourceGroup.description || `${current.emotion || "neutral"} 用の演出セット`,
    effects: [...(sourceGroup.effects || [])],
  };
  state.decorationProject.effect_groups = [...(state.decorationProject.effect_groups || []), newGroup];
  current.text_effect_group_id = newId;
  current.effect_group_id = newId;
  current.emotion_preset_id = preset.id;
  return newGroup;
}

function applyDecorationGroupToEvent(eventItem, group) {
  if (!eventItem || !group) return;
  eventItem.text_effect_group_id = group.id;
  eventItem.effect_group_id = group.id;
}

function applyDecorationGroupToSelection(group) {
  const current = currentDecorationEvent();
  if (!current || !group) return 0;
  applyDecorationGroupToEvent(current, group);
  return 1;
}

function applyDecorationGroupToCurrentScene(group) {
  const current = currentDecorationEvent();
  if (!current || !group) return 0;
  const sceneId = String(current.scene_id || "").trim();
  if (!sceneId) return 0;
  let count = 0;
  for (const eventItem of state.decorationProject?.events || []) {
    if (String(eventItem.scene_id || "").trim() === sceneId) {
      applyDecorationGroupToEvent(eventItem, group);
      count += 1;
    }
  }
  return count;
}

function applyDecorationGroupToCurrentSpeaker(group) {
  const current = currentDecorationEvent();
  if (!current || !group) return 0;
  const speakerKey = String(current.speaker_label || current.speaker_id || "").trim();
  if (!speakerKey) return 0;
  let count = 0;
  for (const eventItem of state.decorationProject?.events || []) {
    const targetKey = String(eventItem.speaker_label || eventItem.speaker_id || "").trim();
    if (targetKey === speakerKey) {
      applyDecorationGroupToEvent(eventItem, group);
      count += 1;
    }
  }
  return count;
}

function applyDecorationGroupToCurrentEmotion(group) {
  const current = currentDecorationEvent();
  if (!current || !group) return 0;
  const emotionKey = String(current.emotion || "neutral").trim() || "neutral";
  let count = 0;
  for (const eventItem of state.decorationProject?.events || []) {
    const targetKey = String(eventItem.emotion || "neutral").trim() || "neutral";
    if (targetKey === emotionKey) {
      applyDecorationGroupToEvent(eventItem, group);
      count += 1;
    }
  }
  return count;
}

function applyDecorationGroupToAll(group) {
  if (!group) return 0;
  let count = 0;
  for (const eventItem of state.decorationProject?.events || []) {
    applyDecorationGroupToEvent(eventItem, group);
    count += 1;
  }
  return count;
}

function decorationEffectLibrary() {
  const presets = state.presets.decoration_presets || {};
  const library = presets.effect_library || [];
  return library.length ? library : [
    { id: "sparkle", name: "きらめき" },
    { id: "pop_in", name: "ポップイン" },
    { id: "shake", name: "揺れ" },
    { id: "float_in", name: "浮遊" },
    { id: "heart", name: "ハート" },
    { id: "star_reaction", name: "☆反応" },
    { id: "heart_reaction", name: "♡反応" },
  ];
}

function emotionPresets() {
  return (state.presets.emotion_presets || []).map((item) => ({ ...item }));
}

function emotionPresetForEmotion(emotion) {
  const key = String(emotion || "neutral").trim().toLowerCase();
  return emotionPresets().find((item) => String(item.emotion || item.id || "").trim().toLowerCase() === key) || {
    id: "emotion_neutral",
    name: "通常",
    emotion: "neutral",
    effect_group_id: "",
    subtitle_style_preset_id: "subtitle_standard",
    font_preset_id: "font_standard",
  };
}

function emotionVisualTheme(emotion) {
  const key = String(emotion || "neutral").toLowerCase();
  const themes = {
    joy: { bg: "#fffbe6", border: "#f4d35e", chip: "#e7b600" },
    anger: { bg: "#fff0f0", border: "#ff6b6b", chip: "#b42318" },
    sadness: { bg: "#eef6ff", border: "#7cb5ff", chip: "#3e63dd" },
    surprise: { bg: "#f3edff", border: "#9c7cff", chip: "#6f42c1" },
    teasing: { bg: "#fff0fb", border: "#f472b6", chip: "#be185d" },
    fear: { bg: "#eefcf8", border: "#63c5b5", chip: "#0f766e" },
    embarrassment: { bg: "#fff5ea", border: "#f59e0b", chip: "#b45309" },
  };
  return themes[key] || { bg: "#f7f9fc", border: "#d0d7e2", chip: "#64748b" };
}

function decorationFontPresets() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  return (project.font_presets && project.font_presets.length ? project.font_presets : presets.font_presets || []).map((preset) => ({ ...preset }));
}

function effectiveFontForEvent(eventItem) {
  const effectiveEvent = effectiveDecorationForEvent(eventItem);
  const preset = decorationFontPresets().find((item) => item.id === effectiveEvent?.font_preset_id) || decorationFontPresets()[0] || {};
  const numberOr = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const outlineWidth = numberOr(effectiveEvent?.font_outline_width, numberOr(preset.outline_width, 4));
  return {
    id: effectiveEvent?.font_preset_id || preset.id || "font_standard",
    family: effectiveEvent?.font_family || preset.family || "Yu Gothic",
    size: numberOr(effectiveEvent?.font_size, numberOr(preset.size, 44)),
    color: effectiveEvent?.font_color || preset.color || "#ffffff",
    outline_enabled: effectiveEvent?.font_outline_enabled ?? outlineWidth > 0,
    outline_color: effectiveEvent?.font_outline_color || preset.outline_color || "#000000",
    outline_width: outlineWidth,
  };
}

function isJapaneseFontName(name) {
  const value = String(name || "").trim();
  if (!value) return false;
  const patterns = [
    /^(Yu Gothic|Yu Mincho|Meiryo|MS Gothic|MS PGothic|MS UI Gothic|MS Mincho|MS PMincho|BIZ UDGothic|BIZ UDPGothic|BIZ UDMincho|BIZ UDPMincho|UD Digi Kyokasho|UDDigiKyokasho|HG|HGP|HGS|HGG|DF|DFP|DFG|M+|\bNoto (Sans|Serif) CJK|\bNoto (Sans|Serif) JP|\bSource Han (Sans|Serif)|\bHiragino|\bKozuka|\bTakao|\bIPA|\bIPAPGothic|\bIPAMincho|\bUD )/i,
    /[ぁ-んァ-ヶ一-龠]/,
    /(Japanese|JP|CJK|Kyokasho|Klee|Kaisei|Zen |Kosugi|Sawarabi|Migu|MigMix|Motoya|Yomogi|Mochiy|Kiwi Maru|Reggae|Stick|RocknRoll|Yusei|Dela Gothic|DotGothic|Rampart|Tegomin|Potta|Hachi Maru|Murecho)/i,
  ];
  return patterns.some((pattern) => pattern.test(value));
}

function japaneseFontNames(fonts) {
  return [...new Set((fonts || []).map((item) => String(item || "").trim()).filter(Boolean))].filter(isJapaneseFontName);
}

function fontPresetFromEvent(eventItem, name, id = null) {
  const currentFont = effectiveFontForEvent(eventItem);
  return {
    id: id || `font_custom_${String(Date.now()).slice(-8)}`,
    name: name || "文字プリセット",
    family: currentFont.family,
    size: currentFont.size,
    color: currentFont.color,
    outline_color: currentFont.outline_color,
    outline_width: currentFont.outline_enabled === false ? 0 : currentFont.outline_width,
    shadow_color: "#000000",
    shadow_depth: 4,
  };
}

function applyFontPresetToEvent(eventItem, presetId) {
  const preset = decorationFontPresets().find((item) => item.id === presetId);
  if (!eventItem || !preset) return;
  eventItem.font_preset_id = preset.id;
  eventItem.font_family = preset.family || "Yu Gothic";
  eventItem.font_size = Number(preset.size) || 44;
  eventItem.font_color = preset.color || "#ffffff";
  eventItem.font_outline_enabled = Number(preset.outline_width ?? 0) > 0;
  eventItem.font_outline_color = preset.outline_color || "#000000";
  eventItem.font_outline_width = Number(preset.outline_width ?? 0) || 0;
}

function applyCurrentTextSettingsToAll(sourceEvent) {
  if (!state.decorationProject || !sourceEvent) return 0;
  if (isGlobalDecorationEvent(sourceEvent)) {
    return applyGlobalDecorationToAllEvents();
  }
  let count = 0;
  for (const eventItem of state.decorationProject.events || []) {
    eventItem.font_preset_id = sourceEvent.font_preset_id || "";
    eventItem.font_family = sourceEvent.font_family || "";
    eventItem.font_size = sourceEvent.font_size ?? null;
    eventItem.font_color = sourceEvent.font_color || "";
    eventItem.font_outline_enabled = sourceEvent.font_outline_enabled ?? true;
    eventItem.font_outline_color = sourceEvent.font_outline_color || "";
    eventItem.font_outline_width = sourceEvent.font_outline_width ?? null;
    eventItem.frame_preset_id = sourceEvent.frame_preset_id || "frame_none";
    eventItem.frame_border_enabled = sourceEvent.frame_border_enabled ?? true;
    eventItem.frame_border_width = sourceEvent.frame_border_width ?? null;
    eventItem.frame_border_color = sourceEvent.frame_border_color || "";
    eventItem.frame_bg_color = sourceEvent.frame_bg_color || "";
    eventItem.frame_bg_opacity = sourceEvent.frame_bg_opacity ?? null;
    eventItem.frame_shadow_depth = sourceEvent.frame_shadow_depth ?? null;
    eventItem.frame_clearance_factor = sourceEvent.frame_clearance_factor ?? null;
    eventItem.frame_clearance_px = sourceEvent.frame_clearance_px ?? null;
    eventItem.frame_wrap_ratio = sourceEvent.frame_wrap_ratio ?? null;
    eventItem.frame_jagged_outer_px = sourceEvent.frame_jagged_outer_px ?? null;
    eventItem.frame_jagged_inner_px = sourceEvent.frame_jagged_inner_px ?? null;
    eventItem.frame_jagged_spacing_px = sourceEvent.frame_jagged_spacing_px ?? null;
    eventItem.frame_jagged_spacing_min_jitter_px = sourceEvent.frame_jagged_spacing_min_jitter_px ?? null;
    eventItem.frame_jagged_spacing_max_jitter_px = sourceEvent.frame_jagged_spacing_max_jitter_px ?? null;
    eventItem.frame_jagged_pattern = sourceEvent.frame_jagged_pattern || "alternate";
    eventItem.frame_halftone_enabled = sourceEvent.frame_halftone_enabled ?? null;
    eventItem.frame_halftone_scale = sourceEvent.frame_halftone_scale ?? null;
    eventItem.frame_halftone_dot_size = sourceEvent.frame_halftone_dot_size ?? null;
    eventItem.frame_halftone_opacity = sourceEvent.frame_halftone_opacity ?? null;
    eventItem.frame_halftone_color = sourceEvent.frame_halftone_color || "";
    eventItem.layout_preset_id = sourceEvent.layout_preset_id || eventItem.layout_preset_id || "layout_bottom_center";
    count += 1;
  }
  return count;
}

function resetDecorationEventTextToPresetDefaults(eventItem) {
  if (!eventItem) return;
  const presetId = eventItem.font_preset_id || decorationFontPresets()[0]?.id || "font_standard";
  applyFontPresetToEvent(eventItem, presetId);
}

function resetDecorationEventFrameToPresetDefaults(eventItem) {
  if (!eventItem) return;
  const presetId = eventItem.frame_preset_id || decorationFramePresets()[0]?.id || "frame_manga_round";
  applyFramePresetToEvent(eventItem, presetId);
}

function sharedDecorationPresetPayload() {
  return {
    effect_library: state.presets.decoration_presets?.effect_library || [],
    screen_effect_library: state.presets.decoration_presets?.screen_effect_library || [],
    screen_effect_stacks: state.decorationProject?.screen_effect_stacks || state.presets.decoration_presets?.screen_effect_stacks || [],
    font_presets: decorationFontPresets(),
    effect_groups: decorationEffectGroups(),
    frame_presets: decorationFramePresets(),
    layout_presets: decorationLayoutPresets(),
    screen_effect_targets: state.decorationProject?.screen_effect_targets || state.presets.decoration_presets?.screen_effect_targets || { global_stack_ids: [], scene_stack_ids: {} },
  };
}

async function saveSharedDecorationPresets() {
  if (!state.decorationProject) return null;
  const payload = {
    project_id: state.projectId || null,
    decoration: sharedDecorationPresetPayload(),
  };
  const data = await api("/api/decoration-presets/global", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setStatus("共通プリセットへ保存しました");
  return data;
}

async function saveCurrentScreenEffectStackAsSharedPreset(stack, name = null) {
  if (!state.decorationProject || !stack) return null;
  const next = screenEffectStackTemplateFromStack(stack, name || stack.name || stack.id);
  const currentShared = [...(state.presets.decoration_presets?.screen_effect_stacks || [])];
  const existingIndex = currentShared.findIndex((item) => item.id === next.id);
  if (existingIndex >= 0) currentShared[existingIndex] = next;
  else currentShared.push(next);
  if (!state.presets.decoration_presets) state.presets.decoration_presets = {};
  state.presets.decoration_presets.screen_effect_stacks = currentShared;
  await saveSharedDecorationPresets();
  return next;
}

function decorationLayoutPresets() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  const base = presets.layout_presets && presets.layout_presets.length ? presets.layout_presets : [];
  const merged = new Map(base.map((preset) => [preset.id, preset]));
  for (const preset of project.layout_presets || []) {
    const id = preset.id || `layout_${Math.random().toString(16).slice(2, 8)}`;
    merged.set(id, { ...(merged.get(id) || {}), ...preset, id });
  }
  return [...merged.values()].map((preset) => ({ ...preset }));
}

function buildDecorationProjectFromSubtitles(source = null) {
  const subtitles = source?.subtitles?.length ? source.subtitles : decorationSourceSubtitles();
  const presets = state.presets.decoration_presets || {};
  const scenes = sceneCatalogFromSubtitles(subtitles);
  state.decorationProject = {
    project_id: state.projectId,
    source_srt: source?.path || (state.editPlanPath ? "subtitles/edited.srt" : "subtitles/original.srt"),
    global_event: defaultGlobalDecorationEvent(),
    events: subtitles.map((sub, index) => {
      const frame = effectiveFrameForEvent(sub);
      return {
      emotion_preset_id: emotionPresetForEmotion(sub.emotion).id,
      id: sub.id,
      subtitle_id: sub.subtitle_id,
      text: sub.text,
      start_sec: sub.start_sec,
      end_sec: sub.end_sec,
      scene_id: subtitleSceneId(index),
      speaker_label: sub.speaker_label,
      emotion: sub.emotion,
      subtitle_style_preset_id: sub.subtitle_style_preset_id || emotionPresetForEmotion(sub.emotion).subtitle_style_preset_id || "subtitle_standard",
      effect_group_id: sub.effect_group_id || emotionPresetForEmotion(sub.emotion).effect_group_id || (presets.effect_groups?.[0]?.id || ""),
      text_effect_group_id: sub.text_effect_group_id || sub.effect_group_id || emotionPresetForEmotion(sub.emotion).effect_group_id || (presets.effect_groups?.[0]?.id || ""),
      frame_preset_id: frame.id,
      frame_border_enabled: sub.frame_border_enabled ?? frame.border_enabled,
      frame_border_width: sub.frame_border_width ?? frame.border_width,
      frame_border_color: sub.frame_border_color || frame.border_color,
      frame_bg_color: sub.frame_bg_color || frame.bg_color,
      frame_bg_opacity: sub.frame_bg_opacity ?? frame.bg_opacity,
      frame_shadow_depth: sub.frame_shadow_depth ?? frame.shadow_depth,
      frame_clearance_factor: sub.frame_clearance_factor ?? frame.clearance_factor,
      frame_clearance_px: sub.frame_clearance_px ?? frame.clearance_px,
      frame_wrap_ratio: sub.frame_wrap_ratio ?? frame.wrap_ratio,
      frame_jagged_outer_px: sub.frame_jagged_outer_px ?? frame.jagged_outer_px,
      frame_jagged_inner_px: sub.frame_jagged_inner_px ?? frame.jagged_inner_px,
      frame_jagged_spacing_px: sub.frame_jagged_spacing_px ?? frame.jagged_spacing_px,
      frame_jagged_spacing_min_jitter_px: sub.frame_jagged_spacing_min_jitter_px ?? frame.jagged_spacing_min_jitter_px,
      frame_jagged_spacing_max_jitter_px: sub.frame_jagged_spacing_max_jitter_px ?? frame.jagged_spacing_max_jitter_px,
      frame_jagged_pattern: sub.frame_jagged_pattern ?? frame.jagged_pattern,
      frame_halftone_enabled: sub.frame_halftone_enabled ?? frame.halftone_enabled,
      frame_halftone_scale: sub.frame_halftone_scale ?? frame.halftone_scale,
      frame_halftone_dot_size: sub.frame_halftone_dot_size ?? frame.halftone_dot_size,
      frame_halftone_opacity: sub.frame_halftone_opacity ?? frame.halftone_opacity,
      frame_halftone_color: sub.frame_halftone_color || frame.halftone_color,
      font_preset_id: sub.font_preset_id || emotionPresetForEmotion(sub.emotion).font_preset_id || (presets.font_presets?.[0]?.id || "font_standard"),
      font_family: sub.font_family || "",
      font_size: sub.font_size || null,
      font_color: sub.font_color || "",
      font_outline_enabled: sub.font_outline_enabled ?? true,
      font_outline_color: sub.font_outline_color || "",
      font_outline_width: sub.font_outline_width ?? null,
      layout_preset_id: sub.layout_preset_id || presets.layout_presets?.[0]?.id || "layout_bottom_center",
      layout_offset_x_px: sub.layout_offset_x_px ?? (decorationLayoutPresets().find((preset) => preset.id === (sub.layout_preset_id || "layout_bottom_center"))?.offset_x_px ?? 0),
      layout_offset_y_px: sub.layout_offset_y_px ?? (decorationLayoutPresets().find((preset) => preset.id === (sub.layout_preset_id || "layout_bottom_center"))?.offset_y_px ?? 18),
      seed: sub.seed,
      enabled: sub.enabled,
      style_override_enabled: false,
      };
    }),
    effect_groups: decorationEffectGroups(),
    screen_effect_stacks: [],
    font_presets: decorationFontPresets(),
    layout_presets: decorationLayoutPresets(),
    frame_presets: decorationFramePresets(),
    screen_effect_targets: {
      global_stack_ids: [],
      scene_stack_ids: {},
    },
    scenes,
  };
  state.decorationSelectionId = state.decorationProject.events[0]?.id || null;
  state.screenEffectSelectedStackId = "";
  renderDecorationPage();
  return state.decorationProject;
}

function syncDecorationEventsFromSubtitles(source = null) {
  const previous = state.decorationProject ? normalizeDecorationProject(state.decorationProject) : null;
  const previousByKey = new Map();
  for (const eventItem of previous?.events || []) {
    const keys = [eventItem.subtitle_id, eventItem.id].map((item) => String(item || "").trim()).filter(Boolean);
    keys.forEach((key) => previousByKey.set(key, eventItem));
  }
  buildDecorationProjectFromSubtitles(source);
  if (!state.decorationProject || !previous) return state.decorationProject;
  state.decorationProject.effect_groups = previous.effect_groups?.length ? previous.effect_groups : state.decorationProject.effect_groups;
  state.decorationProject.screen_effect_stacks = previous.screen_effect_stacks || [];
  state.decorationProject.font_presets = previous.font_presets?.length ? previous.font_presets : state.decorationProject.font_presets;
  state.decorationProject.layout_presets = previous.layout_presets?.length ? previous.layout_presets : state.decorationProject.layout_presets;
  state.decorationProject.frame_presets = previous.frame_presets?.length ? previous.frame_presets : state.decorationProject.frame_presets;
  state.decorationProject.global_event = previous.global_event || state.decorationProject.global_event || defaultGlobalDecorationEvent();
  state.decorationProject.screen_effect_targets = previous.screen_effect_targets || state.decorationProject.screen_effect_targets;
  state.decorationProject.events = state.decorationProject.events.map((eventItem) => {
    const previousEvent = previousByKey.get(String(eventItem.subtitle_id || "").trim()) || previousByKey.get(String(eventItem.id || "").trim());
    if (!previousEvent) return eventItem;
    return {
      ...previousEvent,
      id: eventItem.id,
      subtitle_id: eventItem.subtitle_id,
      text: eventItem.text,
      start_sec: eventItem.start_sec,
      end_sec: eventItem.end_sec,
      scene_id: eventItem.scene_id,
      speaker_label: eventItem.speaker_label,
      enabled: eventItem.enabled,
    };
  });
  state.decorationSelectionId = state.decorationProject.events.find((item) => item.id === previous?.events?.find((eventItem) => eventItem.id === state.decorationSelectionId)?.id)?.id || state.decorationProject.events[0]?.id || null;
  return state.decorationProject;
}

function currentDecorationEvent() {
  if (!state.decorationProject) return null;
  if (state.decorationSelectionId === DECORATION_GLOBAL_ID) return globalDecorationEvent();
  if (!state.decorationProject.events?.length) return globalDecorationEvent();
  return state.decorationProject.events.find((item) => item.id === state.decorationSelectionId) || state.decorationProject.events[0] || null;
}

function setDecorationEditTab(tab) {
  state.decorationEditTab = ["text", "frame", "text_effect", "zoom", "screen_effect"].includes(tab) ? tab : "text";
  renderDecorationPage();
  updateZoomBoxOverlay();
}

function decorationEventForSubtitle(sub) {
  if (!sub || !state.decorationProject?.events?.length) return null;
  const key = String(sub.subtitle_id || sub.id || "").trim();
  if (!key) return null;
  const eventItem = state.decorationProject.events.find((item) => String(item.subtitle_id || "").trim() === key || String(item.id || "").trim() === key) || null;
  if (!eventItem) return null;
  return {
    ...eventItem,
    text: sub.text ?? eventItem.text,
    start_sec: sub.output_start_sec ?? eventItem.start_sec,
    end_sec: sub.output_end_sec ?? eventItem.end_sec,
    speaker_label: sub.speaker_label ?? eventItem.speaker_label,
    enabled: sub.enabled ?? eventItem.enabled,
  };
}

function buildDecorationPreviewNode(eventItem, options = {}) {
  const { compact = false, includeMeta = true, includeChips = true } = options;
  if (!eventItem) return null;
  const selected = eventItem;
  const preview = document.createElement("div");
  preview.className = compact ? "decoration-preview decoration-preview-compact" : "decoration-preview";
  preview.style.display = "flex";
  preview.style.flexDirection = "column";
  preview.style.alignItems = "flex-start";
  preview.style.gap = compact ? "6px" : "8px";
  preview.style.width = "100%";
  preview.style.boxSizing = "border-box";
  const theme = emotionVisualTheme(selected.emotion);
  const activeFrame = effectiveFrameForEvent(selected);
  const activeFont = effectiveFontForEvent(selected);
  const frameClearancePx = Number.isFinite(Number(activeFrame.clearance_factor))
    ? Math.max(0, Math.round((Number(activeFont.size) || 44) * Number(activeFrame.clearance_factor)))
    : Math.max(0, Number(activeFrame.clearance_px) || 0);
  const previewFrameWrapRatio = Math.max(0.4, Math.min(0.98, Number(activeFrame.wrap_ratio) || 0.88));
  const previewHalftoneEnabled = activeFrame.halftone_enabled === true;
  const previewHalftoneScale = Math.max(4, Number(activeFrame.halftone_scale) || 16);
  const previewHalftoneDotSize = Math.max(1, Math.min(previewHalftoneScale * 0.45, Number(activeFrame.halftone_dot_size) || 2));
  const previewHalftoneOpacity = Math.max(0, Math.min(1, Number(activeFrame.halftone_opacity) || 0));
  const previewHalftoneColor = activeFrame.bg_color || activeFrame.halftone_color || "#222222";
  const subtitleFrame = document.createElement("div");
  subtitleFrame.style.display = "inline-flex";
  subtitleFrame.style.flexDirection = "column";
  subtitleFrame.style.alignItems = "flex-start";
  subtitleFrame.style.width = "fit-content";
  subtitleFrame.style.maxWidth = `${Math.round(previewFrameWrapRatio * 100)}%`;
  subtitleFrame.style.boxSizing = "border-box";
  subtitleFrame.style.position = "relative";
  subtitleFrame.style.overflow = "hidden";
  subtitleFrame.style.background = previewHalftoneEnabled ? "transparent" : hexToRgba(activeFrame.bg_color || "#ffffff", activeFrame.bg_opacity ?? 0.9);
  subtitleFrame.style.borderColor = activeFrame.border_color || theme.border;
  subtitleFrame.style.borderStyle = activeFrame.border_enabled === false ? "dashed" : "solid";
  subtitleFrame.style.borderWidth = `${Math.max(1, Number(activeFrame.border_width) || 1)}px`;
  subtitleFrame.style.borderRadius = activeFrame.id === "frame_manga_jagged" ? "18px 20px 14px 22px" : activeFrame.id === "frame_cloud_soft" ? "28px" : activeFrame.id === "frame_narration_top" || activeFrame.id === "frame_narration_bottom" ? "0px" : activeFrame.id === "frame_square" ? "2px" : "8px";
  subtitleFrame.style.boxShadow = activeFrame.id === "frame_cloud_soft" ? "0 8px 18px rgba(120, 124, 140, 0.16)" : activeFrame.id === "frame_narration_top" || activeFrame.id === "frame_narration_bottom" ? "none" : activeFrame.id === "frame_shadow_box" ? "0 12px 24px rgba(15, 23, 42, 0.28)" : activeFrame.id === "frame_note_paper" ? "0 6px 12px rgba(120, 96, 0, 0.14)" : "none";
  if (activeFrame.id === "frame_manga_jagged" || (activeFrame.effects || []).includes("jagged")) {
    subtitleFrame.style.clipPath = jaggedFrameClipPath({ ...activeFrame, seed: selected.seed });
    subtitleFrame.style.borderRadius = "0";
  }
  subtitleFrame.style.color = activeFont.color || "#111111";
  subtitleFrame.style.padding = `${Math.max(18, Math.round((Number(activeFont.size) || 44) * 0.6) + frameClearancePx)}px ${Math.max(24, Math.round((Number(activeFont.size) || 44) * 0.95) + frameClearancePx)}px`;
  if (previewHalftoneEnabled && previewHalftoneOpacity > 0) {
    const halftoneLayer = document.createElement("div");
    halftoneLayer.style.position = "absolute";
    halftoneLayer.style.inset = "0";
    halftoneLayer.style.pointerEvents = "none";
    halftoneLayer.style.borderRadius = "inherit";
    halftoneLayer.style.opacity = String(previewHalftoneOpacity);
    halftoneLayer.style.backgroundImage = `radial-gradient(circle, ${previewHalftoneColor} 0 ${previewHalftoneDotSize}px, transparent ${previewHalftoneDotSize}px ${previewHalftoneScale}px)`;
    halftoneLayer.style.backgroundSize = `${previewHalftoneScale}px ${previewHalftoneScale}px`;
    halftoneLayer.style.mixBlendMode = "multiply";
    subtitleFrame.appendChild(halftoneLayer);
  }
  const previewRotation = Number(selected.text_rotation_deg ?? selected.font_rotation_deg ?? selected.subtitle_rotation_deg ?? selected.angle ?? 0) || 0;
  if (previewRotation) {
    subtitleFrame.style.transform = `rotate(${previewRotation}deg)`;
    subtitleFrame.style.transformOrigin = "center center";
  }
  if (includeMeta) {
    const previewMeta = document.createElement("div");
    previewMeta.textContent = `${fmtTime(selected.start_sec)} - ${fmtTime(selected.end_sec)} / ${selected.scene_id || "sceneなし"} / ${selected.speaker_label || "speakerなし"}`;
    preview.appendChild(previewMeta);
  }
  const previewLine = document.createElement("div");
  previewLine.className = "preview-line";
  previewLine.style.maxWidth = "100%";
  previewLine.style.overflowWrap = "anywhere";
  previewLine.style.wordBreak = "break-word";
  previewLine.style.whiteSpace = "pre-wrap";
  previewLine.style.fontFamily = activeFont.family || "Meiryo";
  previewLine.style.fontSize = `${Math.max(12, Math.min(72, Number(activeFont.size) || 44))}px`;
  previewLine.style.lineHeight = "1.2";
  if (activeFont.outline_enabled !== false && Number(activeFont.outline_width || 0) > 0) {
    const outlineColor = activeFont.outline_color || "#000000";
    const outline = Math.max(1, Math.min(8, Number(activeFont.outline_width) || 1));
    previewLine.style.textShadow = [
      `${outline}px 0 ${outlineColor}`,
      `-${outline}px 0 ${outlineColor}`,
      `0 ${outline}px ${outlineColor}`,
      `0 -${outline}px ${outlineColor}`,
    ].join(",");
  }
  previewLine.textContent = selected.text || "";
  subtitleFrame.appendChild(previewLine);
  preview.appendChild(subtitleFrame);
  if (includeChips) {
    const chipRow = document.createElement("div");
    chipRow.className = "decoration-chip-list";
    const effective = effectiveDecorationForEvent(selected);
    [effective.subtitle_style_preset_id || "styleなし", activeFrame.name || effective.frame_preset_id || "frameなし", effective.text_effect_group_id || "effectなし"].forEach((label, idx) => {
      const chip = document.createElement("span");
      chip.className = "decoration-chip";
      chip.textContent = label;
      if (idx >= 2) chip.style.borderColor = theme.chip;
      chipRow.appendChild(chip);
    });
    preview.appendChild(chipRow);
  }
  return preview;
}

function normalizeDecorationProject(decoration) {
  if (!decoration) return null;
  return {
    ...decoration,
    global_event: decoration.global_event || defaultGlobalDecorationEvent(),
    effect_groups: Array.isArray(decoration.effect_groups) ? decoration.effect_groups : [],
    screen_effect_stacks: Array.isArray(decoration.screen_effect_stacks) ? decoration.screen_effect_stacks : [],
    font_presets: Array.isArray(decoration.font_presets) ? decoration.font_presets : [],
    layout_presets: Array.isArray(decoration.layout_presets) ? decoration.layout_presets : [],
    frame_presets: Array.isArray(decoration.frame_presets) ? decoration.frame_presets : [],
    events: (Array.isArray(decoration.events) ? decoration.events : []).map((eventItem, index) => ({
      ...eventItem,
      scene_id: subtitleSceneId(index),
      text_effect_group_id: eventItem.text_effect_group_id || eventItem.effect_group_id || "",
      frame_preset_id: eventItem.frame_preset_id || "frame_none",
      frame_border_enabled: eventItem.frame_border_enabled ?? effectiveFrameForEvent(eventItem).border_enabled,
      frame_border_width: eventItem.frame_border_width ?? effectiveFrameForEvent(eventItem).border_width,
      frame_border_color: eventItem.frame_border_color || effectiveFrameForEvent(eventItem).border_color,
      frame_bg_color: eventItem.frame_bg_color || effectiveFrameForEvent(eventItem).bg_color,
      frame_bg_opacity: eventItem.frame_bg_opacity ?? effectiveFrameForEvent(eventItem).bg_opacity,
      frame_shadow_depth: eventItem.frame_shadow_depth ?? effectiveFrameForEvent(eventItem).shadow_depth,
      frame_clearance_factor: eventItem.frame_clearance_factor ?? effectiveFrameForEvent(eventItem).clearance_factor,
      frame_clearance_px: eventItem.frame_clearance_px ?? effectiveFrameForEvent(eventItem).clearance_px,
      frame_wrap_ratio: eventItem.frame_wrap_ratio ?? effectiveFrameForEvent(eventItem).wrap_ratio,
      frame_jagged_outer_px: eventItem.frame_jagged_outer_px ?? effectiveFrameForEvent(eventItem).jagged_outer_px,
      frame_jagged_inner_px: eventItem.frame_jagged_inner_px ?? effectiveFrameForEvent(eventItem).jagged_inner_px,
      frame_jagged_spacing_px: eventItem.frame_jagged_spacing_px ?? effectiveFrameForEvent(eventItem).jagged_spacing_px,
      frame_jagged_spacing_min_jitter_px: eventItem.frame_jagged_spacing_min_jitter_px ?? effectiveFrameForEvent(eventItem).jagged_spacing_min_jitter_px,
      frame_jagged_spacing_max_jitter_px: eventItem.frame_jagged_spacing_max_jitter_px ?? effectiveFrameForEvent(eventItem).jagged_spacing_max_jitter_px,
      frame_jagged_pattern: eventItem.frame_jagged_pattern ?? effectiveFrameForEvent(eventItem).jagged_pattern,
      frame_halftone_enabled: eventItem.frame_halftone_enabled ?? effectiveFrameForEvent(eventItem).halftone_enabled,
      frame_halftone_scale: eventItem.frame_halftone_scale ?? effectiveFrameForEvent(eventItem).halftone_scale,
      frame_halftone_dot_size: eventItem.frame_halftone_dot_size ?? effectiveFrameForEvent(eventItem).halftone_dot_size,
      frame_halftone_opacity: eventItem.frame_halftone_opacity ?? effectiveFrameForEvent(eventItem).halftone_opacity,
      frame_halftone_color: eventItem.frame_halftone_color || effectiveFrameForEvent(eventItem).halftone_color,
      font_outline_enabled: eventItem.font_outline_enabled ?? true,
    })),
    screen_effect_targets: {
      global_stack_ids: [...new Set((decoration.screen_effect_targets?.global_stack_ids || []).map((item) => String(item || "").trim()).filter(Boolean))],
      scene_stack_ids: Object.fromEntries(
        Object.entries(decoration.screen_effect_targets?.scene_stack_ids || {}).map(([sceneId, stackIds]) => [
          String(sceneId || "").trim(),
          [...new Set((stackIds || []).map((item) => String(item || "").trim()).filter(Boolean))],
        ]),
      ),
    },
  };
}

async function loadDecorationProjectFromServer() {
  if (!state.projectId) return null;
  const data = await api(`/api/projects/${state.projectId}/decoration`, { method: "GET" });
  state.decorationProject = normalizeDecorationProject(data.decoration || null);
  if (state.decorationProject?.events?.length) {
    state.decorationProject.scenes = sceneCatalogFromSubtitles(state.decorationProject.events.filter((item) => !isGlobalDecorationEvent(item)));
    state.projectScenes = [...state.decorationProject.scenes];
    renderScenes();
  }
  if (state.decorationProject?.events?.length) {
    state.decorationSelectionId = state.decorationProject.events[0].id;
  }
  state.screenEffectSelectedStackId = state.decorationProject?.screen_effect_stacks?.[0]?.id || "";
  renderDecorationPage();
  return state.decorationProject;
}

async function reloadDecorationFromSource() {
  if (subtitleItems().length) {
    await persistCurrentSubtitles();
  }
  const source = await fetchDecorationSourceSubtitles();
  syncDecorationEventsFromSubtitles(source);
  if (state.decorationProject) state.decorationProject.source_srt = source.path || state.decorationProject.source_srt;
  renderDecorationPage();
  return source;
}

async function saveDecorationProject() {
  if (!state.projectId) return null;
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  if (state.frameSyncMode !== "live") {
    const selected = currentDecorationEvent();
    if (selected) syncFramePresetToLinkedEvents(selected, true);
  }
  const payload = {
    project_id: state.projectId,
    decoration: {
      ...state.decorationProject,
      scenes: sceneCatalog(),
    },
  };
  const data = await api("/api/projects/decoration", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const previousGlobalEvent = state.decorationProject?.global_event || null;
  const savedDecoration = data.decoration || state.decorationProject;
  if (savedDecoration && !savedDecoration.global_event && previousGlobalEvent) {
    savedDecoration.global_event = previousGlobalEvent;
  }
  state.decorationProject = normalizeDecorationProject(savedDecoration);
  if (state.decorationProject?.events?.length) {
    state.decorationProject.scenes = sceneCatalogFromSubtitles(state.decorationProject.events.filter((item) => !isGlobalDecorationEvent(item)));
    state.projectScenes = [...state.decorationProject.scenes];
    renderScenes();
  }
  renderDecorationPage();
  return data.decoration;
}

function downloadDecorationProjectJson() {
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  const blob = new Blob([JSON.stringify(state.decorationProject, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${state.projectId || "decoration"}_decoration_project.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderDecorationPage() {
  const list = $("decorationList");
  const detail = $("decorationDetail");
  const groupList = $("effectGroupList");
  const previewVideo = $("decorationPreviewVideo");
  if (!list || !detail || !groupList) return;
  const project = state.decorationProject;
  const events = project?.events || [];
  const groups = decorationEffectGroups();
  $("decorationCount").textContent = `${events.length}件`;
  $("effectGroupCount").textContent = `${groups.length}件`;
  $("decorationSelectionLabel").textContent = currentDecorationEvent()?.id || "未選択";
  $("decorationPreviewState").textContent = `${selectedDecorationSourceKind()} / ${project?.source_srt || "未設定"}`;
  $("decorationPreviewLabel").textContent = state.decorationPreviewUrl ? "生成済み" : "未生成";
  $("textEffectSection")?.classList.toggle("hidden-panel", state.decorationEditTab !== "text_effect");
  $("screenEffectSection")?.classList.toggle("hidden-panel", state.decorationEditTab !== "screen_effect");
  updateZoomBoxOverlay();
  if (previewVideo) {
    const nextSrc = state.decorationPreviewUrl || (state.decorationEditTab === "zoom" ? state.sourceVideoUrl || "" : "");
    if ((previewVideo.dataset.currentSrc || "") !== nextSrc) {
      const wasPlaying = !previewVideo.paused && !previewVideo.ended;
      previewVideo.pause();
      previewVideo.dataset.currentSrc = nextSrc;
      if (nextSrc) {
        previewVideo.src = nextSrc;
        previewVideo.load();
        previewVideo.style.filter = "none";
        updateDecorationShaderEffects([]);
        if (wasPlaying) {
          previewVideo.play().then(() => startDecorationShaderLoop()).catch((err) => {
            if (String(err?.name || "") !== "AbortError") console.warn(err);
          });
        }
      }
    }
  }
  list.textContent = "";
  groupList.textContent = "";
  if (!project) {
    detail.textContent = "字幕から生成するとここで装飾を編集できます。";
  } else {
    const selected = currentDecorationEvent();
    const activeFont = effectiveFontForEvent(selected);
    const activeFrame = effectiveFrameForEvent(selected);
    $("decorationSelectionLabel").textContent = selected ? (isGlobalDecorationEvent(selected) ? "全体シーンへ適用" : selected.id) : "未選択";
    detail.textContent = "";
    if (detail.dataset.overrideBound !== "1") {
      detail.dataset.overrideBound = "1";
      detail.addEventListener("input", () => markDecorationEventOverride(currentDecorationEvent()), true);
      detail.addEventListener("change", () => markDecorationEventOverride(currentDecorationEvent()), true);
    }
    if (selected) {
      const preview = buildDecorationPreviewNode(selected, { compact: false, includeMeta: true, includeChips: true });
      detail.appendChild(preview);

      const tabBar = document.createElement("div");
      tabBar.className = "decoration-tabs";
      [
        { id: "text", label: "テキスト" },
        { id: "frame", label: "枠" },
        { id: "text_effect", label: "文字連動" },
        { id: "zoom", label: "拡大・縮小" },
        { id: "screen_effect", label: "画面効果" },
      ].forEach((tab) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = tab.label;
        button.className = state.decorationEditTab === tab.id ? "active" : "";
        button.addEventListener("click", () => setDecorationEditTab(tab.id));
        tabBar.appendChild(button);
      });
      detail.appendChild(tabBar);

      const makeField = (labelText, control) => {
        const label = document.createElement("label");
        label.textContent = labelText;
        label.appendChild(control);
        return label;
      };
      const textFields = document.createElement("div");
      textFields.className = `decoration-fields${state.decorationEditTab !== "text" ? " hidden-panel" : ""}`;
      const frameFields = document.createElement("div");
      frameFields.className = `decoration-fields${state.decorationEditTab !== "frame" ? " hidden-panel" : ""}`;
      const effectFields = document.createElement("div");
      effectFields.className = `decoration-fields${state.decorationEditTab !== "text_effect" ? " hidden-panel" : ""}`;
      const zoomFields = document.createElement("div");
      zoomFields.className = `decoration-fields${state.decorationEditTab !== "zoom" ? " hidden-panel" : ""}`;

      const fontPreset = presetOptions(decorationFontPresets(), selected.font_preset_id || activeFont.id || "", "");
      fontPreset.addEventListener("change", () => {
        applyFontPresetToEvent(selected, fontPreset.value || "");
        renderDecorationPage();
      });
      const fontFamily = document.createElement("select");
      const fonts = state.systemFonts?.length ? state.systemFonts : ["Meiryo", "Yu Gothic", "Yu Mincho", "MS Gothic", "MS Mincho"];
      for (const name of fonts) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        fontFamily.appendChild(option);
      }
      fontFamily.value = activeFont.family;
      if (!fontFamily.value && activeFont.family) {
        const fallback = fonts[0] || "Meiryo";
        fontFamily.value = fallback;
      }
      fontFamily.addEventListener("change", () => {
        selected.font_family = fontFamily.value || "Yu Gothic";
      });
      const fontSize = document.createElement("input");
      fontSize.type = "number";
      fontSize.min = "8";
      fontSize.step = "1";
      fontSize.value = String(activeFont.size || 44);
      fontSize.addEventListener("change", () => {
        selected.font_size = Number(fontSize.value) || 44;
        if (Number.isFinite(Number(selected.frame_clearance_factor))) {
          selected.frame_wrap_ratio = suggestedWrapRatioForClearance(selected.font_size, selected.frame_clearance_factor);
          frameWrapRatio.value = String(selected.frame_wrap_ratio.toFixed(2));
        }
      });
      const fontColor = document.createElement("input");
      fontColor.type = "color";
      fontColor.value = activeFont.color || "#ffffff";
      fontColor.addEventListener("input", () => {
        selected.font_color = fontColor.value || "#ffffff";
      });
      const outlineEnabled = document.createElement("input");
      outlineEnabled.type = "checkbox";
      outlineEnabled.checked = activeFont.outline_enabled !== false;
      outlineEnabled.addEventListener("change", () => {
        selected.font_outline_enabled = outlineEnabled.checked;
      });
      const outlineColor = document.createElement("input");
      outlineColor.type = "color";
      outlineColor.value = activeFont.outline_color || "#000000";
      outlineColor.addEventListener("input", () => {
        selected.font_outline_color = outlineColor.value || "#000000";
      });
      const outlineWidth = document.createElement("input");
      outlineWidth.type = "number";
      outlineWidth.min = "0";
      outlineWidth.step = "1";
      outlineWidth.value = String(activeFont.outline_width ?? 4);
      outlineWidth.addEventListener("change", () => {
        selected.font_outline_width = Math.max(0, Number(outlineWidth.value) || 0);
      });
      const text = document.createElement("textarea");
      text.value = isGlobalDecorationEvent(selected) ? "全体設定" : (selected.text || "");
      text.disabled = isGlobalDecorationEvent(selected);
      text.addEventListener("input", () => {
        selected.text = text.value;
      });
      const speaker = document.createElement("input");
      speaker.value = selected.speaker_label || "";
      speaker.addEventListener("input", () => {
        selected.speaker_label = speaker.value;
      });

      const makeFrameSelect = () => {
        const frameSelect = presetOptions(decorationFramePresets(), effectiveDecorationForEvent(selected).frame_preset_id || "", "");
        frameSelect.addEventListener("change", () => {
          applyFramePresetToEvent(selected, frameSelect.value || "frame_none");
          if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
          renderDecorationPage();
        });
        return frameSelect;
      };
      const textFrame = makeFrameSelect();
      const frame = makeFrameSelect();
      const effect = presetOptions(groups, effectiveDecorationForEvent(selected).text_effect_group_id || "", "");
      effect.addEventListener("change", () => {
        selected.text_effect_group_id = effect.value || "";
        selected.effect_group_id = selected.text_effect_group_id;
        renderDecorationPage();
      });
      const layout = presetOptions(decorationLayoutPresets(), selected.layout_preset_id || "", "");
      layout.addEventListener("change", () => {
        selected.layout_preset_id = layout.value || "";
        const layoutPreset = decorationLayoutPresets().find((preset) => preset.id === selected.layout_preset_id);
        const layoutDefaultOffsetY = String(layoutPreset?.anchor || "").startsWith("bottom_") ? 18 : 0;
        selected.layout_offset_x_px = Number.isFinite(Number(layoutPreset?.offset_x_px)) ? Number(layoutPreset.offset_x_px) : 0;
        selected.layout_offset_y_px = Number.isFinite(Number(layoutPreset?.offset_y_px)) ? Number(layoutPreset.offset_y_px) : layoutDefaultOffsetY;
        renderDecorationPage();
      });
      const activeLayoutPreset = decorationLayoutPresets().find((preset) => preset.id === (selected.layout_preset_id || ""));
      const layoutOffsetX = document.createElement("input");
      layoutOffsetX.type = "number";
      layoutOffsetX.min = "-360";
      layoutOffsetX.max = "360";
      layoutOffsetX.step = "1";
      layoutOffsetX.value = String(
        Number.isFinite(Number(effectiveDecorationForEvent(selected).layout_offset_x_px))
          ? Number(effectiveDecorationForEvent(selected).layout_offset_x_px)
          : Number(activeLayoutPreset?.offset_x_px ?? 0),
      );
      layoutOffsetX.addEventListener("change", () => {
        selected.layout_offset_x_px = Math.max(-360, Math.min(360, Number(layoutOffsetX.value) || 0));
        renderDecorationPage();
      });
      const activeLayoutDefaultOffsetY = String(activeLayoutPreset?.anchor || "").startsWith("bottom_") ? 18 : 0;
      const layoutOffsetY = document.createElement("input");
      layoutOffsetY.type = "number";
      layoutOffsetY.min = "-240";
      layoutOffsetY.max = "240";
      layoutOffsetY.step = "1";
      layoutOffsetY.value = String(
        Number.isFinite(Number(effectiveDecorationForEvent(selected).layout_offset_y_px))
          ? Number(effectiveDecorationForEvent(selected).layout_offset_y_px)
          : Number(activeLayoutPreset?.offset_y_px ?? activeLayoutDefaultOffsetY),
      );
      layoutOffsetY.addEventListener("change", () => {
        selected.layout_offset_y_px = Math.max(-240, Math.min(240, Number(layoutOffsetY.value) || 0));
        renderDecorationPage();
      });
      const seedInput = document.createElement("input");
      seedInput.type = "number";
      seedInput.value = Number(selected.seed || 0);
      seedInput.addEventListener("change", () => {
        selected.seed = Number(seedInput.value) || 0;
      });
      const frameBorderEnabled = document.createElement("input");
      frameBorderEnabled.type = "checkbox";
      frameBorderEnabled.checked = activeFrame.border_enabled !== false;
      frameBorderEnabled.addEventListener("change", () => {
        selected.frame_border_enabled = frameBorderEnabled.checked;
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameBorderWidth = document.createElement("input");
      frameBorderWidth.type = "number";
      frameBorderWidth.min = "0";
      frameBorderWidth.step = "1";
      frameBorderWidth.value = String(activeFrame.border_width ?? 4);
      frameBorderWidth.addEventListener("change", () => {
        selected.frame_border_width = Math.max(0, Number(frameBorderWidth.value) || 0);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameBorderColor = document.createElement("input");
      frameBorderColor.type = "color";
      frameBorderColor.value = activeFrame.border_color || "#000000";
      frameBorderColor.addEventListener("input", () => {
        selected.frame_border_color = frameBorderColor.value || "#000000";
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameBgColor = document.createElement("input");
      frameBgColor.type = "color";
      frameBgColor.value = activeFrame.bg_color || "#ffffff";
      frameBgColor.addEventListener("input", () => {
        selected.frame_bg_color = frameBgColor.value || "#ffffff";
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameBgOpacity = document.createElement("input");
      frameBgOpacity.type = "number";
      frameBgOpacity.min = "0";
      frameBgOpacity.max = "1";
      frameBgOpacity.step = "0.01";
      frameBgOpacity.value = String(activeFrame.bg_opacity ?? 0.9);
      frameBgOpacity.addEventListener("input", () => {
        selected.frame_bg_opacity = Number(frameBgOpacity.value) || 0;
        if (selected.frame_bg_opacity <= 0) {
          selected.frame_border_enabled = false;
          selected.frame_shadow_depth = 0;
        }
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameClearance = document.createElement("select");
      [
        [0.5, "0.5文字分"],
        [1.0, "1文字分"],
        [1.5, "1.5文字分"],
        [2.0, "2文字分"],
        [2.5, "2.5文字分"],
      ].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = label;
        frameClearance.appendChild(option);
      });
      const clearanceFallback = Number.isFinite(Number(activeFrame.clearance_factor))
        ? Number(activeFrame.clearance_factor)
        : Math.max(0.5, Math.min(2.5, (Number(activeFrame.clearance_px) || 0) / Math.max(1, Number(activeFont.size) || 44))) || 0.5;
      const clearanceChoices = [0.5, 1.0, 1.5, 2.0, 2.5];
      const nearestClearance = clearanceChoices.reduce((best, value) => (Math.abs(value - clearanceFallback) < Math.abs(best - clearanceFallback) ? value : best), clearanceChoices[0]);
      frameClearance.value = String(nearestClearance);
      frameClearance.addEventListener("change", () => {
        const factor = Math.max(0.5, Math.min(2.5, Number(frameClearance.value) || 0.5));
        selected.frame_clearance_factor = factor;
        selected.frame_clearance_px = Math.max(0, Math.round((Number(activeFont.size) || 44) * factor));
        selected.frame_wrap_ratio = suggestedWrapRatioForClearance(Number(activeFont.size) || 44, factor);
        frameWrapRatio.value = String(selected.frame_wrap_ratio.toFixed(2));
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameWrapRatio = document.createElement("input");
      frameWrapRatio.type = "number";
      frameWrapRatio.min = "0.4";
      frameWrapRatio.max = "0.98";
      frameWrapRatio.step = "0.01";
      frameWrapRatio.value = String(
        Number.isFinite(Number(activeFrame.clearance_factor))
          ? suggestedWrapRatioForClearance(Number(activeFont.size) || 44, Number(activeFrame.clearance_factor)).toFixed(2)
          : (activeFrame.wrap_ratio ?? 0.88),
      );
      frameWrapRatio.addEventListener("change", () => {
        const next = Number(frameWrapRatio.value);
        selected.frame_wrap_ratio = Math.max(0.4, Math.min(0.98, Number.isFinite(next) ? next : 0.88));
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedOuter = document.createElement("input");
      frameJaggedOuter.type = "number";
      frameJaggedOuter.min = "1";
      frameJaggedOuter.max = "80";
      frameJaggedOuter.step = "1";
      frameJaggedOuter.value = String(activeFrame.jagged_outer_px ?? 14);
      frameJaggedOuter.addEventListener("change", () => {
        selected.frame_jagged_outer_px = Math.max(1, Number(frameJaggedOuter.value) || 14);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedInner = document.createElement("input");
      frameJaggedInner.type = "number";
      frameJaggedInner.min = "0";
      frameJaggedInner.max = "80";
      frameJaggedInner.step = "1";
      frameJaggedInner.value = String(activeFrame.jagged_inner_px ?? 5);
      frameJaggedInner.addEventListener("change", () => {
        selected.frame_jagged_inner_px = Math.max(0, Number(frameJaggedInner.value) || 0);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedSpacing = document.createElement("input");
      frameJaggedSpacing.type = "number";
      frameJaggedSpacing.min = "6";
      frameJaggedSpacing.max = "120";
      frameJaggedSpacing.step = "1";
      frameJaggedSpacing.value = String(activeFrame.jagged_spacing_px ?? 28);
      frameJaggedSpacing.addEventListener("change", () => {
        selected.frame_jagged_spacing_px = Math.max(6, Number(frameJaggedSpacing.value) || 28);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedMinJitter = document.createElement("input");
      frameJaggedMinJitter.type = "number";
      frameJaggedMinJitter.min = "0";
      frameJaggedMinJitter.max = "80";
      frameJaggedMinJitter.step = "1";
      frameJaggedMinJitter.value = String(activeFrame.jagged_spacing_min_jitter_px ?? 4);
      frameJaggedMinJitter.addEventListener("change", () => {
        selected.frame_jagged_spacing_min_jitter_px = Math.max(0, Number(frameJaggedMinJitter.value) || 0);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedMaxJitter = document.createElement("input");
      frameJaggedMaxJitter.type = "number";
      frameJaggedMaxJitter.min = "0";
      frameJaggedMaxJitter.max = "80";
      frameJaggedMaxJitter.step = "1";
      frameJaggedMaxJitter.value = String(activeFrame.jagged_spacing_max_jitter_px ?? 6);
      frameJaggedMaxJitter.addEventListener("change", () => {
        selected.frame_jagged_spacing_max_jitter_px = Math.max(0, Number(frameJaggedMaxJitter.value) || 0);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedPattern = document.createElement("select");
      [
        ["alternate", "交互"],
        ["short_long_short", "短い-長い-短い"],
        ["random", "ランダム"],
      ].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        frameJaggedPattern.appendChild(option);
      });
      frameJaggedPattern.value = activeFrame.jagged_pattern || "alternate";
      frameJaggedPattern.addEventListener("change", () => {
        selected.frame_jagged_pattern = frameJaggedPattern.value || "alternate";
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameHalftoneEnabled = document.createElement("input");
      frameHalftoneEnabled.type = "checkbox";
      frameHalftoneEnabled.checked = activeFrame.halftone_enabled === true;
      frameHalftoneEnabled.addEventListener("change", () => {
        selected.frame_halftone_enabled = frameHalftoneEnabled.checked;
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameHalftoneScale = document.createElement("input");
      frameHalftoneScale.type = "number";
      frameHalftoneScale.min = "4";
      frameHalftoneScale.max = "64";
      frameHalftoneScale.step = "1";
      frameHalftoneScale.value = String(activeFrame.halftone_scale ?? 16);
      frameHalftoneScale.addEventListener("change", () => {
        selected.frame_halftone_scale = Math.max(4, Number(frameHalftoneScale.value) || 16);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameHalftoneDotSize = document.createElement("input");
      frameHalftoneDotSize.type = "number";
      frameHalftoneDotSize.min = "1";
      frameHalftoneDotSize.max = "32";
      frameHalftoneDotSize.step = "1";
      frameHalftoneDotSize.value = String(activeFrame.halftone_dot_size ?? 2);
      frameHalftoneDotSize.addEventListener("change", () => {
        selected.frame_halftone_dot_size = Math.max(1, Number(frameHalftoneDotSize.value) || 2);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameHalftoneOpacity = document.createElement("input");
      frameHalftoneOpacity.type = "number";
      frameHalftoneOpacity.min = "0";
      frameHalftoneOpacity.max = "1";
      frameHalftoneOpacity.step = "0.01";
      frameHalftoneOpacity.value = String(activeFrame.halftone_opacity ?? 0.24);
      frameHalftoneOpacity.addEventListener("change", () => {
        selected.frame_halftone_opacity = Math.max(0, Math.min(1, Number(frameHalftoneOpacity.value) || 0));
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameJaggedPreset = document.createElement("select");
      [
        { id: "", name: "手動設定" },
        { id: "small_even", name: "細かい均等", outer: 8, inner: 3, spacing: 18, min: 0, max: 0, pattern: "alternate" },
        { id: "manga_standard", name: "漫画標準", outer: 14, inner: 5, spacing: 28, min: 4, max: 6, pattern: "alternate" },
        { id: "large_impact", name: "大きめインパクト", outer: 24, inner: 8, spacing: 36, min: 4, max: 10, pattern: "short_long_short" },
        { id: "rough_random", name: "荒めランダム", outer: 20, inner: 4, spacing: 30, min: 8, max: 18, pattern: "random" },
        { id: "sharp_dense", name: "鋭い密集", outer: 18, inner: 1, spacing: 16, min: 2, max: 5, pattern: "alternate" },
      ].forEach((preset) => {
        const option = document.createElement("option");
        option.value = preset.id;
        option.textContent = preset.name;
        option.dataset.preset = JSON.stringify(preset);
        frameJaggedPreset.appendChild(option);
      });
      frameJaggedPreset.addEventListener("change", () => {
        const option = frameJaggedPreset.selectedOptions[0];
        const preset = option?.dataset?.preset ? JSON.parse(option.dataset.preset) : null;
        if (!preset || !preset.id) return;
        selected.frame_jagged_outer_px = preset.outer;
        selected.frame_jagged_inner_px = preset.inner;
        selected.frame_jagged_spacing_px = preset.spacing;
        selected.frame_jagged_spacing_min_jitter_px = preset.min;
        selected.frame_jagged_spacing_max_jitter_px = preset.max;
        selected.frame_jagged_pattern = preset.pattern;
        frameJaggedOuter.value = String(preset.outer);
        frameJaggedInner.value = String(preset.inner);
        frameJaggedSpacing.value = String(preset.spacing);
        frameJaggedMinJitter.value = String(preset.min);
        frameJaggedMaxJitter.value = String(preset.max);
        frameJaggedPattern.value = preset.pattern;
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const frameHalftonePreset = document.createElement("select");
      [
        { id: "", name: "手動設定" },
        { id: "fine_light", name: "細かい薄め", scale: 10, dot: 1, opacity: 0.16 },
        { id: "manga_standard", name: "漫画標準", scale: 16, dot: 2, opacity: 0.24 },
        { id: "coarse_print", name: "粗い印刷", scale: 24, dot: 4, opacity: 0.30 },
        { id: "bold_pop", name: "太めポップ", scale: 18, dot: 6, opacity: 0.38 },
        { id: "sparse_shadow", name: "まばら影", scale: 32, dot: 3, opacity: 0.22 },
      ].forEach((preset) => {
        const option = document.createElement("option");
        option.value = preset.id;
        option.textContent = preset.name;
        option.dataset.preset = JSON.stringify(preset);
        frameHalftonePreset.appendChild(option);
      });
      frameHalftonePreset.addEventListener("change", () => {
        const option = frameHalftonePreset.selectedOptions[0];
        const preset = option?.dataset?.preset ? JSON.parse(option.dataset.preset) : null;
        if (!preset || !preset.id) return;
        selected.frame_halftone_enabled = true;
        selected.frame_halftone_scale = preset.scale;
        selected.frame_halftone_dot_size = preset.dot;
        selected.frame_halftone_opacity = preset.opacity;
        frameHalftoneEnabled.checked = true;
        frameHalftoneScale.value = String(preset.scale);
        frameHalftoneDotSize.value = String(preset.dot);
        frameHalftoneOpacity.value = String(preset.opacity);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = selected.enabled !== false;
      enabled.addEventListener("change", () => {
        selected.enabled = enabled.checked;
      });
      const saveTextPresetBtn = document.createElement("button");
      saveTextPresetBtn.type = "button";
      saveTextPresetBtn.textContent = "名前をつけて保存";
      saveTextPresetBtn.addEventListener("click", () => {
        if (!state.decorationProject) return;
        const defaultName = `文字プリセット ${String((state.decorationProject.font_presets || []).length + 1).padStart(2, "0")}`;
        const name = window.prompt("保存する文字プリセット名", defaultName);
        if (!name) return;
        const next = fontPresetFromEvent(selected, name.trim() || defaultName);
        state.decorationProject.font_presets = [...decorationFontPresets(), next];
        selected.font_preset_id = next.id;
        renderDecorationPage();
      });
      const updateTextPresetBtn = document.createElement("button");
      updateTextPresetBtn.type = "button";
      updateTextPresetBtn.textContent = "今のプリセットを更新";
      updateTextPresetBtn.addEventListener("click", () => {
        if (!state.decorationProject || !selected.font_preset_id) return;
        const presets = decorationFontPresets();
        const current = presets.find((item) => item.id === selected.font_preset_id);
        if (!current) return;
        const updated = fontPresetFromEvent(selected, current.name || current.id, current.id);
        state.decorationProject.font_presets = presets.map((item) => (item.id === updated.id ? updated : item));
        renderDecorationPage();
      });
      const applyTextAllBtn = document.createElement("button");
      applyTextAllBtn.type = "button";
      applyTextAllBtn.textContent = isGlobalDecorationEvent(selected) ? "全体設定を反映" : "文字と枠を全体へ適用";
      applyTextAllBtn.addEventListener("click", () => {
        const count = applyCurrentTextSettingsToAll(selected);
        renderDecorationPage();
        setStatus(isGlobalDecorationEvent(selected) ? `全体設定を ${count} 件へ反映しました` : `文字と枠を ${count} 件へ適用しました`);
      });
      const resetTextBtn = document.createElement("button");
      resetTextBtn.type = "button";
      resetTextBtn.textContent = "文字を初期化";
      resetTextBtn.addEventListener("click", () => {
        resetDecorationEventTextToPresetDefaults(selected);
        renderDecorationPage();
      });
      const saveFramePresetBtn = document.createElement("button");
      saveFramePresetBtn.type = "button";
      saveFramePresetBtn.textContent = "名前をつけて保存";
      saveFramePresetBtn.addEventListener("click", () => {
        if (!state.decorationProject) return;
        const defaultName = `枠プリセット ${String((state.decorationProject.frame_presets || []).length + 1).padStart(2, "0")}`;
        const name = window.prompt("保存する枠プリセット名", defaultName);
        if (!name) return;
        const next = framePresetFromEvent(selected, name.trim() || defaultName);
        state.decorationProject.frame_presets = [...decorationFramePresets(), next];
        applyFramePresetToEvent(selected, next.id);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const saveSharedPresetsBtn = document.createElement("button");
      saveSharedPresetsBtn.type = "button";
      saveSharedPresetsBtn.textContent = "共通へ保存";
      saveSharedPresetsBtn.addEventListener("click", () => {
        runStep("共通プリセット保存", async () => {
          await saveSharedDecorationPresets();
        });
      });
      const updateFramePresetBtn = document.createElement("button");
      updateFramePresetBtn.type = "button";
      updateFramePresetBtn.textContent = "今の枠を更新";
      updateFramePresetBtn.addEventListener("click", () => {
        if (!state.decorationProject || !selected.frame_preset_id) return;
        const presets = decorationFramePresets();
        const current = presets.find((item) => item.id === selected.frame_preset_id);
        if (!current) return;
        const updated = framePresetFromEvent(selected, current.name || current.id, current.id);
        state.decorationProject.frame_presets = presets.map((item) => (item.id === updated.id ? updated : item));
        applyFramePresetToEvent(selected, updated.id);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected);
        renderDecorationPage();
      });
      const resetFrameBtn = document.createElement("button");
      resetFrameBtn.type = "button";
      resetFrameBtn.textContent = "枠を初期化";
      resetFrameBtn.addEventListener("click", () => {
        resetDecorationEventFrameToPresetDefaults(selected);
        if (state.frameSyncMode === "live") syncFramePresetToLinkedEvents(selected, true);
        renderDecorationPage();
      });
      const applyFrameGlobalBtn = document.createElement("button");
      applyFrameGlobalBtn.type = "button";
      applyFrameGlobalBtn.textContent = isGlobalDecorationEvent(selected) ? "全体設定を反映" : "この枠を全体へ適用";
      applyFrameGlobalBtn.addEventListener("click", () => {
        const count = applyCurrentTextSettingsToAll(selected);
        renderDecorationPage();
        setStatus(isGlobalDecorationEvent(selected) ? `全体設定を ${count} 件へ反映しました` : `枠を ${count} 件へ適用しました`);
      });

      textFields.appendChild(makeField("本文", text));
      textFields.appendChild(makeField("話者", speaker));
      textFields.appendChild(makeField("文字プリセット", fontPreset));
      textFields.appendChild(makeField("枠プリセット", textFrame));
      textFields.appendChild(makeField("フォント", fontFamily));
      textFields.appendChild(makeField("フォントサイズ", fontSize));
      textFields.appendChild(makeField("フォントの色", fontColor));
      textFields.appendChild(makeField("フォントの縁", outlineEnabled));
      textFields.appendChild(makeField("フォントの縁の色", outlineColor));
      textFields.appendChild(makeField("フォントの縁の幅", outlineWidth));
      textFields.appendChild(makeField("有効", enabled));
      textFields.appendChild(saveTextPresetBtn);
      textFields.appendChild(updateTextPresetBtn);
      textFields.appendChild(applyTextAllBtn);
      textFields.appendChild(resetTextBtn);

      frameFields.appendChild(makeField("枠プリセット", frame));
      frameFields.appendChild(makeField("配置", layout));
      frameFields.appendChild(makeField("横位置調整(px)", layoutOffsetX));
      frameFields.appendChild(makeField("縦位置調整(px)", layoutOffsetY));
      frameFields.appendChild(makeField("枠のフチの有り無し", frameBorderEnabled));
      frameFields.appendChild(makeField("枠のフチの幅", frameBorderWidth));
      frameFields.appendChild(makeField("枠のフチの色", frameBorderColor));
      frameFields.appendChild(makeField("枠の背景色", frameBgColor));
      frameFields.appendChild(makeField("背景の透過率", frameBgOpacity));
      frameFields.appendChild(makeField("枠までのクリアランス", frameClearance));
      frameFields.appendChild(makeField("自動折り返し率(0.4-0.98)", frameWrapRatio));
      frameFields.appendChild(makeField("ギザギザ設定プリセット", frameJaggedPreset));
      frameFields.appendChild(makeField("ギザギザ突起の外側距離(px)", frameJaggedOuter));
      frameFields.appendChild(makeField("ギザギザ凹みの内側距離(px)", frameJaggedInner));
      frameFields.appendChild(makeField("ギザギザ突起の基準間隔(px)", frameJaggedSpacing));
      frameFields.appendChild(makeField("ギザギザ間隔の最小公差(px)", frameJaggedMinJitter));
      frameFields.appendChild(makeField("ギザギザ間隔の最大公差(px)", frameJaggedMaxJitter));
      frameFields.appendChild(makeField("ギザギザの並び", frameJaggedPattern));
      frameFields.appendChild(makeField("網点/ハーフトーン", frameHalftoneEnabled));
      frameFields.appendChild(makeField("網点設定プリセット", frameHalftonePreset));
      frameFields.appendChild(makeField("網点の大きさ(px)", frameHalftoneDotSize));
      frameFields.appendChild(makeField("網点の密度(px)", frameHalftoneScale));
      frameFields.appendChild(makeField("網点の濃さ", frameHalftoneOpacity));
      const syncModeBar = document.createElement("div");
      syncModeBar.className = "decoration-toggle-row";
      const liveButton = document.createElement("button");
      liveButton.type = "button";
      liveButton.textContent = "リアルタイム反映";
      liveButton.className = state.frameSyncMode === "live" ? "active" : "";
      liveButton.addEventListener("click", () => {
        state.frameSyncMode = "live";
        renderDecorationPage();
      });
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.textContent = "保存時に反映";
      saveButton.className = state.frameSyncMode === "save" ? "active" : "";
      saveButton.addEventListener("click", () => {
        state.frameSyncMode = "save";
        renderDecorationPage();
      });
      syncModeBar.appendChild(liveButton);
      syncModeBar.appendChild(saveButton);
      frameFields.appendChild(syncModeBar);
      frameFields.appendChild(makeField("レイアウト", layout));
      frameFields.appendChild(makeField("seed", seedInput));
      frameFields.appendChild(saveFramePresetBtn);
      frameFields.appendChild(updateFramePresetBtn);
      frameFields.appendChild(resetFrameBtn);
      frameFields.appendChild(applyFrameGlobalBtn);
      frameFields.appendChild(saveSharedPresetsBtn);

      effectFields.appendChild(makeField("文字連動プリセット", effect));
      const applyEffectGlobalBtn = document.createElement("button");
      applyEffectGlobalBtn.type = "button";
      applyEffectGlobalBtn.textContent = isGlobalDecorationEvent(selected) ? "全体設定を反映" : "文字連動を全体へ適用";
      applyEffectGlobalBtn.addEventListener("click", () => {
        const count = applyCurrentTextSettingsToAll(selected);
        renderDecorationPage();
        setStatus(isGlobalDecorationEvent(selected) ? `全体設定を ${count} 件へ反映しました` : `文字連動を ${count} 件へ適用しました`);
      });
      effectFields.appendChild(applyEffectGlobalBtn);

      const zoomScale = document.createElement("input");
      zoomScale.id = "zoomBoxScaleInput";
      zoomScale.type = "number";
      zoomScale.min = "0.25";
      zoomScale.max = "3";
      zoomScale.step = "0.01";
      zoomScale.value = "1.25";
      zoomScale.addEventListener("change", setZoomBoxFromInputs);
      const zoomX = document.createElement("input");
      zoomX.id = "zoomBoxXInput";
      zoomX.type = "number";
      zoomX.min = "0";
      zoomX.max = "1";
      zoomX.step = "0.01";
      zoomX.value = "0.50";
      zoomX.addEventListener("change", setZoomBoxFromInputs);
      const zoomY = document.createElement("input");
      zoomY.id = "zoomBoxYInput";
      zoomY.type = "number";
      zoomY.min = "0";
      zoomY.max = "1";
      zoomY.step = "0.01";
      zoomY.value = "0.50";
      zoomY.addEventListener("change", setZoomBoxFromInputs);
      const currentZoomBox = clampZoomBox(state.zoomBox);
      zoomScale.value = (1 / currentZoomBox.widthRatio).toFixed(2);
      zoomX.value = currentZoomBox.centerX.toFixed(2);
      zoomY.value = currentZoomBox.centerY.toFixed(2);
      const zoomBoxPreset = document.createElement("select");
      const fillZoomBoxPresetOptions = () => {
        zoomBoxPreset.textContent = "";
        zoomBoxPresets().forEach((preset) => {
          const option = document.createElement("option");
          option.value = preset.id;
          option.textContent = preset.name;
          zoomBoxPreset.appendChild(option);
        });
      };
      fillZoomBoxPresetOptions();
      zoomBoxPreset.addEventListener("change", () => {
        const preset = zoomBoxPresets().find((item) => item.id === zoomBoxPreset.value);
        if (!preset) return;
        state.zoomBox = clampZoomBox({
          active: true,
          centerX: preset.centerX,
          centerY: preset.centerY,
          widthRatio: preset.widthRatio,
        });
        syncZoomInputsFromBox();
        updateZoomBoxOverlay();
      });
      const zoomPreset = document.createElement("select");
      const zoomRelatedPresets = [
        {
          id: "zoom_in_soft",
          name: "少し拡大",
          scale: 1.18,
          effects: [],
        },
        {
          id: "zoom_in_blur",
          name: "拡大 + ズームブラー",
          scale: 1.32,
          effects: [
            { id: "zoom_blur", intensity: 0.35, speed: 1.0, blur_samples: 5, blur_amount: 0.12, color: "#ffffff" },
          ],
        },
        {
          id: "zoom_in_focus",
          name: "拡大 + スポットライト",
          scale: 1.25,
          effects: [
            { id: "spotlight", intensity: 0.45, speed: 1.0, radius: 0.38, color: "#000000" },
          ],
        },
        {
          id: "zoom_in_action",
          name: "拡大 + 手ブレ",
          scale: 1.22,
          effects: [
            { id: "action_shake", intensity: 0.25, speed: 1.35, shake_strength: 0.9, color: "#ffffff" },
          ],
        },
        {
          id: "zoom_in_impact",
          name: "拡大 + 集中線",
          scale: 1.28,
          effects: [
            { id: "speed_lines", intensity: 0.55, speed: 1.0, color: "#000000", center_gap: 0.26, spokes: 72, line_width: 0.012 },
          ],
        },
        {
          id: "zoom_in_flash",
          name: "拡大 + 衝撃フラッシュ",
          scale: 1.25,
          effects: [
            { id: "impact_flash", intensity: 0.42, speed: 1.2, flash_frequency: 10, flash_power: 5, color: "#ffffff" },
          ],
        },
        {
          id: "zoom_out",
          name: "縮小 黒背景",
          scale: 0.82,
          effects: [],
        },
        {
          id: "zoom_out_spot",
          name: "縮小 + スポットライト",
          scale: 0.78,
          effects: [
            { id: "spotlight", intensity: 0.55, speed: 1.0, radius: 0.45, color: "#000000" },
          ],
        },
      ];
      zoomRelatedPresets.forEach((preset) => {
        const option = document.createElement("option");
        option.value = preset.id;
        option.textContent = preset.name;
        zoomPreset.appendChild(option);
      });
      zoomPreset.value = "zoom_in_soft";
      const selectedZoomPreset = () => zoomRelatedPresets.find((preset) => preset.id === zoomPreset.value) || zoomRelatedPresets[0];
      const applyZoomPresetToInputs = () => {
        const preset = selectedZoomPreset();
        zoomScale.value = String(preset.scale ?? 1.25);
      };
      zoomPreset.addEventListener("change", applyZoomPresetToInputs);
      const zoomTarget = document.createElement("select");
      [
        { id: "scene", name: "現在シーン" },
        { id: "global", name: "全体" },
      ].forEach((item) => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.name;
        zoomTarget.appendChild(option);
      });
      zoomTarget.value = "scene";
      const zoomTiming = document.createElement("select");
      [
        { id: "full", name: "対象全体" },
        { id: "custom", name: "時間指定" },
      ].forEach((item) => {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.name;
        zoomTiming.appendChild(option);
      });
      const zoomStart = document.createElement("input");
      zoomStart.placeholder = "開始 秒";
      zoomStart.value = "0.000";
      const zoomEnd = document.createElement("input");
      zoomEnd.placeholder = "終了 秒";
      zoomEnd.value = selected ? Math.max(0.1, Number(selected.end_sec || 0) - Number(selected.start_sec || 0)).toFixed(3) : "3.000";
      const addZoomBtn = document.createElement("button");
      addZoomBtn.type = "button";
      addZoomBtn.className = "primary";
      addZoomBtn.textContent = "拡大・縮小を追加";
      addZoomBtn.addEventListener("click", () => {
        if (!state.decorationProject) return;
        const targetSceneId = zoomTarget.value === "scene" ? ensureScreenEffectSceneIdForCurrentSelection() : "";
        if (zoomTarget.value === "scene" && !targetSceneId) {
          setStatus("現在シーンを判定できません。字幕イベントを選択してください。", true);
          return;
        }
        const scale = Math.max(0.25, Math.min(3, Number(zoomScale.value) || 1));
        const nextId = `screen_stack_zoom_${String(Date.now()).slice(-8)}_${Math.random().toString(16).slice(2, 6)}`;
        const startSec = Math.max(0, parseTime(zoomStart.value || "0"));
        const endSec = Math.max(startSec, parseTime(zoomEnd.value || String(startSec + 1)));
        const preset = selectedZoomPreset();
        const effect = normalizeScreenEffectItem({
          id: "video_zoom",
          zoom_scale: scale,
          position_x: Math.max(0, Math.min(1, Number(zoomX.value) || 0.5)),
          position_y: Math.max(0, Math.min(1, Number(zoomY.value) || 0.5)),
          intensity: 1,
          speed: 1,
          color: "#000000",
        });
        const relatedEffects = (preset.effects || []).map((item) => normalizeScreenEffectItem({
          ...item,
          position_x: item.position_x ?? effect.position_x,
          position_y: item.position_y ?? effect.position_y,
        }));
        const nextStack = {
          id: nextId,
          name: preset.name || (scale >= 1 ? "拡大" : "縮小"),
          description: "シーンの長さを変えずに映像を拡大・縮小し、関連する画面効果を重ねる",
          effects: [effect, ...relatedEffects],
          timing_mode: zoomTiming.value || "full",
          timing_basis: zoomTarget.value === "global" ? "absolute" : "relative",
          effect_start_sec: roundTime(startSec),
          effect_end_sec: roundTime(endSec),
        };
        state.decorationProject.screen_effect_stacks = [...(state.decorationProject.screen_effect_stacks || []), nextStack];
        if (zoomTarget.value === "scene") addScreenEffectStackToTarget(nextId, "scene", targetSceneId);
        else addScreenEffectStackToTarget(nextId, "global");
        state.screenEffectSelectedStackId = nextId;
        setStatus(`${nextStack.name}を${zoomTarget.value === "scene" ? "現在シーン" : "全体"}へ追加しました`);
        renderDecorationPage();
      });
      const openZoomBoxEditorBtn = document.createElement("button");
      openZoomBoxEditorBtn.type = "button";
      openZoomBoxEditorBtn.textContent = "プレビュー上で赤枠編集";
      openZoomBoxEditorBtn.addEventListener("click", () => {
        state.zoomBox = clampZoomBox({
          active: true,
          centerX: Number(zoomX.value) || 0.5,
          centerY: Number(zoomY.value) || 0.5,
          widthRatio: 1 / Math.max(0.25, Math.min(3, Number(zoomScale.value) || 1.25)),
        });
        setAppPage("previewCheck");
        setDecorationEditTab("zoom");
        updateZoomBoxOverlay();
      });
      const saveZoomBoxPresetBtn = document.createElement("button");
      saveZoomBoxPresetBtn.type = "button";
      saveZoomBoxPresetBtn.textContent = "赤枠をプリセット登録";
      saveZoomBoxPresetBtn.addEventListener("click", () => {
        const name = window.prompt("赤枠プリセット名", `拡大枠 ${new Date().toLocaleTimeString()}`);
        if (!name) return;
        const box = clampZoomBox(state.zoomBox);
        saveCustomZoomBoxPreset({
          id: `zoom_box_${Date.now()}`,
          name: name.trim() || "拡大枠",
          centerX: box.centerX,
          centerY: box.centerY,
          widthRatio: box.widthRatio,
        });
        fillZoomBoxPresetOptions();
        setStatus("赤枠プリセットを保存しました");
      });
      const zoomNote = document.createElement("p");
      zoomNote.className = "muted";
      zoomNote.textContent = "1.00より大きいと拡大、1.00より小さいと縮小します。縮小で余る部分は黒背景になります。";
      zoomFields.appendChild(makeField("演出項目", zoomPreset));
      zoomFields.appendChild(makeField("赤枠プリセット", zoomBoxPreset));
      zoomFields.appendChild(makeField("対象", zoomTarget));
      zoomFields.appendChild(makeField("適用時間", zoomTiming));
      zoomFields.appendChild(makeField("開始", zoomStart));
      zoomFields.appendChild(makeField("終了", zoomEnd));
      zoomFields.appendChild(makeField("拡大率", zoomScale));
      zoomFields.appendChild(makeField("中心X", zoomX));
      zoomFields.appendChild(makeField("中心Y", zoomY));
      zoomFields.appendChild(openZoomBoxEditorBtn);
      zoomFields.appendChild(saveZoomBoxPresetBtn);
      zoomFields.appendChild(addZoomBtn);
      zoomFields.appendChild(zoomNote);

      detail.appendChild(textFields);
      detail.appendChild(frameFields);
      detail.appendChild(effectFields);
      detail.appendChild(zoomFields);
    }
  }

  if (project) {
    const globalItem = globalDecorationEvent();
    const item = document.createElement("div");
    item.className = `decoration-item decoration-global-item${state.decorationSelectionId === DECORATION_GLOBAL_ID ? " selected" : ""}`;
    const idx = document.createElement("strong");
    idx.textContent = "全体";
    const meta = document.createElement("div");
    meta.className = "decoration-meta";
    const title = document.createElement("span");
    title.textContent = "全体シーンへ適用";
    const subline = document.createElement("small");
    subline.textContent = `${effectiveFrameForEvent(globalItem).name || globalItem.frame_preset_id || "frameなし"} / ${globalItem.text_effect_group_id || globalItem.effect_group_id || "effectなし"}`;
    const text = document.createElement("div");
    text.textContent = "ここで設定した文字・枠・文字連動は、個別上書きしていない字幕へ反映されます。";
    meta.appendChild(title);
    meta.appendChild(subline);
    meta.appendChild(text);
    const action = document.createElement("button");
    action.type = "button";
    action.textContent = "選択";
    action.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = DECORATION_GLOBAL_ID;
      setDecorationEditTab("text");
    });
    item.appendChild(idx);
    item.appendChild(meta);
    item.appendChild(action);
    item.addEventListener("click", () => {
      state.decorationSelectionId = DECORATION_GLOBAL_ID;
      renderDecorationPage();
    });
    list.appendChild(item);
  }

  events.forEach((eventItem, index) => {
    const item = document.createElement("div");
    item.className = `decoration-item${eventItem.id === state.decorationSelectionId ? " selected" : ""}`;
    const idx = document.createElement("strong");
    idx.textContent = `#${index + 1}`;
    const meta = document.createElement("div");
    meta.className = "decoration-meta";
    const title = document.createElement("span");
    title.textContent = `${fmtTime(eventItem.start_sec)} - ${fmtTime(eventItem.end_sec)}`;
    const subline = document.createElement("small");
    subline.textContent = `${eventItem.scene_id || "sceneなし"} / ${eventItem.style_override_enabled === true ? "個別" : "全体設定"} / ${effectiveFrameForEvent(eventItem).name || eventItem.frame_preset_id || "frameなし"} / ${effectiveDecorationForEvent(eventItem).text_effect_group_id || "effectなし"}`;
    const text = document.createElement("div");
    text.textContent = eventItem.text || "";
    meta.appendChild(title);
    meta.appendChild(subline);
    meta.appendChild(text);
    const action = document.createElement("button");
    action.type = "button";
    action.textContent = "選択";
    action.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      renderDecorationPage();
    });
    const textAction = document.createElement("button");
    textAction.type = "button";
    textAction.textContent = "文字";
    textAction.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      setDecorationEditTab("text");
    });
    const frameAction = document.createElement("button");
    frameAction.type = "button";
    frameAction.textContent = "枠";
    frameAction.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      setDecorationEditTab("frame");
    });
    const effectAction = document.createElement("button");
    effectAction.type = "button";
    effectAction.textContent = "文字連動";
    effectAction.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      setDecorationEditTab("text_effect");
    });
    const zoomAction = document.createElement("button");
    zoomAction.type = "button";
    zoomAction.textContent = "拡大";
    zoomAction.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      setDecorationEditTab("zoom");
    });
    const screenAction = document.createElement("button");
    screenAction.type = "button";
    screenAction.textContent = "画面";
    screenAction.addEventListener("click", (event) => {
      event.stopPropagation();
      state.decorationSelectionId = eventItem.id;
      setDecorationEditTab("screen_effect");
    });
    item.appendChild(idx);
    item.appendChild(meta);
    item.appendChild(action);
    item.appendChild(textAction);
    item.appendChild(frameAction);
    item.appendChild(effectAction);
    item.appendChild(zoomAction);
    item.appendChild(screenAction);
    item.addEventListener("click", () => {
      state.decorationSelectionId = eventItem.id;
      renderDecorationPage();
    });
    list.appendChild(item);
  });

  groups.forEach((group) => {
    const item = document.createElement("div");
    item.className = `effect-group-item${effectiveDecorationForEvent(currentDecorationEvent())?.text_effect_group_id === group.id ? " selected" : ""}`;
    const header = document.createElement("div");
    header.className = "effect-group-header";
    const title = document.createElement("strong");
    const nameInput = document.createElement("input");
    nameInput.value = group.name || group.id;
    nameInput.placeholder = "グループ名";
    nameInput.style.minWidth = "180px";
    const count = document.createElement("small");
    count.textContent = group.id;
    header.appendChild(title);
    header.appendChild(count);
    title.textContent = group.name || group.id;
    const description = document.createElement("textarea");
    description.value = group.description || "";
    description.placeholder = "説明";
    description.style.minHeight = "48px";
    const effectDetails = document.createElement("details");
    effectDetails.className = "effect-library-details";
    const effectSummary = document.createElement("summary");
    const effectGrid = document.createElement("div");
    effectGrid.className = "screen-effect-grid";
    const effectLibrary = decorationEffectLibrary();
    const controls = document.createElement("div");
    controls.className = "decoration-toolbar";
    const selectedEffects = new Set((group.effects || []).map((item) => String(item).trim()).filter(Boolean));
    effectSummary.textContent = `効果一覧を開く（選択中 ${selectedEffects.size} 件）`;
    effectDetails.appendChild(effectSummary);
    effectLibrary.forEach((effect) => {
      const row = document.createElement("label");
      row.className = "screen-effect-checkbox";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedEffects.has(effect.id);
      checkbox.addEventListener("change", () => {
        const next = new Set((group.effects || []).map((item) => String(item).trim()).filter(Boolean));
        if (checkbox.checked) next.add(effect.id);
        else next.delete(effect.id);
        group.effects = Array.from(next);
        renderDecorationPage();
      });
      const text = document.createElement("span");
      text.textContent = effect.name || effect.id;
      row.appendChild(checkbox);
      row.appendChild(text);
      effectGrid.appendChild(row);
    });
    effectDetails.appendChild(effectGrid);
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "保存";
    saveBtn.addEventListener("click", () => {
      const target = state.decorationProject?.effect_groups || [];
      for (let i = 0; i < target.length; i += 1) {
        if (target[i].id === group.id) {
          target[i] = {
            ...target[i],
            name: nameInput.value.trim() || target[i].name || target[i].id,
            description: description.value.trim(),
            effects: [...(group.effects || [])],
          };
        }
      }
      if (state.decorationProject) state.decorationProject.effect_groups = target;
      renderDecorationPage();
    });
    const duplicateBtn = document.createElement("button");
    duplicateBtn.type = "button";
    duplicateBtn.textContent = "複製";
    duplicateBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      const nextId = `effect_group_${String(Date.now()).slice(-8)}`;
      state.decorationProject.effect_groups = [
        ...(state.decorationProject.effect_groups || []),
        {
          id: nextId,
          name: `${nameInput.value.trim() || group.name || group.id} copy`,
          description: description.value.trim(),
          effects: [...(group.effects || [])],
        },
      ];
      renderDecorationPage();
    });
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.textContent = "選択へ適用";
    applyBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      applyDecorationGroupToSelection(group);
      renderDecorationPage();
    });
    const applySceneBtn = document.createElement("button");
    applySceneBtn.type = "button";
    applySceneBtn.textContent = "同シーンへ適用";
    applySceneBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      const count = applyDecorationGroupToCurrentScene(group);
      if (!count) return;
      renderDecorationPage();
      setStatus(`同シーンへ ${count} 件適用しました`);
    });
    const applySpeakerBtn = document.createElement("button");
    applySpeakerBtn.type = "button";
    applySpeakerBtn.textContent = "同話者へ適用";
    applySpeakerBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      const count = applyDecorationGroupToCurrentSpeaker(group);
      if (!count) return;
      renderDecorationPage();
      setStatus(`同話者へ ${count} 件適用しました`);
    });
    const applyEmotionBtn = document.createElement("button");
    applyEmotionBtn.type = "button";
    applyEmotionBtn.textContent = "同感情へ適用";
    applyEmotionBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      const count = applyDecorationGroupToCurrentEmotion(group);
      if (!count) return;
      renderDecorationPage();
      setStatus(`同感情へ ${count} 件適用しました`);
    });
    const applyAllBtn = document.createElement("button");
    applyAllBtn.type = "button";
    applyAllBtn.textContent = "全体へ適用";
    applyAllBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      const count = applyDecorationGroupToAll(group);
      if (!count) return;
      renderDecorationPage();
      setStatus(`全体へ ${count} 件適用しました`);
    });
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "削除";
    removeBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      state.decorationProject.effect_groups = (state.decorationProject.effect_groups || []).filter((item) => item.id !== group.id);
      for (const eventItem of state.decorationProject.events || []) {
        if (eventItem.effect_group_id === group.id) eventItem.effect_group_id = "";
        if (eventItem.text_effect_group_id === group.id) eventItem.text_effect_group_id = "";
      }
      renderDecorationPage();
    });
    controls.appendChild(saveBtn);
    controls.appendChild(duplicateBtn);
    controls.appendChild(applyBtn);
    controls.appendChild(applySceneBtn);
    controls.appendChild(applySpeakerBtn);
    controls.appendChild(applyEmotionBtn);
    controls.appendChild(applyAllBtn);
    controls.appendChild(removeBtn);
    item.appendChild(header);
    item.appendChild(nameInput);
    item.appendChild(description);
    item.appendChild(controls);
    item.appendChild(effectDetails);
    groupList.appendChild(item);
  });
  renderScreenEffectStackSection();
  updateDecorationPreviewFilters();
}

function renderScreenEffectStackSection() {
  const stackList = $("screenEffectStackList");
  const globalList = $("screenEffectGlobalList");
  const sceneList = $("screenEffectSceneList");
  const stackCount = $("screenEffectStackCount");
  if (!stackList || !globalList || !sceneList || !stackCount) return;
  const stacks = screenEffectStacks();
  const targets = screenEffectTargets();
  const currentSceneId = screenEffectSceneIdForCurrentSelection();
  const currentScene = sceneCatalog().find((scene) => scene.id === currentSceneId);
  const currentSceneDuration = currentScene ? Math.max(0, Number(currentScene.end_sec || 0) - Number(currentScene.start_sec || 0)) : 0;
  stackCount.textContent = `${stacks.length}件`;

  const stackPrimaryEffect = (stack) => normalizeScreenEffectItem((stack?.effects || [])[0] || { id: "" });
  const stackScopeLabel = (stackId) => {
    if ((targets.global_stack_ids || []).includes(stackId)) return "全体";
    const sceneIds = Object.entries(targets.scene_stack_ids || {}).filter(([, ids]) => (ids || []).includes(stackId)).map(([sceneId]) => sceneId);
    if (!sceneIds.length) return "未適用";
    return sceneIds.map((sceneId) => sceneCatalog().find((scene) => scene.id === sceneId)?.label || sceneId).join(", ");
  };
  const stackTimingLabel = (stack, scope) => {
    if ((stack.timing_mode || "full") !== "custom") return scope === "全体" ? "全体時間" : "シーン全体";
    const start = Number(stack.effect_start_sec || 0) || 0;
    const end = Number(stack.effect_end_sec || 0) || 0;
    return `${fmtTime(start)} - ${fmtTime(end)}${stack.timing_basis === "absolute" ? "" : "（相対）"}`;
  };

  const renderTargetChips = (container, ids, scope) => {
    container.textContent = "";
    if (!ids.length) {
      const empty = document.createElement("small");
      empty.textContent = "未設定";
      container.appendChild(empty);
      return;
    }
    ids.forEach((stackId) => {
      const stack = screenEffectStackById(stackId);
      const effect = stackPrimaryEffect(stack);
      const chip = document.createElement("span");
      chip.className = "decoration-chip";
      chip.textContent = `${screenEffectName(effect.id)} / ${stackTimingLabel(stack || {}, scope === "global" ? "全体" : "シーン")}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.style.marginLeft = "6px";
      remove.addEventListener("click", () => {
        if (!state.decorationProject) return;
        removeScreenEffectStackFromTarget(stackId, scope, currentSceneId);
        renderDecorationPage();
      });
      chip.appendChild(remove);
      container.appendChild(chip);
    });
  };

  renderTargetChips(globalList, targets.global_stack_ids || [], "global");
  renderTargetChips(sceneList, currentSceneId ? (targets.scene_stack_ids?.[currentSceneId] || []) : [], "scene");

  stackList.textContent = "";

  const addPanel = document.createElement("div");
  addPanel.className = "effect-group-item";
  const addHeader = document.createElement("div");
  addHeader.className = "effect-group-header";
  const addTitle = document.createElement("strong");
  addTitle.textContent = "画面エフェクトを追加";
  const addNote = document.createElement("small");
  addNote.textContent = "単体エフェクトを対象と時間つきで追加";
  addHeader.appendChild(addTitle);
  addHeader.appendChild(addNote);
  addPanel.appendChild(addHeader);

  const addToolbar = document.createElement("div");
  addToolbar.className = "decoration-toolbar";
  const categorySelect = document.createElement("select");
  for (const category of screenEffectCategories()) {
    const option = document.createElement("option");
    option.value = category.id;
    option.textContent = category.name;
    categorySelect.appendChild(option);
  }
  categorySelect.value = state.screenEffectCategoryFilter || "all";

  const effectSelect = document.createElement("select");
  const fillEffectOptions = () => {
    const selectedCategory = categorySelect.value || "all";
    effectSelect.textContent = "";
    screenEffectLibrary()
      .filter((effect) => selectedCategory === "all" || screenEffectCategory(effect.id) === selectedCategory)
      .forEach((effect) => {
        const option = document.createElement("option");
        option.value = effect.id;
        option.textContent = `${effect.name || effect.id} / ${screenEffectCategoryName(screenEffectCategory(effect.id))}`;
        effectSelect.appendChild(option);
      });
  };
  fillEffectOptions();

  const targetSelect = document.createElement("select");
  [
    { id: "scene", name: "現在シーンに追加" },
    { id: "global", name: "全体に追加" },
  ].forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    targetSelect.appendChild(option);
  });
  targetSelect.value = "scene";

  const timingSelect = document.createElement("select");
  [
    { id: "full", name: "対象全体" },
    { id: "custom", name: "時間指定" },
  ].forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    timingSelect.appendChild(option);
  });
  const startInput = document.createElement("input");
  startInput.placeholder = "開始 秒";
  startInput.value = "0.000";
  const endInput = document.createElement("input");
  endInput.placeholder = "終了 秒";
  endInput.value = currentSceneDuration ? currentSceneDuration.toFixed(3) : "3.000";

  addToolbar.appendChild(categorySelect);
  addToolbar.appendChild(effectSelect);
  addToolbar.appendChild(targetSelect);
  addToolbar.appendChild(timingSelect);
  addToolbar.appendChild(startInput);
  addToolbar.appendChild(endInput);
  addPanel.appendChild(addToolbar);

  const addSettings = document.createElement("div");
  addSettings.className = "screen-effect-settings";
  addPanel.appendChild(addSettings);

  const makeParamControl = (effect, spec, onChange = null) => {
    const row = document.createElement("label");
    row.className = "screen-effect-range";
    const title = document.createElement("span");
    title.textContent = spec.label;
    const current = document.createElement("output");
    const input = document.createElement("input");
    const rawValue = effect?.[spec.key] ?? spec.default ?? screenEffectItemDefaults(effect.id)?.[spec.key] ?? 0;
    if (spec.kind === "color") {
      input.type = "color";
      input.value = String(rawValue || "#ffffff");
      current.textContent = input.value.toUpperCase();
      input.addEventListener("input", () => {
        current.textContent = input.value.toUpperCase();
        if (onChange) onChange(input.value);
      });
    } else {
      input.type = "range";
      input.min = String(spec.min);
      input.max = String(spec.max);
      input.step = String(spec.step);
      input.value = String(rawValue);
      current.textContent = spec.format ? spec.format(rawValue) : String(rawValue);
      input.addEventListener("input", () => {
        const nextValue = spec.integer ? Math.round(Number(input.value)) : Number(input.value);
        current.textContent = spec.format ? spec.format(nextValue) : String(nextValue);
        if (onChange) onChange(nextValue);
      });
    }
    input.dataset.effectParam = spec.key;
    row.appendChild(title);
    row.appendChild(current);
    row.appendChild(input);
    return row;
  };

  const paramSpecsForEffect = (effectId) => {
    const commonSpecs = [
      { key: "intensity", label: "強さ", min: 0, max: 1, step: 0.01, default: 1, format: (v) => Number(v).toFixed(2) },
      { key: "speed", label: "速度", min: 0.1, max: 3, step: 0.01, default: 1, format: (v) => Number(v).toFixed(2) },
      { key: "color", label: "色", kind: "color", default: "#ffffff" },
    ];
    const specs = screenEffectParameterSpecs(effectId);
    return [
      ...commonSpecs,
      ...specs.filter((spec) => !commonSpecs.some((common) => common.key === spec.key)),
    ];
  };

  const renderAddSettings = () => {
    addSettings.textContent = "";
    const effect = normalizeScreenEffectItem({ id: effectSelect.value, ...screenEffectItemDefaults(effectSelect.value) });
    paramSpecsForEffect(effect.id).forEach((spec) => addSettings.appendChild(makeParamControl(effect, spec)));
  };
  renderAddSettings();

  const collectEffectFromPanel = (effectId, panel) => {
    const effect = normalizeScreenEffectItem({ id: effectId, ...screenEffectItemDefaults(effectId) });
    panel.querySelectorAll("[data-effect-param]").forEach((input) => {
      const key = input.dataset.effectParam;
      effect[key] = input.type === "color" ? input.value : Number(input.value);
    });
    return normalizeScreenEffectItem(effect);
  };

  categorySelect.addEventListener("change", () => {
    state.screenEffectCategoryFilter = categorySelect.value || "all";
    fillEffectOptions();
    renderAddSettings();
  });
  effectSelect.addEventListener("change", renderAddSettings);

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "primary";
  const syncAddButtonLabel = () => {
    addBtn.textContent = targetSelect.value === "scene" ? "現在シーンに追加" : "全体に追加";
  };
  targetSelect.addEventListener("change", () => {
    endInput.value = targetSelect.value === "scene" && currentSceneDuration ? currentSceneDuration.toFixed(3) : "3.000";
    syncAddButtonLabel();
  });

  const addScreenEffectFromConfig = (effectConfig, name = "") => {
    if (!state.decorationProject) return;
    const effectId = effectConfig?.id || effectSelect.value;
    if (!effectId) return;
    const targetSceneId = targetSelect.value === "scene" ? ensureScreenEffectSceneIdForCurrentSelection() : "";
    if (targetSelect.value === "scene" && !targetSceneId) {
      setStatus("現在シーンを判定できません。字幕イベントを選択するか、プレビュー位置をシーン内へ移動してください。", true);
      return;
    }
    const nextId = `screen_stack_${String(Date.now()).slice(-8)}_${Math.random().toString(16).slice(2, 6)}`;
    const startSec = Math.max(0, parseTime(startInput.value || "0"));
    const endSec = Math.max(startSec, parseTime(endInput.value || String(startSec + 1)));
    const effect = normalizeScreenEffectItem({ id: effectId, ...screenEffectItemDefaults(effectId), ...(effectConfig || {}) });
    const nextStack = {
      id: nextId,
      name: name || screenEffectName(effect.id),
      description: "単体画面エフェクト",
      effects: [effect],
      timing_mode: timingSelect.value || "full",
      timing_basis: targetSelect.value === "global" ? "absolute" : "relative",
      effect_start_sec: roundTime(startSec),
      effect_end_sec: roundTime(endSec),
    };
    state.decorationProject.screen_effect_stacks = [...(state.decorationProject.screen_effect_stacks || []), nextStack];
    if (targetSelect.value === "scene") addScreenEffectStackToTarget(nextId, "scene", targetSceneId);
    else addScreenEffectStackToTarget(nextId, "global");
    state.screenEffectSelectedStackId = nextId;
    renderDecorationPage();
    setStatus(`${name || screenEffectName(effect.id)}を${targetSelect.value === "scene" ? "現在シーン" : "全体"}へ追加しました`);
  };
  syncAddButtonLabel();
  addBtn.addEventListener("click", () => {
    const effectId = effectSelect.value;
    if (!effectId) return;
    addScreenEffectFromConfig(collectEffectFromPanel(effectId, addSettings));
  });

  addToolbar.appendChild(addBtn);

  const presetBar = document.createElement("div");
  presetBar.className = "decoration-toolbar screen-effect-preset-bar";
  const presetLabel = document.createElement("span");
  presetLabel.className = "screen-effect-preset-label";
  presetLabel.textContent = "プリセット";
  presetBar.appendChild(presetLabel);
  const presetGroups = [
    {
      id: "zoom",
      name: "拡大縮小",
      presets: [
        { name: "少し拡大", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 1.18, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "強め拡大", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 1.45, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "少し縮小", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 0.82, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "ズームブラー", effect: { id: "zoom_blur", intensity: 0.55, speed: 1.0, blur_samples: 6, blur_amount: 0.18, color: "#ffffff" } },
        { name: "スポット拡大", effect: { id: "spotlight", intensity: 0.55, speed: 1.0, position_x: 0.5, position_y: 0.45, radius: 0.38, color: "#000000" } },
        { name: "手ブレ拡大", effect: { id: "action_shake", intensity: 0.28, speed: 1.35, shake_strength: 0.9, color: "#ffffff" } },
      ],
    },
    {
      id: "speed",
      name: "集中線",
      presets: [
        { name: "集中線", effect: { id: "speed_lines", intensity: 0.8, speed: 1.0, color: "#000000", center_gap: 0.32, spokes: 72, line_width: 0.012 } },
        { name: "荒め集中線", effect: { id: "speed_lines_sparse", intensity: 0.85, speed: 1.0, color: "#000000", center_gap: 0.22, spokes: 42, line_width: 0.018 } },
        { name: "白抜き集中線", effect: { id: "speed_lines_white", intensity: 0.78, speed: 1.0, color: "#ffffff", center_gap: 0.18, spokes: 110, line_width: 0.012 } },
        { name: "斜め線", effect: { id: "speed_lines_slash", intensity: 0.82, speed: 1.0, color: "#000000", center_gap: 0.0, spokes: 72, line_width: 0.009 } },
        { name: "外周線", effect: { id: "speed_lines_frame", intensity: 0.9, speed: 1.0, color: "#000000", center_gap: 0.42, spokes: 120, line_width: 0.014 } },
        { name: "爆発線", effect: { id: "speed_lines_burst", intensity: 0.9, speed: 1.0, color: "#000000", center_gap: 0.08, spokes: 84, line_width: 0.02 } },
        { name: "外向き放射線", effect: { id: "speed_lines_outward", intensity: 0.9, speed: 1.0, color: "#000000", center_gap: 0.08, spokes: 96, line_width: 0.014 } },
      ],
    },
    {
      id: "heart",
      name: "ハート/流れ物",
      presets: [
        { name: "ハート紙吹雪", effect: { id: "heart_confetti", intensity: 0.85, speed: 1.25, symbol_count: 34, radius: 0.045, position_x: 0.5, position_y: 0.5, color: "#ff5ca8" } },
        { name: "ハート雨", effect: { id: "heart_rain", intensity: 0.78, speed: 0.85, symbol_count: 28, radius: 0.055, color: "#ff5ca8" } },
        { name: "ハート浮上", effect: { id: "heart_float_up", intensity: 0.72, speed: 0.7, symbol_count: 22, radius: 0.06, color: "#ff83bd" } },
        { name: "ハートワイプ", effect: { id: "heart_wipe", intensity: 0.9, speed: 1.0, position_x: 0.5, position_y: 0.5, radius: 0.18, expansion_speed: 1.0, color: "#ff5ca8" } },
        { name: "ハートきらめき", effect: { id: "heart_sparkle", intensity: 0.72, speed: 1.0, symbol_count: 26, radius: 0.04, color: "#ff7ec8" } },
        { name: "回転ハート", effect: { id: "heart_orbit_burst", intensity: 0.88, speed: 1.0, symbol_count: 14, radius: 0.055, position_x: 0.5, position_y: 0.5, color: "#ff5ca8" } },
        { name: "流れ星", effect: { id: "drifting_stars", intensity: 0.85, speed: 1.0, direction_angle: -25, symbol_count: 10, color: "#fff176" } },
      ],
    },
    {
      id: "mood",
      name: "雰囲気",
      presets: [
        { name: "映画調", effect: { id: "cinema", intensity: 0.55, speed: 1.0, color: "#ffffff" } },
        { name: "セピア", effect: { id: "sepia", intensity: 0.7, speed: 1.0, color: "#ffffff" } },
        { name: "モノクロ", effect: { id: "monochrome", intensity: 1.0, speed: 1.0, color: "#ffffff" } },
        { name: "ホラー", effect: { id: "horror", intensity: 0.65, speed: 1.0, color: "#ffffff" } },
        { name: "ドリーム", effect: { id: "dream", intensity: 0.65, speed: 1.0, color: "#ffffff" } },
        { name: "夕焼け", effect: { id: "sunset", intensity: 0.55, speed: 1.0, color: "#ffffff" } },
      ],
    },
    {
      id: "retro",
      name: "レトロ/印刷",
      presets: [
        { name: "単色網点", effect: { id: "halftone", intensity: 0.9, speed: 1.0, color: "#101010", background_color: "#f7f1e3", dot_density: 20, dot_scale: 1.1, contrast: 1.05, rotation: 0.35 } },
        { name: "マンガ網点", effect: { id: "halftone", intensity: 0.95, speed: 1.0, color: "#111111", background_color: "#ffffff", dot_density: 28, dot_scale: 0.95, contrast: 1.18, rotation: 0.785398 } },
        { name: "VHS", effect: { id: "vhs", intensity: 0.6, speed: 1.0, color_shift: 0.014, color: "#ffffff" } },
        { name: "CRT", effect: { id: "crt", intensity: 0.65, speed: 1.0, line_density: 1, line_opacity: 0.22, color: "#ffffff" } },
        { name: "フィルム粒子", effect: { id: "film_grain", intensity: 0.35, speed: 1.0, grain_strength: 0.18, color: "#ffffff" } },
        { name: "ドット化", effect: { id: "pixelate", intensity: 0.8, speed: 1.0, pixel_size: 12, color: "#ffffff" } },
      ],
    },
    {
      id: "action",
      name: "アクション/注目",
      presets: [
        { name: "少し拡大", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 1.18, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "強め拡大", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 1.45, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "少し縮小", effect: { id: "video_zoom", intensity: 1.0, speed: 1.0, zoom_scale: 0.82, position_x: 0.5, position_y: 0.5, color: "#000000" } },
        { name: "スポットライト", effect: { id: "spotlight", intensity: 0.72, speed: 1.0, position_x: 0.5, position_y: 0.45, radius: 0.34, color: "#000000" } },
        { name: "丸絞り暗転", effect: { id: "iris_out", intensity: 1.0, speed: 1.0, position_x: 0.5, position_y: 0.5, radius: 0.65, color: "#000000" } },
        { name: "ズームブラー", effect: { id: "zoom_blur", intensity: 0.55, speed: 1.0, blur_samples: 6, blur_amount: 0.18, color: "#ffffff" } },
        { name: "衝撃フラッシュ", effect: { id: "impact_flash", intensity: 0.55, speed: 1.2, flash_frequency: 10, flash_power: 5, color: "#ffffff" } },
        { name: "アクション揺れ", effect: { id: "action_shake", intensity: 0.35, speed: 1.4, shake_strength: 1, color: "#ffffff" } },
        { name: "魚眼", effect: { id: "fisheye", intensity: 0.45, speed: 1.0, fisheye_strength: 0.45, color: "#ffffff" } },
      ],
    },
    {
      id: "adjust",
      name: "補正",
      presets: [
        { name: "文字視認性", effect: { id: "text_readability", intensity: 0.65, speed: 1.0, contrast: 1.15, color: "#ffffff" } },
        { name: "シャープ", effect: { id: "sharpen", intensity: 0.55, speed: 1.0, edge_threshold: 0.12, color: "#ffffff" } },
        { name: "暗いゲーム補正", effect: { id: "dark_game", intensity: 0.55, speed: 1.0, brightness_shift: -0.12, saturation_shift: 0.08, color: "#ffffff" } },
        { name: "白飛び抑制", effect: { id: "highlight_suppress", intensity: 0.55, speed: 1.0, brightness_shift: -0.05, color_temperature: -0.05, color: "#ffffff" } },
        { name: "中央強調", effect: { id: "highlight_subject", intensity: 0.6, speed: 1.0, brightness_shift: 0.08, saturation_shift: 0.12, color: "#ffffff" } },
        { name: "ホワイトバランス", effect: { id: "white_balance", intensity: 0.45, speed: 1.0, color_temperature: 0.06, color: "#ffffff" } },
      ],
    },
  ];
  const presetSelect = document.createElement("select");
  presetGroups.forEach((group) => {
    const option = document.createElement("option");
    option.value = group.id;
    option.textContent = group.name;
    presetSelect.appendChild(option);
  });
  const presetButtons = document.createElement("div");
  presetButtons.className = "screen-effect-preset-buttons";
  const renderPresetButtons = () => {
    presetButtons.textContent = "";
    const group = presetGroups.find((item) => item.id === presetSelect.value) || presetGroups[0];
    group.presets.forEach((preset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = preset.name;
      button.addEventListener("click", () => addScreenEffectFromConfig(preset.effect, preset.name));
      presetButtons.appendChild(button);
    });
  };
  presetSelect.addEventListener("change", renderPresetButtons);
  presetBar.appendChild(presetSelect);
  presetBar.appendChild(presetButtons);
  renderPresetButtons();
  addPanel.appendChild(presetBar);
  stackList.appendChild(addPanel);

  const listPanel = document.createElement("div");
  listPanel.className = "effect-group-item";
  const listHeader = document.createElement("div");
  listHeader.className = "effect-group-header";
  const listTitle = document.createElement("strong");
  listTitle.textContent = "追加済み画面エフェクト";
  const listNote = document.createElement("small");
  listNote.textContent = "単体ごとに編集・削除";
  listHeader.appendChild(listTitle);
  listHeader.appendChild(listNote);
  listPanel.appendChild(listHeader);

  if (!stacks.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "画面エフェクトは未追加です。";
    listPanel.appendChild(empty);
  } else {
    if (!stacks.some((stack) => stack.id === state.screenEffectSelectedStackId)) {
      state.screenEffectSelectedStackId = stacks[0]?.id || "";
    }
    const editToolbar = document.createElement("div");
    editToolbar.className = "decoration-toolbar";
    const editLabel = document.createElement("span");
    editLabel.textContent = "編集対象";
    const editSelect = document.createElement("select");
    stacks.forEach((stack) => {
      const effect = stackPrimaryEffect(stack);
      const option = document.createElement("option");
      option.value = stack.id;
      option.textContent = `${screenEffectName(effect.id)} / ${stackScopeLabel(stack.id)} / ${stackTimingLabel(stack, stackScopeLabel(stack.id))}`;
      editSelect.appendChild(option);
    });
    editSelect.value = state.screenEffectSelectedStackId || stacks[0]?.id || "";
    editSelect.addEventListener("change", () => {
      state.screenEffectSelectedStackId = editSelect.value || "";
      renderDecorationPage();
    });
    editToolbar.appendChild(editLabel);
    editToolbar.appendChild(editSelect);
    listPanel.appendChild(editToolbar);

    const stack = stacks.find((item) => item.id === editSelect.value) || stacks[0];
    const effect = stackPrimaryEffect(stack);
    const item = document.createElement("div");
    item.className = "screen-effect-setting-item";
    const heading = document.createElement("div");
    heading.className = "screen-effect-setting-heading";
    const title = document.createElement("strong");
    title.textContent = `${screenEffectName(effect.id)} / ${stackScopeLabel(stack.id)}`;
    const meta = document.createElement("small");
    meta.textContent = stackTimingLabel(stack, stackScopeLabel(stack.id));
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "削除";
    removeBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      state.decorationProject.screen_effect_stacks = (state.decorationProject.screen_effect_stacks || []).filter((itemStack) => itemStack.id !== stack.id);
      removeScreenEffectStackEverywhere(stack.id);
      renderDecorationPage();
    });
    heading.appendChild(title);
    heading.appendChild(meta);
    heading.appendChild(removeBtn);
    item.appendChild(heading);

    const timingRow = document.createElement("div");
    timingRow.className = "decoration-toolbar";
    const timingMode = document.createElement("select");
    [{ id: "full", name: "対象全体" }, { id: "custom", name: "時間指定" }].forEach((optionItem) => {
      const option = document.createElement("option");
      option.value = optionItem.id;
      option.textContent = optionItem.name;
      timingMode.appendChild(option);
    });
    timingMode.value = stack.timing_mode || "full";
    const editStart = document.createElement("input");
    editStart.value = String(stack.effect_start_sec ?? 0);
    editStart.placeholder = "開始 秒";
    const editEnd = document.createElement("input");
    editEnd.value = String(stack.effect_end_sec ?? 0);
    editEnd.placeholder = "終了 秒";
    const updateTiming = () => {
      updateScreenEffectStack(stack.id, (currentStack) => ({
        ...currentStack,
        timing_mode: timingMode.value || "full",
        effect_start_sec: roundTime(Math.max(0, parseTime(editStart.value || "0"))),
        effect_end_sec: roundTime(Math.max(0, parseTime(editEnd.value || "0"))),
      }));
      updateDecorationPreviewFilters();
    };
    timingMode.addEventListener("change", updateTiming);
    editStart.addEventListener("change", updateTiming);
    editEnd.addEventListener("change", updateTiming);
    timingRow.appendChild(timingMode);
    timingRow.appendChild(editStart);
    timingRow.appendChild(editEnd);
    item.appendChild(timingRow);

    paramSpecsForEffect(effect.id).forEach((spec) => {
      item.appendChild(makeParamControl(effect, spec, (nextValue) => {
        updateScreenEffectStackEffectAt(stack.id, 0, (currentEffect) => ({ ...currentEffect, [spec.key]: nextValue }));
        updateDecorationPreviewFilters();
      }));
    });
    listPanel.appendChild(item);
  }

  stackList.appendChild(listPanel);
  updateDecorationPreviewFilters();
}
function playDecorationPreviewVideo() {
  const previewVideo = $("decorationPreviewVideo");
  if (!previewVideo || !state.decorationPreviewUrl) return;
  const tryPlay = () => {
    previewVideo.play().then(() => startDecorationShaderLoop()).catch((err) => {
      if (String(err?.name || "") !== "AbortError") console.warn(err);
    });
  };
  if (previewVideo.readyState >= 3) {
    tryPlay();
    return;
  }
  const onCanPlay = () => {
    previewVideo.removeEventListener("canplay", onCanPlay);
    tryPlay();
  };
  previewVideo.addEventListener("canplay", onCanPlay, { once: true });
  previewVideo.load();
}

function pauseDecorationPreviewVideo() {
  const previewVideo = $("decorationPreviewVideo");
  if (!previewVideo) return;
  previewVideo.pause();
  stopDecorationShaderLoop();
  renderDecorationShaderFrame();
}

function setEditorView(view) {
  state.editorView = view;
  $("timelineViewBtn").classList.toggle("active", view === "timeline");
  $("waveformViewBtn").classList.toggle("active", view === "waveform");
  $("timelinePanel").classList.toggle("hidden-panel", view !== "timeline");
  $("waveformPanel").classList.toggle("hidden-panel", view !== "waveform");
  renderWaveformEditor();
}

function getWaveformDraft() {
  if (!state.waveformDrafts.cut) {
    state.waveformDrafts.cut = { start: null, end: null };
  }
  return state.waveformDrafts.cut;
}

function setWaveformDraftPoint(edge, time = video.currentTime) {
  const draft = getWaveformDraft();
  if (edge === "start") {
    draft.start = time;
    draft.end = null;
  } else {
    if (draft.start == null) draft.start = time;
    draft.end = time;
  }
  if (draft.start != null && draft.end != null && draft.end < draft.start) {
    [draft.start, draft.end] = [draft.end, draft.start];
  }
  renderWaveformEditor();
}

function clearWaveformDraft() {
  state.waveformDrafts.cut = { start: null, end: null };
  renderWaveformEditor();
}

function waveformTimeFromEvent(event) {
  const stage = $("waveformStage");
  const rect = stage.getBoundingClientRect();
  const x = Math.min(Math.max(0, event.clientX - rect.left), rect.width);
  const { start, duration } = sourceRangeBounds();
  return start + (x / Math.max(1, rect.width)) * duration;
}

function commitWaveformSelection(start, end) {
  const interval = {
    src_start: Math.min(start, end),
    src_end: Math.max(start, end),
  };
  if (interval.src_end - interval.src_start < 0.05) return { ok: false, reason: "too_short" };
  const clipped = subtractIntervals([interval], state.protectedSegments);
  if (!clipped.length) return { ok: false, reason: "fully_protected" };
  state.manualCutSegments.push(...clipped);
  state.manualCutSegments.sort((a, b) => a.src_start - b.src_start || a.src_end - b.src_end);
  if (state.editPlan) {
    const nextPlanSegments = normalizeIntervalList(state.editPlan.manual_cut_segments || []);
    nextPlanSegments.push(...clipped);
    state.editPlan.manual_cut_segments = normalizeIntervalList(nextPlanSegments);
  }
  renderWaveformEditor();
  return {
    ok: true,
    requested: interval,
    registered: clipped,
    split: clipped.length > 1,
    protectedOverlap: (
      clipped.length > 1 ||
      clipped[0].src_start !== interval.src_start ||
      clipped[0].src_end !== interval.src_end
    ),
  };
}

function removeWaveformInterval(index) {
  state.manualCutSegments.splice(index, 1);
  if (state.editPlan) state.editPlan.manual_cut_segments = normalizeIntervalList(state.manualCutSegments);
  renderWaveformEditor();
}

function renderWaveformEditor() {
  const { start, duration } = sourceRangeBounds();
  const { manual } = waveformIntervals();
  $("manualCutCount").textContent = `${manual.length}件`;
  const cutDraft = getWaveformDraft();
  const formatDraft = (label, draft) => {
    const hasStart = draft.start != null;
    const hasEnd = draft.end != null;
    if (!hasStart && !hasEnd) return `${label}: 未選択`;
    const startTime = hasStart ? draft.start : draft.end;
    const endTime = hasEnd ? draft.end : draft.start;
    return `${label}: ${fmtTime(Math.min(startTime, endTime))} - ${hasStart && hasEnd ? fmtTime(Math.max(startTime, endTime)) : "未完了"}`;
  };
  $("waveformDraftState").textContent = formatDraft("カット", cutDraft);
  $("waveformSourceModeBtn").classList.toggle("active", state.mode === "source");
  $("waveformPlannedModeBtn").classList.toggle("active", state.mode === "planned");
  $("waveformRenderedModeBtn").classList.toggle("active", state.mode === "rendered");
  const overlay = $("waveformOverlay");
  overlay.textContent = "";
  overlay.innerHTML = "";
  const addBar = (interval, className) => {
    const bar = document.createElement("div");
    bar.className = `waveform-bar ${className}`;
    const left = Math.max(0, ((interval.src_start - start) / duration) * 100);
    const width = Math.max(0.4, ((interval.src_end - interval.src_start) / duration) * 100);
    bar.style.left = `${left}%`;
    bar.style.width = `${width}%`;
    overlay.appendChild(bar);
  };
  manual.forEach((interval) => addBar(interval, "cut"));
  if (cutDraft.start != null || cutDraft.end != null) {
    addBar(
      {
        src_start: Math.min(cutDraft.start ?? cutDraft.end, cutDraft.end ?? cutDraft.start),
        src_end: Math.max(cutDraft.start ?? cutDraft.end, cutDraft.end ?? cutDraft.start),
      },
      "pending cut",
    );
  }
  if (state.waveformLoopRange) addBar(state.waveformLoopRange, "pending");
  updateWaveformPlayhead();
  const manualList = $("manualCutList");
  manualList.textContent = "";
  manual.forEach((interval, index) => {
    const row = document.createElement("div");
    row.className = "interval-row";
    const label = document.createElement("span");
    label.textContent = formatInterval(interval);
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "削除";
    del.addEventListener("click", () => removeWaveformInterval(index));
    row.appendChild(label);
    row.appendChild(del);
    manualList.appendChild(row);
  });
}

function registerWaveformSelection() {
  const draft = getWaveformDraft();
  if (draft.start == null || draft.end == null) return;
  const result = commitWaveformSelection(draft.start, draft.end);
  clearWaveformDraft();
  if (!result.ok) {
    setStatus("区間が短すぎます", true);
  } else if (result.split) {
    setStatus(`${result.registered.length} 区間に分割して登録しました`);
  } else {
    setStatus("カット区間を登録しました");
  }
  renderWaveformEditor();
}

function drawTimeline() {
  const timeline = $("timeline");
  timeline.textContent = "";
  const plan = state.editPlan;
  const modeRendered = state.mode === "rendered";
  const sourceDuration = plan ? plan.source_range.end_sec - plan.source_range.start_sec : Math.max(1, video.duration || 1);
  const outputDuration = plannedOutputDuration();
  const duration = modeRendered || state.mode === "planned" ? outputDuration : sourceDuration;
  const startKey = modeRendered || state.mode === "planned" ? "output_start_sec" : "range_relative_start_sec";
  const endKey = modeRendered || state.mode === "planned" ? "output_end_sec" : "range_relative_end_sec";
  const addBar = (className, start, end, title) => {
    const bar = document.createElement("div");
    bar.className = `bar ${className}`;
    bar.style.left = `${Math.max(0, (start / duration) * 100)}%`;
    bar.style.width = `${Math.max(0.4, ((end - start) / duration) * 100)}%`;
    bar.title = title;
    timeline.appendChild(bar);
  };
  if (plan) {
    for (const seg of plan.segments || []) addBar("speech", Number(seg[startKey]) || 0, Number(seg[endKey]) || 0, seg.id);
    for (const sub of plan.subtitles || []) {
      if (sub.enabled !== false) {
        const start = Number(sub[startKey] ?? sub.output_start_sec ?? sub.range_relative_start_sec ?? 0) || 0;
        const end = Number(sub[endKey] ?? sub.output_end_sec ?? sub.range_relative_end_sec ?? start) || start;
        addBar("subtitle", start, end, sub.speaker_label ? `${sub.speaker_label}: ${sub.text}` : sub.text);
      }
    }
    if (state.mode !== "rendered") {
      const rangeStart = plan.source_range?.start_sec ?? parseTime($("startTime").value);
      for (const cut of plan.manual_cut_segments || []) {
        addBar("cut", Math.max(0, Number(cut.src_start) - rangeStart), Math.max(0, Number(cut.src_end) - rangeStart), "manual cut");
      }
      for (const protect of plan.protected_segments || []) {
        addBar("protect", Math.max(0, Number(protect.src_start) - rangeStart), Math.max(0, Number(protect.src_end) - rangeStart), "protected");
      }
    }
  }
  const playhead = document.createElement("div");
  playhead.className = "playhead";
  const activeMedia = primaryPlaybackVideo();
  const rel = modeRendered ? activeMedia.currentTime : state.mode === "planned" ? plannedOutputTimeFromVideo(activeMedia) : sourceRelativeTime(activeMedia);
  playhead.style.left = `${Math.min(100, Math.max(0, (rel / duration) * 100))}%`;
  timeline.appendChild(playhead);
}

function updateWaveformPreview(url, label = "生成済み") {
  state.waveformUrl = url || null;
  $("waveformState").textContent = url ? label : "未生成";
  $("waveformPreview").src = url ? `${url}?t=${Date.now()}` : "";
  renderWaveformEditor();
}

function setMode(mode) {
  state.mode = mode;
  $("sourceModeBtn").classList.toggle("active", mode === "source");
  $("plannedModeBtn").classList.toggle("active", mode === "planned");
  $("renderedModeBtn").classList.toggle("active", mode === "rendered");
  if ($("subtitlePreviewSourceModeBtn")) $("subtitlePreviewSourceModeBtn").classList.toggle("active", mode === "source");
  if ($("subtitlePreviewPlannedModeBtn")) $("subtitlePreviewPlannedModeBtn").classList.toggle("active", mode === "planned");
  const nextSrc = mode === "rendered" && state.previewUrl ? state.previewUrl : state.sourceVideoUrl;
  if (nextSrc) {
    for (const media of [video, ...mirroredPreviewVideos()].filter(Boolean)) {
      if ((media.dataset.syncSrc || media.getAttribute("src") || "") !== nextSrc) {
        const previousTime = media.currentTime || video.currentTime || 0;
        media.src = nextSrc;
        media.dataset.syncSrc = nextSrc;
        if (previousTime > 0) {
          media.addEventListener("loadedmetadata", () => {
            try {
              media.currentTime = Math.min(previousTime, media.duration || previousTime);
            } catch {}
          }, { once: true });
        }
      }
    }
  }
  syncAllMirroredPreviews();
  updateOverlay();
}

function plannedPreviewTick() {
  const media = primaryPlaybackVideo();
  if (state.mode !== "planned" || !state.editPlan || media.paused) return;
  const rangeStart = state.editPlan.source_range.start_sec;
  const currentRel = media.currentTime - rangeStart;
  const segments = (state.editPlan.segments || [])
    .filter((seg) => seg.enabled !== false)
    .sort((a, b) => Number(a.range_relative_start_sec) - Number(b.range_relative_start_sec));
  const currentSegment = segments.find((seg) => currentRel >= seg.range_relative_start_sec && currentRel <= seg.range_relative_end_sec);
  if (!currentSegment) {
    const next = segments.find((seg) => currentRel < seg.range_relative_start_sec);
    if (next) media.currentTime = rangeStart + next.range_relative_start_sec;
    else media.pause();
    return;
  }
  if (currentRel >= currentSegment.range_relative_end_sec - 0.03) {
    const next = segments.find((seg) => seg.range_relative_start_sec > currentSegment.range_relative_start_sec);
    if (next) media.currentTime = rangeStart + next.range_relative_start_sec;
    else media.pause();
  }
}

function resetProjectRuntimeState() {
  state.projectId = null;
  state.projectName = "";
  state.sourceVideo = null;
  state.sourceVideoUrl = null;
  state.audioPath = null;
  state.transcript = null;
  state.silences = [];
  state.editPlanPath = null;
  state.editPlan = null;
  state.editPlanBuildSignature = "";
  state.selectedSubtitleId = null;
  state.loopSubtitleId = null;
  state.mode = "source";
  state.editorView = "timeline";
  state.manualCutSegments = [];
  state.protectedSegments = [];
  state.waveformDrafts = {
    cut: { start: null, end: null },
  };
  state.waveformLoopRange = null;
  state.previewUrl = null;
  state.decorationPreviewUrl = null;
  state.videoInfo = null;
  state.processingSummary = null;
  state.videoInfoExpanded = false;
  state.projectSettings = {
    default_emotion_preset_id: "emotion_neutral",
    default_subtitle_style_preset_id: "subtitle_standard",
    output_profile: "mp4_compat",
    final_output_mode: "video_srt",
  };
  state.projectScenes = [];
  state.decorationProject = null;
  state.decorationSelectionId = null;
  state.decorationEditTab = "text";
  state.frameSyncMode = "live";
}

function applyLoadedProject(data) {
  state.projectId = data.project_id || state.projectId;
  state.projectName = data.project_name || state.projectId || "";
  state.sourceVideo = data.source_video_path || data.source_video || state.sourceVideo;
  state.sourceVideoUrl = data.source_video_url || state.sourceVideoUrl;
  state.projectSettings = data.ui_state || state.projectSettings;
  syncProjectSettingsForm();
  state.projectScenes = data.scenes || [];
  state.editPlan = data.edit_plan || null;
  state.editPlanPath = data.edit_plan_path || (data.edit_plan ? "edit_plan.json" : null);
  state.manualCutSegments = data.edit_plan?.manual_cut_segments || data.manual_cut_segments || state.manualCutSegments || [];
  state.protectedSegments = data.edit_plan?.protected_segments || data.protected_segments || state.protectedSegments || [];
  state.editPlanBuildSignature = editPlanRequestSignatureFromPlan(state.editPlan);
  if (!state.editPlan && data.subtitles?.length) {
    state.transcript = { subtitles: data.subtitles };
  }
  syncProjectNameInput(state.projectName);
  renderProjectLabel();
  if (state.sourceVideoUrl) video.src = state.sourceVideoUrl;
  syncAllMirroredPreviews();
  $("paths").textContent = state.sourceVideo || "";
  setProjectReady(true);
  renderVideoInfo();
  renderSubtitles();
  renderScenes();
  renderDecorationPage();
}

async function loadProjectById(projectId) {
  if (!projectId) throw new Error("プロジェクトIDがありません");
  const data = await api(`/api/projects/${encodeURIComponent(projectId)}`, { method: "GET" });
  resetProjectRuntimeState();
  applyLoadedProject(data);
  if (!state.editPlan || !(Array.isArray(state.editPlan.subtitles) && state.editPlan.subtitles.length)) {
    let subtitles = await api(`/api/projects/${encodeURIComponent(projectId)}/subtitles?kind=edited`, { method: "GET" }).catch(() => null);
    if (!subtitles?.subtitles?.length) {
      subtitles = await api(`/api/projects/${encodeURIComponent(projectId)}/subtitles?kind=original`, { method: "GET" }).catch(() => null);
    }
    if (subtitles?.subtitles?.length) {
      state.transcript = { subtitles: subtitles.subtitles };
      if (state.editPlan && !(Array.isArray(state.editPlan.subtitles) && state.editPlan.subtitles.length)) {
        state.editPlan.subtitles = subtitles.subtitles;
        state.editPlanBuildSignature = editPlanRequestSignatureFromPlan(state.editPlan);
      }
      renderSubtitles();
    }
  }
  const probe = await api("/api/video/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: state.sourceVideo }),
  });
  state.videoInfo = probe;
  restoreProjectSourceRange(probe.duration_sec);
  syncAllMirroredPreviews();
  setAppPage("editor");
  setEditorView("timeline");
  drawTimeline();
  await loadDecorationProjectFromServer().catch(() => {});
  return data;
}

async function loadProjectList() {
  const data = await api("/api/projects", { method: "GET" });
  state.projectList = data.projects || [];
  renderProjectListPage();
  return state.projectList;
}

function renderProjectListPage() {
  const list = $("projectList");
  if (!list) return;
  const projects = state.projectList || [];
  list.textContent = "";
  if (!projects.length) {
    const empty = document.createElement("div");
    empty.className = "project-list-item";
    empty.textContent = "保存済みプロジェクトがありません。";
    list.appendChild(empty);
    return;
  }
  for (const project of projects) {
    const item = document.createElement("div");
    item.className = `project-list-item${project.project_id === state.projectId ? " selected" : ""}`;
    const meta = document.createElement("div");
    meta.className = "project-meta";
    const title = document.createElement("strong");
    title.textContent = project.project_name || project.project_id;
    const sub = document.createElement("small");
    sub.textContent = `${project.project_id} / ${project.source_video_name || "sourceなし"}`;
    const time = document.createElement("small");
    time.textContent = `更新: ${project.updated_at || "不明"}`;
    const tags = document.createElement("div");
    tags.className = "project-tags";
    [
      project.has_edit_plan ? "字幕済み" : null,
      project.has_transcript ? "文字起こし済み" : null,
      project.has_decoration ? "デコ済み" : null,
      project.has_output ? "出力済み" : null,
    ].filter(Boolean).forEach((label) => {
      const tag = document.createElement("span");
      tag.className = "project-tag";
      tag.textContent = label;
      tags.appendChild(tag);
    });
    meta.appendChild(title);
    meta.appendChild(sub);
    meta.appendChild(time);
    meta.appendChild(tags);
    const actions = document.createElement("div");
    actions.className = "project-actions";
    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.textContent = "開く";
    openBtn.addEventListener("click", () => {
      runStep("プロジェクト読込", async () => {
        await loadProjectById(project.project_id);
      });
    });
    const renameBtn = document.createElement("button");
    renameBtn.type = "button";
    renameBtn.textContent = "名前変更";
    renameBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      runStep("プロジェクト名変更", async () => {
        const currentName = project.project_name || project.project_id;
        const nextName = window.prompt("新しいプロジェクト名", currentName);
        if (nextName === null) return;
        const projectName = nextName.trim();
        if (!projectName) throw new Error("プロジェクト名を入力してください");
        const data = await api(`/api/projects/${encodeURIComponent(project.project_id)}/rename`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_name: projectName }),
        });
        if (state.projectId === project.project_id) {
          state.projectName = data.project?.project_name || projectName;
          syncProjectNameInput(state.projectName);
          renderProjectLabel();
        }
        await loadProjectList();
        setStatus("プロジェクト名を変更しました");
      });
    });
    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.textContent = "削除";
    deleteBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      runStep("プロジェクト削除", async () => {
        const ok = window.confirm(`プロジェクト「${project.project_name || project.project_id}」を削除しますか？`);
        if (!ok) return;
        await api(`/api/projects/${encodeURIComponent(project.project_id)}`, { method: "DELETE" });
        if (state.projectId === project.project_id) {
          resetProjectRuntimeState();
          renderProjectLabel();
          setProjectReady(false);
          $("paths").textContent = "";
        }
        await loadProjectList();
      });
    });
    actions.appendChild(openBtn);
    actions.appendChild(renameBtn);
    actions.appendChild(deleteBtn);
    item.appendChild(meta);
    item.appendChild(actions);
    item.addEventListener("click", () => {
      state.projectId = project.project_id;
      state.projectName = project.project_name || project.project_id;
      renderProjectLabel();
      renderProjectListPage();
    });
    list.appendChild(item);
  }
}

async function loadSelectedVideo() {
  const file = $("videoFile").files[0];
  if (!file) throw new Error("動画ファイルを選択してください");
  const form = new FormData();
  form.append("file", file);
  const projectName = $("projectName").value || autoProjectNameForFile(file.name);
  form.append("project_name", projectName);
  const created = await api("/api/projects", { method: "POST", body: form });
  resetProjectRuntimeState();
  state.projectId = created.project_id;
  state.projectName = created.project_name || projectName;
  state.sourceVideo = created.source_video;
  state.sourceVideoUrl = created.source_video_url;
  state.projectSettings = created.ui_state || state.projectSettings;
  syncProjectSettingsForm();
  state.projectScenes = created.scenes || [];
  syncProjectNameInput(state.projectName);
  renderProjectLabel();
  video.src = state.sourceVideoUrl;
  syncAllMirroredPreviews();
  $("paths").textContent = created.source_video;
  setProjectReady(true);
  const info = await api("/api/video/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: state.sourceVideo }) });
  state.videoInfo = info;
  renderVideoInfo();
  await loadPresets().catch(() => {});
  $("endTime").value = fmtTime(info.duration_sec);
  setSourceRanges(buildSourceRanges(info.duration_sec, Number($("splitMinutes").value) || 20), 0);
  selectSourceRange(0);
  renderSubtitles();
  setAppPage("editor");
  setEditorView("timeline");
  renderWaveformEditor();
  drawTimeline();
  await loadDecorationProjectFromServer().catch(() => {});
}

$("createProjectBtn").addEventListener("click", () => runStep("動画読み込み", loadSelectedVideo));
$("videoFile").addEventListener("change", () => {
  if ($("videoFile").files[0]) {
    $("projectName").value = autoProjectNameForFile($("videoFile").files[0].name);
    runStep("動画読み込み", loadSelectedVideo);
  }
});
$("projectListPageBtn").addEventListener("click", () => {
  setAppPage("projects");
  loadProjectList().catch((err) => setStatus(err.message || String(err), true));
});
$("projectListBackBtn").addEventListener("click", () => setAppPage("editor"));
$("refreshProjectListBtn").addEventListener("click", () => loadProjectList().catch((err) => setStatus(err.message || String(err), true)));
$("saveProjectBtn").addEventListener("click", () =>
  runStep("プロジェクト保存", async () => {
    await saveCurrentProject();
    setStatus("プロジェクトを保存しました");
  })
);
$("overwriteProjectBtn").addEventListener("click", () =>
  runStep("プロジェクト上書き保存", async () => {
    await saveCurrentProject();
    setStatus("プロジェクトを上書き保存しました");
  })
);

$("probeBtn").addEventListener("click", () =>
  runStep("動画情報取得", async () => {
    requireProject();
    const info = await api("/api/video/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: state.sourceVideo }) });
    state.videoInfo = info;
    renderVideoInfo();
  })
);

$("extractBtn").addEventListener("click", () =>
  runStep("音声抽出", async () => {
    await ensureAudioExtracted();
  })
);

$("transcribeBtn").addEventListener("click", () =>
    runStep($("useWhisperxAlignment")?.checked ? "文字起こし 精密補正" : "文字起こし", async () => {
      await ensureAudioExtracted();
      const data = await api("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: state.projectId,
        audio_path: state.audioPath,
        language: $("language").value,
          model: $("model").value,
          ...audioSettings(),
          engine: $("engine").value,
        }),
      });
      const effectiveSubtitles = (Array.isArray(data.aligned_subtitles) && data.aligned_subtitles.length)
        ? data.aligned_subtitles
        : (data.subtitles || []);
      state.transcript = {
        subtitles: effectiveSubtitles,
        raw_subtitles: data.raw_subtitles || data.subtitles || [],
        aligned_subtitles: data.aligned_subtitles || [],
        keep_segments: data.keep_segments || [],
        manual_cut_segments: data.manual_cut_segments || [],
        protected_segments: data.protected_segments || [],
        processing_summary: data.processing_summary || null,
      };
      const defaultEmotion = $("defaultEmotionPreset")?.value || "neutral";
      const defaultStyle = $("defaultSubtitleStylePreset")?.value || "subtitle_standard";
      for (const sub of state.transcript.subtitles || []) {
        if (!sub.emotion) sub.emotion = defaultEmotion;
        if (!sub.subtitle_style_preset_id) sub.subtitle_style_preset_id = defaultStyle;
      }
      syncProjectScenesFromSubtitles();
      state.manualCutSegments = data.manual_cut_segments || state.manualCutSegments || [];
      state.protectedSegments = data.protected_segments || state.protectedSegments || [];
      state.processingSummary = data.processing_summary || null;
      $("paths").textContent = data.srt_path;
      updateWaveformPreview(data.waveform_image_url, "生成済み");
      const timing = audioTimingSettings();
      const silenceData = await api("/api/silence/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: state.projectId,
          audio_path: state.audioPath,
          threshold_db: timing.silence_threshold_db,
          min_silence_duration: timing.min_silence_duration_sec,
          compute_profile: $("computeProfile").value,
        }),
      });
    state.silences = silenceData.silences || [];
    state.processingSummary = {
      ...(state.processingSummary || {}),
      silence_detection: {
        engine: "silencedetect",
        status: "ok",
        count: state.silences.length,
        threshold_db: timing.silence_threshold_db,
        min_silence_duration: timing.min_silence_duration_sec,
      },
    };
    renderSubtitles();
    renderVideoInfo();
    saveProjectScenes().catch(() => {});
  })
);

$("silenceBtn").addEventListener("click", () =>
  runStep("無音検出", async () => {
    requireProject();
    if (!state.audioPath) throw new Error("先に音声を抽出してください");
    const timing = audioTimingSettings();
    const data = await api("/api/silence/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        audio_path: state.audioPath,
        threshold_db: timing.silence_threshold_db,
        min_silence_duration: timing.min_silence_duration_sec,
        compute_profile: $("computeProfile").value,
      }),
    });
    state.silences = data.silences;
    $("paths").textContent = `無音区間 ${state.silences.length}件`;
  })
);

$("planBtn").addEventListener("click", () =>
  runStep("カット案作成", async () => {
    requireProject();
    await ensureEditPlanForCurrentProject({ force: true });
    const segmentCount = (state.editPlan?.segments || []).filter((seg) => seg.enabled !== false).length;
    $("paths").textContent = `${state.editPlanPath || "edit_plan.json"} / 残す区間 ${segmentCount}件`;
  })
);

$("saveSubtitlesBtn").addEventListener("click", () =>
  runStep("字幕保存", async () => {
    const data = await persistCurrentSubtitles();
    renderSubtitles();
    $("paths").textContent = data.srt_path || data.transcript_path;
  })
);

$("previewRenderBtn").addEventListener("click", () =>
  runStep("仮出力", async () => {
    if (subtitleItems().length) {
      await persistCurrentSubtitles();
    }
    await ensureEditPlanForCurrentProject();
    const data = await api("/api/preview/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: state.projectId, quality: "low" }) });
    state.previewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.preview_video_path;
    setMode("rendered");
  })
);

$("manualPreviewBtn").addEventListener("click", () =>
  runStep("手動カット仮出力", async () => {
    requireProject();
    if (subtitleItems().length) {
      await persistCurrentSubtitles();
    }
    const sourceRange = currentRange();
    const data = await api("/api/preview/manual-cuts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        source_range: sourceRange,
        silences: state.silences || [],
        transcript: transcriptForEditPlanRequest(),
        settings: settings(),
        burn_subtitles: $("burnSubtitles").checked,
      }),
    });
    state.previewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.preview_video_path || data.video_url;
    setMode("rendered");
  })
);

async function prepareFinalExport(includeDecoration = false) {
  if (subtitleItems().length) {
    await persistCurrentSubtitles();
  }
  if (includeDecoration && !state.decorationProject && subtitleItems().length) {
    buildDecorationProjectFromSubtitles();
  }
  if (state.decorationProject) {
    await saveDecorationProject();
  }
  await ensureEditPlanForCurrentProject();
  await saveProjectSettings().catch(() => {});
}

function selectedFinalOutputMode() {
  return $("finalOutputMode")?.value || state.projectSettings?.final_output_mode || "video_srt";
}

$("exportBtn").addEventListener("click", () =>
  runStep("最終出力", async () => {
    const outputProfile = $("outputProfile")?.value || state.projectSettings?.output_profile || "mp4_compat";
    const mode = selectedFinalOutputMode();
    await prepareFinalExport(mode !== "video_srt");
    let data = null;
    if (mode === "video_ass") {
      data = await api("/api/decoration/export-ass-package", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: state.projectId, output_profile: outputProfile }),
      });
      $("paths").textContent = `${data.video_path} / ${data.ass_path}`;
      setStatus("カット動画と装飾ASSを出力しました");
      return;
    }
    data = await api("/api/export/final", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        burn_subtitles: mode === "decorated_burned",
        output_profile: outputProfile,
      }),
    });
    $("paths").textContent = `${data.video_path} / ${data.srt_path}`;
    setStatus(mode === "decorated_burned" ? "装飾を焼き込んだ動画を出力しました" : "カット動画とSRTを出力しました");
  })
);

$("setStartBtn").addEventListener("click", () => ($("startTime").value = fmtTime(video.currentTime)));
$("setEndBtn").addEventListener("click", () => ($("endTime").value = fmtTime(video.currentTime)));
$("applyManualRangeBtn").addEventListener("click", () => {
  applyCurrentRangeToSelection();
  drawTimeline();
});
$("split10Btn").addEventListener("click", () => setSourceRanges(buildSourceRanges(video.duration || parseTime($("endTime").value), 10), 0));
$("split15Btn").addEventListener("click", () => setSourceRanges(buildSourceRanges(video.duration || parseTime($("endTime").value), 15), 0));
$("split20Btn").addEventListener("click", () => setSourceRanges(buildSourceRanges(video.duration || parseTime($("endTime").value), 20), 0));
$("split30Btn").addEventListener("click", () => setSourceRanges(buildSourceRanges(video.duration || parseTime($("endTime").value), 30), 0));
$("engine").addEventListener("change", () => {
  const current = $("model").value.trim();
  if ($("engine").value === "whisper.cpp" && (!current || current === "base" || current === "small")) $("model").value = "large-v3";
  if ($("engine").value === "openai-whisper" && (!current || current === "large-v3")) $("model").value = "base";
  if ($("engine").value === "faster-whisper" && (!current || current === "large-v3")) $("model").value = "base";
});
$("voiceIsolationEnabled").addEventListener("change", syncAudioSettingsControls);
$("audioTimingPreset").addEventListener("change", () => applyAudioTimingValues({ preset_id: $("audioTimingPreset").value }));
$("applyAudioTimingPresetBtn").addEventListener("click", () => applyAudioTimingValues({ preset_id: $("audioTimingPreset").value }));
$("finalOutputMode")?.addEventListener("change", () => saveProjectSettings().catch(() => {}));
$("outputProfile")?.addEventListener("change", () => saveProjectSettings().catch(() => {}));
$("sourceModeBtn").addEventListener("click", () => setMode("source"));
$("plannedModeBtn").addEventListener("click", () => setMode("planned"));
$("renderedModeBtn").addEventListener("click", () => setMode("rendered"));
$("subtitlePreviewSourceModeBtn").addEventListener("click", () => setMode("source"));
$("subtitlePreviewPlannedModeBtn").addEventListener("click", () =>
  runStep("字幕プレビュー カット案再生", async () => {
    await ensureEditPlanForCurrentProject();
    setMode("planned");
  })
);
$("editorPageBtn").addEventListener("click", () => setAppPage("editor"));
$("subtitlePageBtn").addEventListener("click", () => setAppPage("subtitles"));
$("settingsPageBtn").addEventListener("click", () => setAppPage("settings"));
$("decorationPageBtn").addEventListener("click", () => setAppPage("decoration"));
$("previewCheckPageBtn").addEventListener("click", () => setAppPage("previewCheck"));
$("subtitlePageBackBtn").addEventListener("click", () => setAppPage("editor"));
$("subtitleSyncScenesBtn").addEventListener("click", () => {
  syncProjectScenesFromSubtitles();
  saveProjectScenes().catch(() => {});
  renderScenes();
  setStatus("字幕からシーンを再同期しました");
});
$("extendSubtitleTimesBtn")?.addEventListener("click", () => {
  const count = extendAllSubtitleDisplayTimes(0.5);
  setStatus(count ? `全字幕 ${count} 件を前後0.5秒延長しました。確定するには字幕を保存してください。` : "延長する字幕がありません", !count);
});
$("settingsBackBtn").addEventListener("click", () => setAppPage("editor"));
$("decorationBackBtn").addEventListener("click", () => setAppPage("editor"));
$("previewCheckBackBtn").addEventListener("click", () => setAppPage("decoration"));
$("videoInfoToggleBtn").addEventListener("click", () => {
  state.videoInfoExpanded = !state.videoInfoExpanded;
  renderVideoInfo();
});
$("sourceRangeList").addEventListener("click", (event) => {
  const row = event.target.closest(".source-range-item");
  if (!row) return;
  const rows = Array.from($("sourceRangeList").querySelectorAll(".source-range-item"));
  const index = rows.indexOf(row);
  if (index >= 0) selectSourceRange(index);
});
$("waveformPlayPauseBtn").addEventListener("click", () => {
  if (video.paused) video.play().catch(() => {});
  else video.pause();
});
$("waveformSourceModeBtn").addEventListener("click", () => setMode("source"));
$("waveformPlannedModeBtn").addEventListener("click", () => setMode("planned"));
$("waveformRenderedModeBtn").addEventListener("click", () => setMode("rendered"));
$("timelineViewBtn").addEventListener("click", () => setEditorView("timeline"));
$("waveformViewBtn").addEventListener("click", () => setEditorView("waveform"));
$("waveformClearBtn").addEventListener("click", () => {
  clearWaveformDraft();
  state.waveformLoopRange = null;
  renderWaveformEditor();
});
$("waveformDeleteLastBtn").addEventListener("click", () => {
  state.manualCutSegments.pop();
  renderWaveformEditor();
});
$("waveformCutStartBtn").addEventListener("click", () => setWaveformDraftPoint("start"));
$("waveformCutEndBtn").addEventListener("click", () => {
  setWaveformDraftPoint("end");
  registerWaveformSelection();
});
$("applyDefaultPresetBtn").addEventListener("click", () => {
  const sub = selectedSubtitle();
  if (!sub) {
    setStatus("先に字幕を選択してください", true);
    return;
  }
  applyDefaultPresetToSubtitle(sub);
  renderSubtitles();
  updateOverlay();
});
$("resetDefaultPresetBtn").addEventListener("click", () => {
  resetProjectDefaultPresetsToStandard();
});
$("addSceneBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  addManualSceneFromCurrentRange();
});
$("syncScenesBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  resyncScenesFromSubtitles();
});
$("reassignScenesBtn").addEventListener("click", () =>
  runStep("scene_id再割当", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    const result = reassignSubtitlesToScenes();
    const data = await persistCurrentSubtitles();
    syncProjectScenesFromSubtitles();
    await saveProjectScenes();
    renderSubtitles();
    renderScenes();
    updateOverlay();
    $("paths").textContent = data.srt_path || data.transcript_path || "";
    setStatus(`scene_idを ${result.reassigned} 件再割当しました`);
  })
);
$("defaultEmotionPreset").addEventListener("change", () => {
  saveProjectSettings().catch(() => {});
  renderScenes();
});
$("defaultSubtitleStylePreset").addEventListener("change", () => {
  saveProjectSettings().catch(() => {});
  renderScenes();
});
$("loadDecorationFromSubtitlesBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  reloadDecorationFromSource()
    .then(() => setStatus("字幕からデコレーションを生成しました"))
    .catch((err) => setStatus(err.message || String(err), true));
});
$("createEffectGroupFromCurrentBtn").addEventListener("click", () =>
  runStep("演出セット作成", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    const created = createDecorationEffectGroupFromCurrentEvent();
    if (!created) throw new Error("先に対象字幕を選択してください");
    await saveDecorationProject();
    renderDecorationPage();
    setStatus("現在字幕から演出セットを作成しました");
  })
);
$("decorationReloadBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  reloadDecorationFromSource().catch((err) => setStatus(err.message || String(err), true));
});
$("saveDecorationBtn").addEventListener("click", () =>
  runStep("デコレーション保存", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    await saveDecorationProject();
    setStatus("デコレーションを保存しました");
  })
);
$("exportDecorationJsonBtn").addEventListener("click", () =>
  runStep("JSON出力", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    downloadDecorationProjectJson();
  })
);
$("buildDecorationAssBtn").addEventListener("click", () =>
  runStep("ASS出力", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    await saveDecorationProject();
    const data = await api("/api/decoration/ass", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, decoration: state.decorationProject }),
    });
    $("paths").textContent = data.ass_path;
    setStatus("ASSを出力しました");
  })
);
$("exportDecorationAssPackageBtn").addEventListener("click", () =>
  runStep("カット動画+ASS出力", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (subtitleItems().length) await persistCurrentSubtitles();
    if (!state.decorationProject) await reloadDecorationFromSource();
    await saveDecorationProject();
    await ensureEditPlanForCurrentProject();
    const data = await api("/api/decoration/export-ass-package", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        output_profile: $("outputProfile")?.value || state.projectSettings?.output_profile || "mp4_compat",
      }),
    });
    $("paths").textContent = `${data.video_path} / ${data.ass_path}`;
    setStatus("カット済み動画と装飾ASSを出力しました");
  })
);
$("renderDecorationPreviewBtn").addEventListener("click", () =>
  runStep("装飾プレビュー", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    await saveDecorationProject();
    const data = await api("/api/decoration/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, preview: true, max_height: 480, fps: 5, duration_sec: 15 }),
    });
    state.decorationPreviewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.video_path;
    renderDecorationPage();
    setAppPage("previewCheck");
    playDecorationPreviewVideo();
    setStatus("先頭15秒の480p点検プレビューを作成しました");
  })
);
$("renderCurrentScenePreviewBtn").addEventListener("click", () =>
  runStep("現在字幕プレビュー", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    const windowInfo = selectedDecorationPreviewWindow();
    if (!windowInfo) throw new Error("先に字幕または文字イベントを選択してください");
    await saveDecorationProject();
    const data = await api("/api/decoration/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        preview: true,
        max_height: 480,
        fps: 5,
        start_sec: windowInfo.start_sec,
        duration_sec: windowInfo.duration_sec,
      }),
    });
    state.decorationPreviewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.video_path;
    renderDecorationPage();
    setAppPage("previewCheck");
    playDecorationPreviewVideo();
    setStatus(`現在字幕の480p点検プレビューを作成しました: ${windowInfo.label}`);
  })
);
$("openMpvPreviewBtn").addEventListener("click", () =>
  runStep("軽量装飾プレビュー", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) await reloadDecorationFromSource();
    await saveDecorationProject();
    const data = await api("/api/decoration/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, preview: true, max_height: 240, fps: 3 }),
    });
    state.decorationPreviewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.video_path;
    renderDecorationPage();
    setAppPage("previewCheck");
    playDecorationPreviewVideo();
    setStatus("240p/3fpsの軽量プレビューを作成しました");
  })
);
$("decorationPreviewPlayBtn").addEventListener("click", () => {
  if (!state.decorationPreviewUrl) {
    setStatus("先に装飾プレビューを作成してください", true);
    return;
  }
  playDecorationPreviewVideo();
});
$("decorationPreviewPauseBtn").addEventListener("click", () => {
  pauseDecorationPreviewVideo();
});
const decorationPreviewVideoEl = $("decorationPreviewVideo");
if (decorationPreviewVideoEl) {
  decorationPreviewVideoEl.addEventListener("timeupdate", updateDecorationPreviewFilters);
  decorationPreviewVideoEl.addEventListener("seeked", updateDecorationPreviewFilters);
  decorationPreviewVideoEl.addEventListener("loadedmetadata", () => {
    updateDecorationPreviewFilters();
    renderDecorationShaderFrame();
    updateZoomBoxOverlay();
  });
  decorationPreviewVideoEl.addEventListener("playing", startDecorationShaderLoop);
  decorationPreviewVideoEl.addEventListener("pause", stopDecorationShaderLoop);
  decorationPreviewVideoEl.addEventListener("ended", stopDecorationShaderLoop);
}
bindZoomBoxOverlayInteraction();
$("decorationAddGroupBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  const current = currentDecorationEvent();
  const sourceGroup = current?.text_effect_group_id || current?.effect_group_id || state.presets.decoration_presets?.effect_groups?.[0]?.id || "effect_group_custom";
  const nextId = `effect_group_${String(Date.now()).slice(-8)}`;
  const preset = (state.presets.decoration_presets?.effect_groups || []).find((group) => group.id === sourceGroup);
  const nextGroup = {
    id: nextId,
    name: `カスタム ${String((state.decorationProject.effect_groups || []).length + 1).padStart(2, "0")}`,
    effects: [...(preset?.effects || ["bubble_round"])],
    description: "手動追加グループ",
  };
  state.decorationProject.effect_groups = [...(state.decorationProject.effect_groups || []), nextGroup];
  if (current) {
    current.text_effect_group_id = nextId;
    current.effect_group_id = nextId;
  }
  renderDecorationPage();
});
$("decorationSourceSelect").addEventListener("change", () => {
  if (!state.projectId) return;
  reloadDecorationFromSource().catch((err) => setStatus(err.message || String(err), true));
});
$("waveformStage").addEventListener("click", (event) => {
  if (state.editorView !== "waveform") return;
  const time = waveformTimeFromEvent(event);
  const draft = getWaveformDraft();
  if (draft.start == null || draft.end != null) {
    setWaveformDraftPoint("start", time);
    return;
  }
  setWaveformDraftPoint("end", time);
  registerWaveformSelection();
});
video.addEventListener("timeupdate", updateOverlay);
video.addEventListener("timeupdate", syncAllMirroredPreviews);
video.addEventListener("loadedmetadata", drawTimeline);
video.addEventListener("loadedmetadata", syncAllMirroredPreviews);
video.addEventListener("play", syncAllMirroredPreviews);
video.addEventListener("pause", syncAllMirroredPreviews);
video.addEventListener("seeked", syncAllMirroredPreviews);
video.addEventListener("ratechange", syncAllMirroredPreviews);
setInterval(plannedPreviewTick, 60);
setInterval(loopSubtitleTick, 50);
setInterval(waveformLoopTick, 50);
setAppPage("editor");
syncAudioSettingsControls();
syncAudioSettingsControls();
startBrowserHeartbeat();
window.addEventListener("pagehide", sendBrowserCloseSignal);
window.addEventListener("beforeunload", sendBrowserCloseSignal);
loadPresets().catch(() => {});


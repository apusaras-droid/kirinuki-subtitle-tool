const state = {
  projectId: null,
  sourceVideo: null,
  sourceVideoUrl: null,
  audioPath: null,
  transcript: null,
  silences: [],
  editPlanPath: null,
  editPlan: null,
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
};

const $ = (id) => document.getElementById(id);
const video = $("video");
const statusEl = $("status");

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function setBusy(busy) {
  document.querySelectorAll("button").forEach((button) => (button.disabled = busy));
}

function setProjectReady(ready) {
  for (const id of ["saveSubtitlesBtn", "manualPreviewBtn", "previewRenderBtn", "exportBtn", "probeBtn", "extractBtn", "transcribeBtn", "silenceBtn", "planBtn"]) {
    $(id).disabled = !ready;
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
}

function setAppPage(page) {
  state.appPage = page;
  $("editorPageBtn").classList.toggle("active", page === "editor");
  $("settingsPageBtn").classList.toggle("active", page === "settings");
  $("videoShellWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorControlsWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorModeWrap").classList.toggle("hidden-panel", page !== "editor");
  $("processWrap").classList.toggle("hidden-panel", page !== "editor");
  $("workspaceWrap").classList.toggle("hidden-panel", page !== "editor");
  $("settingsPage").classList.toggle("hidden-panel", page !== "settings");
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
  try {
    setBusy(true);
    setStatus(`${label}中...`);
    const result = await fn();
    setStatus(`${label}が完了しました`);
    return result;
  } catch (err) {
    setStatus(err.message || String(err), true);
    return null;
  } finally {
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
  return {
    compute_profile: $("computeProfile").value,
    detection_mode: $("useVad").checked ? "vad" : "silencedetect",
    voice_isolation_enabled: $("voiceIsolationEnabled").checked,
    use_isolated_voice_for_vad: $("useIsolatedVoiceForVad").checked,
    use_isolated_voice_for_whisper: $("useIsolatedVoiceForWhisper").checked,
    silence_threshold_db: -35.0,
    subtitle_font_name: $("subtitleFontName").value.trim() || "Meiryo",
    subtitle_font_size: Number($("subtitleFontSize").value) || 42,
    subtitle_outline_width: Number($("subtitleOutlineWidth").value) || 0,
    min_keep_segment_duration: 1.0,
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

function sourceRangeBounds() {
  const start = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  const end = state.editPlan?.source_range?.end_sec ?? parseTime($("endTime").value);
  return { start, end, duration: Math.max(0.001, end - start) };
}

function audioSettings() {
  return {
    compute_profile: $("computeProfile").value,
    detection_mode: $("useVad").checked ? "vad" : "silencedetect",
    voice_isolation_enabled: $("voiceIsolationEnabled").checked,
    use_isolated_voice_for_vad: $("useIsolatedVoiceForVad").checked,
    use_isolated_voice_for_whisper: $("useIsolatedVoiceForWhisper").checked,
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

function sourceRelativeTime() {
  const rangeStart = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
  return Math.max(0, video.currentTime - rangeStart);
}

function plannedOutputTimeFromVideo() {
  if (!state.editPlan) return 0;
  const rel = sourceRelativeTime();
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

function plannedOutputDuration() {
  const plan = state.editPlan;
  if (!plan) return Math.max(1, video.duration || 1);
  return Math.max(
    0.1,
    ...[...(plan.segments || []).map((seg) => Number(seg.output_end_sec) || 0), ...(plan.subtitles || []).map((sub) => Number(sub.output_end_sec) || 0)],
  );
}

function subtitleTimebase() {
  if (state.mode === "source") return sourceRelativeTime();
  if (state.mode === "planned") return plannedOutputTimeFromVideo();
  return video.currentTime;
}

function updateOverlay() {
  const t = subtitleTimebase();
  const sub = activeSubtitles().find((item) => t >= item.output_start_sec && t <= item.output_end_sec);
  $("subtitleOverlay").textContent = sub ? (sub.speaker_label ? `${sub.speaker_label}: ${sub.text}` : sub.text) : "";
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

function loopSubtitleTick() {
  if (!state.loopSubtitleId || video.paused) return;
  const sub = activeSubtitles().find((item) => item.id === state.loopSubtitleId);
  if (!sub) return;
  const { start, end } = subtitleRangeInCurrentMode(sub);
  if (video.currentTime < start) {
    video.currentTime = start;
    return;
  }
  if (video.currentTime >= end - 0.03) {
    video.currentTime = start;
    video.play().catch(() => {});
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
  state.selectedSubtitleId = sub.id;
  state.loopSubtitleId = sub.id;
  if (state.mode === "source" || state.mode === "planned") {
    const rangeStart = state.editPlan?.source_range?.start_sec ?? parseTime($("startTime").value);
    video.currentTime = rangeStart + (sub.range_relative_start_sec ?? sub.output_start_sec);
  } else {
    video.currentTime = sub.output_start_sec;
  }
  renderSubtitles();
  video.play().catch(() => {});
}

function renderSubtitles() {
  const list = $("subtitleList");
  const subtitles = state.editPlan?.subtitles || state.transcript?.subtitles || [];
  $("subtitleCount").textContent = `${subtitles.length}件`;
  list.textContent = "";
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
    item.appendChild(textarea);
    item.appendChild(actions);

    item.addEventListener("input", (event) => {
      const target = event.target;
      const field = target.dataset.field;
      if (!field) return;
      if (field === "enabled") sub.enabled = target.checked;
      else if (field === "text") sub.text = target.value;
      else if (field === "speaker_label") sub.speaker_label = target.value;
      else sub[field] = parseTime(target.value);
      updateOverlay();
      drawTimeline();
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
      if (action === "start") sub.output_start_sec = subtitleTimebase();
      if (action === "end") sub.output_end_sec = subtitleTimebase();
      if (action === "merge-prev" && index > 0) {
        const prev = subtitles[index - 1];
        prev.text = `${prev.text || ""}${prev.text ? "\n" : ""}${sub.text || ""}`;
        prev.output_end_sec = sub.output_end_sec;
        subtitles.splice(index, 1);
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
      }
      renderSubtitles();
      updateOverlay();
    });
    list.appendChild(item);
  });
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
  const rel = modeRendered ? video.currentTime : state.mode === "planned" ? plannedOutputTimeFromVideo() : sourceRelativeTime();
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
  if (mode === "rendered" && state.previewUrl) video.src = state.previewUrl;
  if ((mode === "source" || mode === "planned") && state.sourceVideoUrl) video.src = state.sourceVideoUrl;
  updateOverlay();
}

function plannedPreviewTick() {
  if (state.mode !== "planned" || !state.editPlan || video.paused) return;
  const rangeStart = state.editPlan.source_range.start_sec;
  const currentRel = video.currentTime - rangeStart;
  const segments = state.editPlan.segments || [];
  const currentSegment = segments.find((seg) => currentRel >= seg.range_relative_start_sec && currentRel <= seg.range_relative_end_sec);
  if (!currentSegment) {
    const next = segments.find((seg) => currentRel < seg.range_relative_start_sec);
    if (next) video.currentTime = rangeStart + next.range_relative_start_sec;
    else video.pause();
    return;
  }
  if (currentRel >= currentSegment.range_relative_end_sec - 0.03) {
    const next = segments.find((seg) => seg.range_relative_start_sec > currentSegment.range_relative_start_sec);
    if (next) video.currentTime = rangeStart + next.range_relative_start_sec;
    else video.pause();
  }
}

async function loadSelectedVideo() {
  const file = $("videoFile").files[0];
  if (!file) throw new Error("動画ファイルを選択してください");
  const form = new FormData();
  form.append("file", file);
  form.append("project_name", $("projectName").value || file.name.replace(/\.[^.]+$/, ""));
  const created = await api("/api/projects", { method: "POST", body: form });
  state.projectId = created.project_id;
  state.sourceVideo = created.source_video;
  state.sourceVideoUrl = created.source_video_url;
  state.audioPath = null;
  state.transcript = null;
  state.silences = [];
  state.editPlanPath = null;
  state.editPlan = null;
  state.manualCutSegments = [];
  state.protectedSegments = [];
  state.waveformDrafts = {
    cut: { start: null, end: null },
  };
  state.waveformLoopRange = null;
  state.previewUrl = null;
  state.videoInfo = null;
  state.processingSummary = null;
  video.src = state.sourceVideoUrl;
  $("projectLabel").textContent = state.projectId;
  $("paths").textContent = created.source_video;
  setProjectReady(true);
  const info = await api("/api/video/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: state.sourceVideo }) });
  state.videoInfo = info;
  renderVideoInfo();
  $("endTime").value = fmtTime(info.duration_sec);
  setSourceRanges(buildSourceRanges(info.duration_sec, Number($("splitMinutes").value) || 20), 0);
  selectSourceRange(0);
  renderSubtitles();
  setAppPage("editor");
  setEditorView("timeline");
  renderWaveformEditor();
  drawTimeline();
}

$("createProjectBtn").addEventListener("click", () => runStep("動画読み込み", loadSelectedVideo));
$("videoFile").addEventListener("change", () => {
  if ($("videoFile").files[0]) {
    runStep("動画読み込み", loadSelectedVideo);
  }
});

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
  runStep("文字起こし", async () => {
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
        silence_threshold_db: -35.0,
      }),
    });
    state.transcript = {
      subtitles: data.subtitles || [],
      raw_subtitles: data.raw_subtitles || data.subtitles || [],
      keep_segments: data.keep_segments || [],
      manual_cut_segments: data.manual_cut_segments || [],
      protected_segments: data.protected_segments || [],
      processing_summary: data.processing_summary || null,
    };
    state.manualCutSegments = data.manual_cut_segments || state.manualCutSegments || [];
    state.protectedSegments = data.protected_segments || state.protectedSegments || [];
    state.processingSummary = data.processing_summary || null;
    $("paths").textContent = data.srt_path;
    updateWaveformPreview(data.waveform_image_url, "生成済み");
    const silenceData = await api("/api/silence/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, audio_path: state.audioPath, threshold_db: -35.0, min_silence_duration: 0.7, compute_profile: $("computeProfile").value }),
    });
    state.silences = silenceData.silences || [];
    state.processingSummary = {
      ...(state.processingSummary || {}),
      silence_detection: {
        engine: "silencedetect",
        status: "ok",
        count: state.silences.length,
        threshold_db: -35.0,
        min_silence_duration: 0.7,
      },
    };
    renderSubtitles();
    renderVideoInfo();
  })
);

$("silenceBtn").addEventListener("click", () =>
  runStep("無音検出", async () => {
    requireProject();
    if (!state.audioPath) throw new Error("先に音声を抽出してください");
    const data = await api("/api/silence/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, audio_path: state.audioPath, threshold_db: -35.0, min_silence_duration: 0.7, compute_profile: $("computeProfile").value }),
    });
    state.silences = data.silences;
    $("paths").textContent = `無音区間 ${state.silences.length}件`;
  })
);

$("planBtn").addEventListener("click", () =>
  runStep("カット案作成", async () => {
    requireProject();
    const data = await api("/api/edit-plan/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, source_range: currentRange(), silences: state.silences, transcript: state.transcript || {}, settings: settings() }),
    });
    state.editPlanPath = data.edit_plan_path;
    state.editPlan = data.edit_plan;
    state.manualCutSegments = data.edit_plan?.manual_cut_segments || state.manualCutSegments || [];
    state.protectedSegments = data.edit_plan?.protected_segments || state.protectedSegments || [];
    renderSubtitles();
    renderWaveformEditor();
    drawTimeline();
    $("paths").textContent = state.editPlanPath;
  })
);

$("saveSubtitlesBtn").addEventListener("click", () =>
  runStep("字幕保存", async () => {
    const subtitles = state.editPlan?.subtitles || state.transcript?.subtitles;
    if (!subtitles) throw new Error("先に文字起こしを実行してください");
    const endpoint = state.editPlanPath && state.editPlan ? "/api/subtitles/update" : "/api/transcript/update";
    const data = await api(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, subtitles }),
    });
    if (data.edit_plan) {
      state.editPlan = data.edit_plan;
    } else if (data.transcript) {
      state.transcript = {
        ...state.transcript,
        ...data.transcript,
      };
    }
    renderSubtitles();
    $("paths").textContent = data.srt_path || data.transcript_path;
  })
);

$("previewRenderBtn").addEventListener("click", () =>
  runStep("仮出力", async () => {
    if (!state.editPlanPath) throw new Error("先にカット案を作成してください");
    const data = await api("/api/preview/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: state.projectId, quality: "low" }) });
    state.previewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.preview_video_path;
    setMode("rendered");
  })
);

$("manualPreviewBtn").addEventListener("click", () =>
  runStep("手動カット仮出力", async () => {
    requireProject();
    const sourceRange = currentRange();
    const data = await api("/api/preview/manual-cuts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.projectId,
        source_range: sourceRange,
        silences: state.silences || [],
        transcript: state.transcript || {},
        settings: settings(),
        burn_subtitles: $("burnSubtitles").checked,
      }),
    });
    state.previewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.preview_video_path || data.video_url;
    setMode("rendered");
  })
);

$("exportBtn").addEventListener("click", () =>
  runStep("最終出力", async () => {
    if (!state.editPlanPath) throw new Error("先にカット案を作成してください");
    const data = await api("/api/export/final", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: state.projectId, burn_subtitles: $("burnSubtitles").checked }) });
    $("paths").textContent = `${data.video_path} / ${data.srt_path}`;
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
$("sourceModeBtn").addEventListener("click", () => setMode("source"));
$("plannedModeBtn").addEventListener("click", () => setMode("planned"));
$("renderedModeBtn").addEventListener("click", () => setMode("rendered"));
$("editorPageBtn").addEventListener("click", () => setAppPage("editor"));
$("settingsPageBtn").addEventListener("click", () => setAppPage("settings"));
$("settingsBackBtn").addEventListener("click", () => setAppPage("editor"));
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
video.addEventListener("loadedmetadata", drawTimeline);
setInterval(plannedPreviewTick, 60);
setInterval(loopSubtitleTick, 50);
setInterval(waveformLoopTick, 50);
setAppPage("editor");
syncAudioSettingsControls();
syncAudioSettingsControls();

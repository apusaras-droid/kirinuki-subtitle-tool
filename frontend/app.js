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
  videoInfoExpanded: false,
  projectSettings: {
    default_emotion_preset_id: "emotion_neutral",
    default_subtitle_style_preset_id: "subtitle_standard",
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

function subtitleItems() {
  return state.editPlan?.subtitles || state.transcript?.subtitles || [];
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

async function loadPresets() {
  const data = await api("/api/presets", { method: "GET" });
  state.presets = {
    emotion_presets: data.emotion_presets || [],
    subtitle_style_presets: data.subtitle_style_presets || [],
    scenes: data.scenes || [],
    decoration_presets: data.decoration_presets || {
      font_presets: [],
      effect_groups: [],
      layout_presets: [],
    },
    emotion_labels: data.emotion_labels || ["neutral", "joy", "anger", "sadness", "surprise", "fear", "embarrassment", "teasing"],
  };
  updatePresetSelectors();
  renderSubtitles();
  renderVideoInfo();
  renderDecorationPage();
}

function syncProjectScenesFromSubtitles() {
  const byId = new Map();
  for (const scene of state.projectScenes || []) {
    const sceneId = String(scene.id || "").trim();
    if (!sceneId) continue;
    byId.set(sceneId, {
      id: sceneId,
      start_sec: Number(scene.start_sec ?? 0) || 0,
      end_sec: Number(scene.end_sec ?? 0) || 0,
      emotion: scene.emotion || "neutral",
      effect_group_id: scene.effect_group_id || "",
      subtitle_style_preset_id: scene.subtitle_style_preset_id || "",
      comment_ids: [...(scene.comment_ids || [])],
    });
  }
  for (const sub of subtitleItems()) {
    const sceneId = String(sub.scene_id || "").trim();
    if (!sceneId) continue;
    if (!byId.has(sceneId)) {
      byId.set(sceneId, {
        id: sceneId,
        start_sec: Number(sub.start_sec ?? sub.output_start_sec ?? 0) || 0,
        end_sec: Number(sub.end_sec ?? sub.output_end_sec ?? 0) || 0,
        emotion: sub.emotion || "neutral",
        effect_group_id: sub.effect_group_id || "",
        subtitle_style_preset_id: sub.subtitle_style_preset_id || "",
        comment_ids: [],
      });
    }
    const scene = byId.get(sceneId);
    scene.comment_ids.push(sub.id);
    if (!scene.emotion && sub.emotion) scene.emotion = sub.emotion;
    if (!scene.subtitle_style_preset_id && sub.subtitle_style_preset_id) scene.subtitle_style_preset_id = sub.subtitle_style_preset_id;
    if (!scene.effect_group_id && sub.effect_group_id) scene.effect_group_id = sub.effect_group_id;
  }
  state.projectScenes = Array.from(byId.values()).sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
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
  return data;
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
    default_emotion_preset_id: $("defaultEmotionPreset")?.value || "emotion_neutral",
    default_subtitle_style_preset_id: $("defaultSubtitleStylePreset")?.value || "subtitle_standard",
  };
  const data = await api("/api/projects/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.projectSettings = data.project?.ui_state || state.projectSettings;
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

function sceneCatalog() {
  const subtitles = subtitleItems();
  const byId = new Map();
  for (const scene of state.projectScenes || []) {
    const sceneId = String(scene.id || "").trim();
    if (!sceneId) continue;
    byId.set(sceneId, {
      id: sceneId,
      start_sec: Number(scene.start_sec ?? 0) || 0,
      end_sec: Number(scene.end_sec ?? 0) || 0,
      emotion: scene.emotion || "neutral",
      effect_group_id: scene.effect_group_id || "",
      subtitle_style_preset_id: scene.subtitle_style_preset_id || "",
      comment_ids: [...(scene.comment_ids || [])],
    });
  }
  for (const sub of subtitles) {
    const sceneId = sub.scene_id || "";
    if (!sceneId) continue;
    if (!byId.has(sceneId)) {
      byId.set(sceneId, {
        id: sceneId,
        start_sec: Number(sub.start_sec ?? sub.output_start_sec ?? 0) || 0,
        end_sec: Number(sub.end_sec ?? sub.output_end_sec ?? 0) || 0,
        comment_ids: [],
      });
    }
    const scene = byId.get(sceneId);
    scene.comment_ids.push(sub.id);
    if (!scene.emotion && sub.emotion) scene.emotion = sub.emotion;
    if (!scene.subtitle_style_preset_id && sub.subtitle_style_preset_id) scene.subtitle_style_preset_id = sub.subtitle_style_preset_id;
  }
  const presetScenes = state.presets.scenes || [];
  for (const scene of presetScenes) {
    if (!byId.has(scene.id)) {
      byId.set(scene.id, { ...scene, comment_ids: scene.comment_ids || [] });
    }
  }
  return Array.from(byId.values()).sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec);
}

function renderScenes() {
  const list = $("sceneList");
  if (!list) return;
  const scenes = sceneCatalog();
  $("sceneCount").textContent = `${scenes.length}件`;
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
  state.appPage = page;
  $("editorPageBtn").classList.toggle("active", page === "editor");
  $("settingsPageBtn").classList.toggle("active", page === "settings");
  $("decorationPageBtn").classList.toggle("active", page === "decoration");
  $("videoShellWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorControlsWrap").classList.toggle("hidden-panel", page !== "editor");
  $("editorModeWrap").classList.toggle("hidden-panel", page !== "editor");
  $("processWrap").classList.toggle("hidden-panel", page !== "editor");
  $("workspaceWrap").classList.toggle("hidden-panel", page !== "editor");
  $("settingsPage").classList.toggle("hidden-panel", page !== "settings");
  $("decorationPage").classList.toggle("hidden-panel", page !== "decoration");
  if (page === "decoration" && !(state.decorationProject?.events?.length) && subtitleItems().length) {
    buildDecorationProjectFromSubtitles();
  }
  if (page === "decoration") renderDecorationPage();
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
    default_emotion_preset_id: $("defaultEmotionPreset")?.value || "emotion_neutral",
    default_subtitle_style_preset_id: $("defaultSubtitleStylePreset")?.value || "subtitle_standard",
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
  const subtitles = subtitleItems();
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

    const presetRow = document.createElement("div");
    presetRow.className = "subtitle-preset-row";
    const emotionLabel = document.createElement("label");
    emotionLabel.textContent = "感情";
    const emotionSelect = presetOptions(
      (state.presets.emotion_labels || []).map((emotion) => ({
        id: emotion,
        name: emotion,
      })),
      sub.emotion || "neutral",
      "",
    );
    emotionSelect.dataset.field = "emotion";
    emotionLabel.appendChild(emotionSelect);
    presetRow.appendChild(emotionLabel);

    const styleLabel = document.createElement("label");
    styleLabel.textContent = "字幕スタイル";
    const styleSelect = presetOptions(
      state.presets.subtitle_style_presets || [],
      sub.subtitle_style_preset_id || "",
      "",
    );
    styleSelect.dataset.field = "subtitle_style_preset_id";
    styleLabel.appendChild(styleSelect);
    presetRow.appendChild(styleLabel);

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
      ["scene-apply", "同シーンへ反映"],
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
    item.appendChild(presetRow);
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
      else if (field === "emotion") {
        sub.emotion = target.value;
        const matchedPreset = (state.presets.emotion_presets || []).find((preset) => preset.emotion === target.value);
        if (matchedPreset?.subtitle_style_preset_id) {
          sub.subtitle_style_preset_id = matchedPreset.subtitle_style_preset_id;
          const styleSelect = item.querySelector('[data-field="subtitle_style_preset_id"]');
          if (styleSelect) styleSelect.value = matchedPreset.subtitle_style_preset_id;
        }
      } else if (field === "subtitle_style_preset_id") {
        sub.subtitle_style_preset_id = target.value;
      }
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
      if (action === "scene-apply") {
        const sceneId = sub.scene_id || "";
        if (sceneId) {
          for (const itemSub of subtitles) {
            if (itemSub.scene_id === sceneId) {
              itemSub.emotion = sub.emotion || "neutral";
              itemSub.subtitle_style_preset_id = sub.subtitle_style_preset_id || "";
            }
          }
          saveProjectScenes().catch(() => {});
        }
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
      saveProjectScenes().catch(() => {});
    });
    list.appendChild(item);
  });
  renderScenes();
  renderDecorationPage();
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

function decorationFontPresets() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  return (project.font_presets && project.font_presets.length ? project.font_presets : presets.font_presets || []).map((preset) => ({ ...preset }));
}

function decorationLayoutPresets() {
  const project = state.decorationProject || {};
  const presets = state.presets.decoration_presets || {};
  return (project.layout_presets && project.layout_presets.length ? project.layout_presets : presets.layout_presets || []).map((preset) => ({ ...preset }));
}

function buildDecorationProjectFromSubtitles() {
  const subtitles = decorationSourceSubtitles();
  const presets = state.presets.decoration_presets || {};
  state.decorationProject = {
    project_id: state.projectId,
    source_srt: state.editPlanPath ? "subtitles/edited.srt" : "subtitles/original.srt",
    events: subtitles.map((sub) => ({
      id: sub.id,
      subtitle_id: sub.subtitle_id,
      text: sub.text,
      start_sec: sub.start_sec,
      end_sec: sub.end_sec,
      scene_id: sub.scene_id,
      speaker_label: sub.speaker_label,
      emotion: sub.emotion,
      subtitle_style_preset_id: sub.subtitle_style_preset_id,
      effect_group_id: sub.effect_group_id || (presets.effect_groups?.[0]?.id || ""),
      font_preset_id: presets.font_presets?.[0]?.id || "font_standard",
      layout_preset_id: presets.layout_presets?.[0]?.id || "layout_bottom_center",
      seed: sub.seed,
      enabled: sub.enabled,
    })),
    effect_groups: decorationEffectGroups(),
    font_presets: decorationFontPresets(),
    layout_presets: decorationLayoutPresets(),
    scenes: sceneCatalog(),
  };
  state.decorationSelectionId = state.decorationProject.events[0]?.id || null;
  renderDecorationPage();
  return state.decorationProject;
}

function currentDecorationEvent() {
  if (!state.decorationProject?.events?.length) return null;
  return state.decorationProject.events.find((item) => item.id === state.decorationSelectionId) || state.decorationProject.events[0] || null;
}

async function loadDecorationProjectFromServer() {
  if (!state.projectId) return null;
  const data = await api(`/api/projects/${state.projectId}/decoration`, { method: "GET" });
  state.decorationProject = data.decoration || null;
  if (state.decorationProject?.events?.length) {
    state.decorationSelectionId = state.decorationProject.events[0].id;
  }
  renderDecorationPage();
  return state.decorationProject;
}

async function saveDecorationProject() {
  if (!state.projectId) return null;
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
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
  state.decorationProject = data.decoration || state.decorationProject;
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
  $("decorationPreviewLabel").textContent = state.decorationPreviewUrl ? "生成済み" : "未生成";
  if (previewVideo) {
    previewVideo.src = state.decorationPreviewUrl ? `${state.decorationPreviewUrl}?t=${Date.now()}` : "";
  }
  list.textContent = "";
  groupList.textContent = "";
  if (!project) {
    detail.textContent = "字幕から生成するとここで装飾を編集できます。";
  } else {
    const selected = currentDecorationEvent();
    $("decorationSelectionLabel").textContent = selected ? selected.id : "未選択";
    detail.textContent = "";
    if (selected) {
      const preview = document.createElement("div");
      preview.className = "decoration-preview";
      const previewMeta = document.createElement("div");
      previewMeta.textContent = `${fmtTime(selected.start_sec)} - ${fmtTime(selected.end_sec)} / ${selected.scene_id || "sceneなし"} / ${selected.speaker_label || "speakerなし"}`;
      const previewLine = document.createElement("div");
      previewLine.className = "preview-line";
      previewLine.textContent = selected.text || "";
      const chipRow = document.createElement("div");
      chipRow.className = "decoration-chip-list";
      [selected.emotion || "neutral", selected.subtitle_style_preset_id || "styleなし", selected.effect_group_id || "effectなし"].forEach((label) => {
        const chip = document.createElement("span");
        chip.className = "decoration-chip";
        chip.textContent = label;
        chipRow.appendChild(chip);
      });
      preview.appendChild(previewMeta);
      preview.appendChild(previewLine);
      preview.appendChild(chipRow);
      detail.appendChild(preview);

      const fields = document.createElement("div");
      fields.className = "decoration-fields";
      const makeField = (labelText, control) => {
        const label = document.createElement("label");
        label.textContent = labelText;
        label.appendChild(control);
        return label;
      };
      const emotion = presetOptions(
        (state.presets.emotion_labels || []).map((item) => ({ id: item, name: item })),
        selected.emotion || "neutral",
      );
      emotion.addEventListener("change", () => {
        selected.emotion = emotion.value || "neutral";
        renderDecorationPage();
      });
      const font = presetOptions(decorationFontPresets(), selected.font_preset_id || "", "");
      font.addEventListener("change", () => {
        selected.font_preset_id = font.value || "";
        renderDecorationPage();
      });
      const style = presetOptions(state.presets.subtitle_style_presets || [], selected.subtitle_style_preset_id || "", "");
      style.addEventListener("change", () => {
        selected.subtitle_style_preset_id = style.value || "";
        renderDecorationPage();
      });
      const effect = presetOptions(groups, selected.effect_group_id || "", "");
      effect.addEventListener("change", () => {
        selected.effect_group_id = effect.value || "";
        renderDecorationPage();
      });
      const layout = presetOptions(decorationLayoutPresets(), selected.layout_preset_id || "", "");
      layout.addEventListener("change", () => {
        selected.layout_preset_id = layout.value || "";
        renderDecorationPage();
      });
      const seedInput = document.createElement("input");
      seedInput.type = "number";
      seedInput.value = Number(selected.seed || 0);
      seedInput.addEventListener("change", () => {
        selected.seed = Number(seedInput.value) || 0;
      });
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = selected.enabled !== false;
      enabled.addEventListener("change", () => {
        selected.enabled = enabled.checked;
      });
      fields.appendChild(makeField("感情", emotion));
      fields.appendChild(makeField("フォント", font));
      fields.appendChild(makeField("字幕スタイル", style));
      fields.appendChild(makeField("エフェクトグループ", effect));
      fields.appendChild(makeField("レイアウト", layout));
      fields.appendChild(makeField("seed", seedInput));
      fields.appendChild(makeField("有効", enabled));
      detail.appendChild(fields);
    }
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
    subline.textContent = `${eventItem.scene_id || "sceneなし"} / ${eventItem.emotion || "neutral"} / ${eventItem.effect_group_id || "effectなし"}`;
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
    item.appendChild(idx);
    item.appendChild(meta);
    item.appendChild(action);
    item.addEventListener("click", () => {
      state.decorationSelectionId = eventItem.id;
      renderDecorationPage();
    });
    list.appendChild(item);
  });

  groups.forEach((group) => {
    const item = document.createElement("div");
    item.className = `effect-group-item${currentDecorationEvent()?.effect_group_id === group.id ? " selected" : ""}`;
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
    const effectRow = document.createElement("div");
    effectRow.className = "effect-group-effects";
    const effectInput = document.createElement("input");
    effectInput.value = (group.effects || []).join(", ");
    effectInput.placeholder = "effect_a, effect_b";
    effectInput.style.minWidth = "240px";
    const controls = document.createElement("div");
    controls.className = "decoration-toolbar";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = "保存";
    saveBtn.addEventListener("click", () => {
      const target = state.decorationProject?.effect_groups || [];
      const nextEffects = effectInput.value.split(",").map((item) => item.trim()).filter(Boolean);
      for (let i = 0; i < target.length; i += 1) {
        if (target[i].id === group.id) {
          target[i] = {
            ...target[i],
            name: nameInput.value.trim() || target[i].name || target[i].id,
            description: description.value.trim(),
            effects: nextEffects,
          };
        }
      }
      if (state.decorationProject) {
        state.decorationProject.effect_groups = target;
      }
      renderDecorationPage();
    });
    const applyBtn = document.createElement("button");
    applyBtn.type = "button";
    applyBtn.textContent = "選択へ適用";
    applyBtn.addEventListener("click", () => {
      const current = currentDecorationEvent();
      if (!current) return;
      current.effect_group_id = group.id;
      renderDecorationPage();
    });
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.textContent = "削除";
    removeBtn.addEventListener("click", () => {
      if (!state.decorationProject) return;
      state.decorationProject.effect_groups = (state.decorationProject.effect_groups || []).filter((item) => item.id !== group.id);
      for (const eventItem of state.decorationProject.events || []) {
        if (eventItem.effect_group_id === group.id) eventItem.effect_group_id = "";
      }
      renderDecorationPage();
    });
    controls.appendChild(saveBtn);
    controls.appendChild(applyBtn);
    controls.appendChild(removeBtn);
    for (const effect of group.effects || []) {
      const chip = document.createElement("span");
      chip.className = "decoration-chip";
      chip.textContent = effect;
      effectRow.appendChild(chip);
    }
    item.appendChild(header);
    item.appendChild(nameInput);
    item.appendChild(description);
    item.appendChild(effectInput);
    item.appendChild(controls);
    item.appendChild(effectRow);
    groupList.appendChild(item);
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
  state.decorationPreviewUrl = null;
  state.videoInfo = null;
  state.processingSummary = null;
  state.videoInfoExpanded = false;
  state.projectSettings = created.ui_state || state.projectSettings;
  state.projectScenes = created.scenes || [];
  state.decorationProject = null;
  state.decorationSelectionId = null;
  video.src = state.sourceVideoUrl;
  $("projectLabel").textContent = state.projectId;
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
    saveProjectScenes().catch(() => {});
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
    const data = await persistCurrentSubtitles();
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
$("decorationPageBtn").addEventListener("click", () => setAppPage("decoration"));
$("settingsBackBtn").addEventListener("click", () => setAppPage("editor"));
$("decorationBackBtn").addEventListener("click", () => setAppPage("editor"));
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
  buildDecorationProjectFromSubtitles();
  setStatus("字幕からデコレーションを生成しました");
});
$("decorationReloadBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  loadDecorationProjectFromServer().catch((err) => setStatus(err.message || String(err), true));
});
$("saveDecorationBtn").addEventListener("click", () =>
  runStep("デコレーション保存", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) buildDecorationProjectFromSubtitles();
    await saveDecorationProject();
    setStatus("デコレーションを保存しました");
  })
);
$("exportDecorationJsonBtn").addEventListener("click", () => {
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  downloadDecorationProjectJson();
});
$("buildDecorationAssBtn").addEventListener("click", () =>
  runStep("ASS出力", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) buildDecorationProjectFromSubtitles();
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
$("renderDecorationPreviewBtn").addEventListener("click", () =>
  runStep("装飾プレビュー", async () => {
    if (!state.projectId) throw new Error("先に動画を読み込んでください");
    if (!state.decorationProject) buildDecorationProjectFromSubtitles();
    await saveDecorationProject();
    const data = await api("/api/decoration/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: state.projectId, preview: true }),
    });
    state.decorationPreviewUrl = `${data.video_url}?t=${Date.now()}`;
    $("paths").textContent = data.video_path;
    renderDecorationPage();
    setAppPage("decoration");
  })
);
$("decorationAddGroupBtn").addEventListener("click", () => {
  if (!state.projectId) {
    setStatus("先に動画を読み込んでください", true);
    return;
  }
  if (!state.decorationProject) buildDecorationProjectFromSubtitles();
  const current = currentDecorationEvent();
  const sourceGroup = current?.effect_group_id || state.presets.decoration_presets?.effect_groups?.[0]?.id || "effect_group_custom";
  const nextId = `effect_group_${String(Date.now()).slice(-8)}`;
  const preset = (state.presets.decoration_presets?.effect_groups || []).find((group) => group.id === sourceGroup);
  const nextGroup = {
    id: nextId,
    name: `カスタム ${String((state.decorationProject.effect_groups || []).length + 1).padStart(2, "0")}`,
    effects: [...(preset?.effects || ["bubble_round"])],
    description: "手動追加グループ",
  };
  state.decorationProject.effect_groups = [...(state.decorationProject.effect_groups || []), nextGroup];
  if (current) current.effect_group_id = nextId;
  renderDecorationPage();
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
loadPresets().catch(() => {});

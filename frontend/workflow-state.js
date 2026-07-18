(function initWorkflowState(global) {
  "use strict";

  const SCHEMA_VERSION = "1.2.0";

  const STEPS = Object.freeze([
    { id: "STEP_PROJECT", page: "project", label: "プロジェクト作成" },
    { id: "STEP_TRANSCRIBE", page: "editor", label: "字幕作成方式" },
    { id: "STEP_AI_SUBTITLE", page: "aiSubtitle", label: "Gemini AI編集（任意）" },
    { id: "STEP_CUT", page: "cut", label: "カット編集" },
    { id: "STEP_SUBTITLE_EDIT", page: "subtitles", label: "字幕編集" },
    { id: "STEP_DECORATION", page: "decoration", label: "デコレーション" },
    { id: "STEP_PREVIEW", page: "previewCheck", label: "プレビュー点検" },
    { id: "STEP_EXPORT", page: "export", label: "動画出力" },
  ]);

  const STATUS = new Set([
    "not_started",
    "current",
    "valid",
    "invalidated",
    "completed",
    "blocked",
    "error",
  ]);

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function blankState() {
    return {
      schemaVersion: SCHEMA_VERSION,
      revision: 0,
      currentStepId: "STEP_PROJECT",
      stepStatus: Object.fromEntries(STEPS.map((step, index) => [step.id, index === 0 ? "current" : "not_started"])),
      execution: { status: "idle", snapshot: null },
      errors: [],
    };
  }

  function normalizeState(value) {
    const next = blankState();
    if (!value || typeof value !== "object") return next;
    next.schemaVersion = SCHEMA_VERSION;
    next.revision = Math.max(0, Number(value.revision) || 0);
    if (STEPS.some((step) => step.id === value.currentStepId)) next.currentStepId = value.currentStepId;
    for (const step of STEPS) {
      const status = value.stepStatus?.[step.id];
      if (STATUS.has(status)) next.stepStatus[step.id] = status;
    }
    if (value.execution && typeof value.execution === "object") {
      next.execution = {
        status: String(value.execution.status || "idle"),
        snapshot: value.execution.snapshot && typeof value.execution.snapshot === "object" ? clone(value.execution.snapshot) : null,
      };
    }
    next.errors = Array.isArray(value.errors) ? clone(value.errors).slice(-20) : [];
    return next;
  }

  function inferState(saved, artifacts = {}) {
    const legacyCutBeforeSubtitle = Boolean(saved && saved.schemaVersion === "1.0.0");
    const next = normalizeState(saved);
    const completed = {
      STEP_PROJECT: Boolean(artifacts.projectReady),
      STEP_TRANSCRIBE: Boolean(artifacts.transcriptReady && artifacts.editPlanReady),
      STEP_AI_SUBTITLE: Boolean(
        artifacts.aiSubtitleConfirmed || artifacts.cutConfirmed || artifacts.subtitleConfirmed || artifacts.decorationReady || artifacts.previewReady || artifacts.outputReady
      ),
      STEP_CUT: Boolean(
        artifacts.cutConfirmed || (legacyCutBeforeSubtitle && artifacts.subtitleConfirmed) || artifacts.decorationReady || artifacts.previewReady || artifacts.outputReady
      ),
      STEP_SUBTITLE_EDIT: Boolean(
        artifacts.subtitleConfirmed || artifacts.decorationReady || artifacts.previewReady || artifacts.outputReady
      ),
      STEP_DECORATION: Boolean(artifacts.decorationReady || artifacts.previewReady || artifacts.outputReady),
      STEP_PREVIEW: Boolean(artifacts.previewReady || artifacts.outputReady),
      STEP_EXPORT: Boolean(artifacts.outputReady),
    };

    for (const step of STEPS) {
      if (completed[step.id] && next.stepStatus[step.id] !== "invalidated") {
        next.stepStatus[step.id] = "completed";
      }
    }

    let current = STEPS.find((step) => next.stepStatus[step.id] === "invalidated");
    if (!current) current = STEPS.find((step) => next.stepStatus[step.id] !== "completed");
    if (!current) current = STEPS[STEPS.length - 1];
    next.currentStepId = current.id;
    for (const step of STEPS) {
      if (step.id === current.id && next.stepStatus[step.id] !== "completed") {
        next.stepStatus[step.id] = "current";
      }
    }
    return next;
  }

  class WorkflowStore {
    constructor(initial) {
      this._state = normalizeState(initial);
      this._listeners = new Set();
    }

    getState() {
      return clone(this._state);
    }

    replace(value, artifacts) {
      this._state = inferState(value, artifacts);
      this._emit();
      return this.getState();
    }

    update(mutator) {
      const draft = this.getState();
      mutator(draft);
      draft.revision = this._state.revision + 1;
      this._state = normalizeState(draft);
      this._emit();
      return this.getState();
    }

    setCurrent(stepId) {
      if (!STEPS.some((step) => step.id === stepId)) return this.getState();
      return this.update((draft) => {
        draft.currentStepId = stepId;
        if (draft.stepStatus[stepId] !== "completed") draft.stepStatus[stepId] = "current";
      });
    }

    markCompleted(stepId) {
      const index = STEPS.findIndex((step) => step.id === stepId);
      if (index < 0) return this.getState();
      return this.update((draft) => {
        draft.stepStatus[stepId] = "completed";
        const next = STEPS[index + 1];
        if (next) {
          draft.currentStepId = next.id;
          if (draft.stepStatus[next.id] !== "completed") draft.stepStatus[next.id] = "current";
        } else {
          draft.currentStepId = stepId;
        }
      });
    }

    invalidateFrom(stepId) {
      const index = STEPS.findIndex((step) => step.id === stepId);
      if (index < 0) return this.getState();
      return this.update((draft) => {
        STEPS.slice(index).forEach((step, offset) => {
          draft.stepStatus[step.id] = offset === 0 ? "current" : "invalidated";
        });
        draft.currentStepId = stepId;
        draft.execution = { status: "idle", snapshot: null };
      });
    }

    invalidateAfter(stepId) {
      const index = STEPS.findIndex((step) => step.id === stepId);
      if (index < 0) return this.getState();
      return this.update((draft) => {
        draft.stepStatus[stepId] = "current";
        STEPS.slice(index + 1).forEach((step) => {
          draft.stepStatus[step.id] = "invalidated";
        });
        draft.currentStepId = stepId;
        draft.execution = { status: "idle", snapshot: null };
      });
    }

    setExecution(status, snapshot = null) {
      return this.update((draft) => {
        draft.execution = { status, snapshot: snapshot ? clone(snapshot) : null };
      });
    }

    subscribe(listener) {
      this._listeners.add(listener);
      listener(this.getState());
      return () => this._listeners.delete(listener);
    }

    _emit() {
      const value = this.getState();
      this._listeners.forEach((listener) => listener(value));
    }
  }

  global.KirinukiWorkflow = Object.freeze({ STEPS, WorkflowStore, inferState });
})(window);

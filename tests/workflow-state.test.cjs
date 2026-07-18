const assert = require("node:assert/strict");

global.window = global;
require("../frontend/workflow-state.js");

const { WorkflowStore } = global.KirinukiWorkflow;

const store = new WorkflowStore();
let state = store.getState();
assert.equal(state.currentStepId, "STEP_PROJECT");
assert.equal(state.stepStatus.STEP_PROJECT, "current");

store.replace(null, {
  projectReady: true,
  transcriptReady: false,
  editPlanReady: false,
});
state = store.getState();
assert.equal(state.stepStatus.STEP_PROJECT, "completed");
assert.equal(state.currentStepId, "STEP_TRANSCRIBE");

const transcriptOnlyStore = new WorkflowStore();
transcriptOnlyStore.replace(null, {
  projectReady: true,
  transcriptReady: true,
  editPlanReady: false,
});
assert.equal(transcriptOnlyStore.getState().stepStatus.STEP_TRANSCRIBE, "completed");
assert.equal(transcriptOnlyStore.getState().currentStepId, "STEP_AI_SUBTITLE");

store.markCompleted("STEP_TRANSCRIBE");
state = store.getState();
assert.equal(state.stepStatus.STEP_TRANSCRIBE, "completed");
assert.equal(state.currentStepId, "STEP_AI_SUBTITLE");

store.markCompleted("STEP_AI_SUBTITLE");
state = store.getState();
assert.equal(state.stepStatus.STEP_AI_SUBTITLE, "completed");
assert.equal(state.currentStepId, "STEP_CUT");

store.markCompleted("STEP_CUT");
state = store.getState();
assert.equal(state.stepStatus.STEP_CUT, "completed");
assert.equal(state.currentStepId, "STEP_SUBTITLE_EDIT");

store.markCompleted("STEP_SUBTITLE_EDIT");
store.markCompleted("STEP_DECORATION");
store.markCompleted("STEP_PREVIEW");
store.invalidateAfter("STEP_CUT");
state = store.getState();
assert.equal(state.currentStepId, "STEP_CUT");
assert.equal(state.stepStatus.STEP_CUT, "current");
assert.equal(state.stepStatus.STEP_SUBTITLE_EDIT, "invalidated");
assert.equal(state.stepStatus.STEP_DECORATION, "invalidated");
assert.equal(state.stepStatus.STEP_PREVIEW, "invalidated");
assert.equal(state.stepStatus.STEP_EXPORT, "invalidated");

const snapshot = { projectId: "sample", outputMode: "video_srt" };
store.setExecution("running", snapshot);
snapshot.projectId = "changed-after-start";
state = store.getState();
assert.equal(state.execution.snapshot.projectId, "sample");
assert.equal(state.execution.status, "running");

const legacyStore = new WorkflowStore();
legacyStore.replace(
  {
    schemaVersion: "1.0.0",
    currentStepId: "STEP_SUBTITLE_EDIT",
    stepStatus: {
      STEP_PROJECT: "completed",
      STEP_TRANSCRIBE: "completed",
      STEP_SUBTITLE_EDIT: "completed",
    },
  },
  {
    projectReady: true,
    transcriptReady: true,
    editPlanReady: true,
    subtitleConfirmed: true,
  },
);
assert.equal(legacyStore.getState().stepStatus.STEP_CUT, "completed");
assert.equal(legacyStore.getState().stepStatus.STEP_AI_SUBTITLE, "completed");
assert.equal(legacyStore.getState().schemaVersion, "1.2.0");

const subtitleFirstStore = new WorkflowStore();
subtitleFirstStore.replace(
  {
    schemaVersion: "1.1.0",
    currentStepId: "STEP_CUT",
    stepStatus: {
      STEP_PROJECT: "completed",
      STEP_TRANSCRIBE: "completed",
      STEP_AI_SUBTITLE: "completed",
      STEP_SUBTITLE_EDIT: "completed",
      STEP_CUT: "not_started",
    },
  },
  {
    projectReady: true,
    transcriptReady: true,
    editPlanReady: true,
    subtitleConfirmed: true,
    cutConfirmed: false,
  },
);
assert.equal(subtitleFirstStore.getState().stepStatus.STEP_CUT, "current");
assert.equal(subtitleFirstStore.getState().schemaVersion, "1.2.0");

console.log("workflow-state tests passed");

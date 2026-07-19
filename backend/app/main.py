from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .edit_plan import build_edit_plan, build_speaker_roster
from .audit import audit_event
from .versioning import version_info
from .services import (
    FRONTEND_DIR,
    atomic_write_json,
    create_project_from_upload,
    detect_silence,
    detect_vad_speech_intervals,
    extract_audio,
    finish_transcription_progress,
    prepare_audio_track_preview,
    render_from_plan_data,
    normalize_edit_plan_source_video,
    probe_video,
    project_info,
    load_project_decoration,
    render_from_plan,
    resolve_project_path,
    require_project,
    load_project_edit_plan,
    load_project_decoration,
    load_project_subtitles,
    list_projects,
    list_system_fonts,
    normalize_ass_subtitle_style,
    preset_catalog,
    build_scene_catalog_from_subtitles,
    delete_project,
    project_source_video,
    project_processing_progress,
    transcribe_audio,
    transcribe_audio_range,
    render_decoration_video,
    export_cut_video_with_decoration_ass,
    build_decoration_ass,
    choose_output_directory,
    configured_export_directory,
    open_directory_in_file_manager,
    publish_export_result,
    save_project_decoration,
    save_shared_decoration_presets,
    launch_mpv,
    update_project_info,
)
from .srt import write_srt
from .app_settings import load_app_settings, save_app_settings
from .gemini_service import (
    analyze_project_with_gemini,
    apply_gemini_proposal,
    gemini_config_status,
    gemini_model_status,
    link_project_knowledge_base,
    list_shared_knowledge_bases,
    load_project_knowledge_base,
    load_gemini_proposal,
    research_project_knowledge,
    register_project_knowledge_as_shared,
    save_gemini_config,
    save_project_knowledge_base,
    transcribe_project_with_gemini,
    translate_project_subtitles,
)
from .subtitle_text import normalize_bilingual_settings

app = FastAPI(title="切り抜き字幕作成ツール MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVER_HEARTBEAT_TIMEOUT_SEC = 60.0 * 60.0 * 6.0
SERVER_CLOSE_GRACE_SEC = 30.0
SERVER_HEARTBEAT_CHECK_SEC = 5.0
_browser_heartbeat_at = time.monotonic()
_browser_heartbeat_enabled = False
_browser_close_requested_at: float | None = None
_browser_shutdown_started = False
_active_api_requests = 0
_active_api_lock = threading.Lock()


def _shutdown_process_tree() -> None:
    current_pid = os.getpid()
    if os.name == "nt":
        subprocess.Popen(
            ["taskkill", "/PID", str(current_pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return
    try:
        os.kill(current_pid, signal.SIGTERM)
    except Exception:
        os._exit(0)


def _browser_heartbeat_watchdog() -> None:
    global _browser_shutdown_started
    while True:
        time.sleep(SERVER_HEARTBEAT_CHECK_SEC)
        if not _browser_heartbeat_enabled or _browser_shutdown_started:
            continue
        with _active_api_lock:
            active_requests = _active_api_requests
        if active_requests > 0:
            continue
        now = time.monotonic()
        close_requested = _browser_close_requested_at is not None and now - _browser_close_requested_at >= SERVER_CLOSE_GRACE_SEC
        heartbeat_expired = now - _browser_heartbeat_at >= SERVER_HEARTBEAT_TIMEOUT_SEC
        if close_requested or heartbeat_expired:
            _browser_shutdown_started = True
            audit_event(
                "server.shutdown.browser_closed",
                context={
                    "timeout_sec": SERVER_HEARTBEAT_TIMEOUT_SEC,
                    "close_grace_sec": SERVER_CLOSE_GRACE_SEC,
                    "close_requested": close_requested,
                    "heartbeat_expired": heartbeat_expired,
                },
            )
            _shutdown_process_tree()
            return


threading.Thread(target=_browser_heartbeat_watchdog, name="browser-heartbeat-watchdog", daemon=True).start()


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    global _active_api_requests
    started = time.perf_counter()
    count_as_active = request.url.path not in {"/api/browser/heartbeat", "/api/version"}
    if count_as_active:
        with _active_api_lock:
            _active_api_requests += 1
    try:
        response = await call_next(request)
    finally:
        if count_as_active:
            with _active_api_lock:
                _active_api_requests = max(0, _active_api_requests - 1)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    project_id = None
    segments = [segment for segment in request.url.path.split("/") if segment]
    if len(segments) >= 3 and segments[0] == "api" and segments[1] == "projects":
        project_id = segments[2]
    audit_event(
        "api.request",
        project_id=project_id,
        context={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
        },
    )
    if request.url.path in {"/", "/index.html", "/app.js", "/styles.css"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


class ProbeRequest(BaseModel):
    video_path: str


class ExtractAudioRequest(BaseModel):
    project_id: str
    video_path: str
    start_sec: float
    end_sec: float
    compute_profile: str = "auto"
    audio_stream_index: int | None = None


class AudioTrackPreviewRequest(BaseModel):
    project_id: str
    audio_stream_index: int


class TranscribeRequest(BaseModel):
    project_id: str
    audio_path: str
    language: str = "ja"
    model: str = "small"
    compute_profile: str = "auto"
    engine: str = "whisper.cpp"
    silence_threshold_db: float = -35.0
    detection_mode: str = "silencedetect"
    voice_isolation_enabled: bool = False
    use_isolated_voice_for_vad: bool = False
    use_isolated_voice_for_whisper: bool = False
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 100
    vad_min_silence_duration_ms: int = 80
    vad_speech_pad_ms: int = 50
    pre_margin_sec: float = 0.3
    post_margin_sec: float = 0.5
    min_speech_duration_sec: float = 0.2
    merge_silence_gap_sec: float = 0.5
    align_timestamps: bool = False
    use_whisperx_alignment: bool = False


class RangeTranscribeRequest(BaseModel):
    project_id: str
    start_sec: float
    end_sec: float
    subtitles: list[dict[str, Any]] = []
    replacement_mode: str = "text_and_timing"
    analysis_padding_sec: float = 1.5
    language: str = "ja"
    model: str = "small"
    compute_profile: str = "auto"
    engine: str = "whisper.cpp-vad"
    detection_mode: str = "vad"
    voice_isolation_enabled: bool = False
    use_isolated_voice_for_vad: bool = False
    use_isolated_voice_for_whisper: bool = False
    vad_threshold: float = 0.5
    vad_min_speech_duration_ms: int = 100
    vad_min_silence_duration_ms: int = 80
    vad_speech_pad_ms: int = 50
    pre_margin_sec: float = 0.3
    post_margin_sec: float = 0.5
    min_speech_duration_sec: float = 0.2
    merge_silence_gap_sec: float = 0.5
    align_timestamps: bool = False


class SilenceRequest(BaseModel):
    project_id: str
    audio_path: str
    threshold_db: float = -35.0
    min_silence_duration: float = 0.7
    compute_profile: str = "auto"


class VadRequest(BaseModel):
    project_id: str
    audio_path: str
    silence_threshold_db: float | None = None
    vad_threshold: float = 0.5
    min_speech_duration_sec: float = 0.2
    min_silence_duration_sec: float = 0.5
    speech_pad_sec: float = 0.05
    merge_silence_gap_sec: float = 0.5
    compute_profile: str = "auto"


class EditPlanRequest(BaseModel):
    project_id: str
    source_range: dict[str, float]
    silences: list[dict[str, float]] = []
    transcript: dict[str, Any] = {}
    settings: dict[str, Any] = {}


class EditPlanUpdateRequest(BaseModel):
    project_id: str
    edit_plan: dict[str, Any]


class SubtitleUpdateRequest(BaseModel):
    project_id: str
    subtitles: list[dict[str, Any]]
    speaker_roster: list[dict[str, Any]] | None = None


class TranscriptUpdateRequest(BaseModel):
    project_id: str
    subtitles: list[dict[str, Any]]
    speaker_roster: list[dict[str, Any]] | None = None


class TranscriptSkipRequest(BaseModel):
    project_id: str


class RenderRequest(BaseModel):
    project_id: str
    quality: str = "low"
    burn_subtitles: bool = False
    subtitle_mode: str = "external"
    subtitle_format: str = "srt"
    output_profile: str | None = None
    destination_mode: str = "project"
    output_directory: str | None = None
    output_filename: str | None = None


class DraftRenderRequest(BaseModel):
    project_id: str
    source_range: dict[str, float]
    silences: list[dict[str, float]] = []
    transcript: dict[str, Any] = {}
    settings: dict[str, Any] = {}
    quality: str = "low"
    burn_subtitles: bool = False
    output_profile: str | None = None


class ProjectSettingsRequest(BaseModel):
    project_id: str
    project_name: str | None = None
    default_emotion_preset_id: str | None = None
    default_subtitle_style_preset_id: str | None = None
    output_profile: str | None = None
    final_output_mode: str | None = None
    audio_stream_index: int | None = None
    audio_timing: dict[str, Any] | None = None
    transcription_mode: str | None = None
    subtitle_click_playback_mode: str | None = None
    ass_subtitle_defaults: dict[str, Any] | None = None
    bilingual_subtitle_settings: dict[str, Any] | None = None


class AppSettingsRequest(BaseModel):
    startup_mode: str | None = None
    last_project_id: str | None = None
    default_output_directory: str | None = None
    output_create_project_subdirectory: bool | None = None


class DirectoryPickerRequest(BaseModel):
    initial_directory: str | None = None


class OpenExportDirectoryRequest(BaseModel):
    project_id: str


class ProjectWorkflowRequest(BaseModel):
    project_id: str
    workflow: dict[str, Any]


class GeminiConfigRequest(BaseModel):
    api_key: str | None = None
    model: str | None = None
    clear_key: bool = False
    speaker_labels_enabled: bool | None = None
    srt_timing_priority: bool | None = None


class GeminiAnalyzeRequest(BaseModel):
    project_id: str
    model: str | None = None
    instructions: str = ""
    task: str = "subtitle"


class GeminiTranscribeRequest(BaseModel):
    project_id: str
    model: str | None = None
    language: str = "ja"
    bilingual_subtitle_settings: dict[str, Any] | None = None


class GeminiTranslateRequest(BaseModel):
    project_id: str
    model: str | None = None
    source_language: str = "en"
    target_language: str = "ja"
    display_mode: str = "source_above"


class GeminiApplyRequest(BaseModel):
    project_id: str
    subtitle_edit_ids: list[str] = []
    chapter_ids: list[str] = []
    cut_ids: list[str] = []


class GeminiKnowledgeResearchRequest(BaseModel):
    project_id: str
    work_title: str
    model: str | None = None
    instructions: str = ""


class GeminiKnowledgeSaveRequest(BaseModel):
    project_id: str
    knowledge_base: dict[str, Any]


class GeminiKnowledgeRegisterRequest(BaseModel):
    project_id: str
    database_name: str


class GeminiKnowledgeLinkRequest(BaseModel):
    project_id: str
    database_id: str | None = None


class ProjectRenameRequest(BaseModel):
    project_name: str


class ProjectScenesRequest(BaseModel):
    project_id: str
    scenes: list[dict[str, Any]]


class ProjectDecorationRequest(BaseModel):
    project_id: str
    decoration: dict[str, Any]


class SharedDecorationPresetsRequest(BaseModel):
    project_id: str | None = None
    decoration: dict[str, Any]


class DecorationRenderRequest(BaseModel):
    project_id: str
    preview: bool = True
    max_height: int | None = 480
    fps: int | None = None
    start_sec: float | None = None
    duration_sec: float | None = None


class MpvLaunchRequest(BaseModel):
    project_id: str
    target: str = "decoration_preview"
    path: str | None = None
    pause: bool = False


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), project_name: str | None = Form(default=None)):
    return await create_project_from_upload(file, project_name)


@app.get("/api/projects")
def list_projects_api():
    return {"projects": list_projects()}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    base = require_project(project_id)
    project_path = base / "project.json"
    data = project_info(project_id) if project_path.exists() else {"project_id": project_id}
    data["source_video_path"] = str(project_source_video(project_id))
    edit_plan = base / "edit_plan.json"
    if edit_plan.exists():
        plan = load_project_edit_plan(project_id)
        data["edit_plan_path"] = "edit_plan.json"
        data["edit_plan"] = normalize_edit_plan_source_video(project_id, plan)
    data["has_edit_plan"] = edit_plan.exists()
    transcript_path = base / "transcript" / "transcript.json"
    data["has_transcript"] = transcript_path.exists()
    if transcript_path.exists():
        data["transcript"] = json.loads(transcript_path.read_text(encoding="utf-8"))
    data["has_gemini_proposal"] = (base / "ai" / "gemini_proposal.json").exists()
    data["has_decoration"] = (base / "decoration" / "decoration_project.json").exists()
    preview_files = sorted((base / "preview").glob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True) if (base / "preview").exists() else []
    data["has_preview"] = bool(preview_files)
    if preview_files:
        data["preview_video_url"] = f"/api/projects/{project_id}/media/preview/{preview_files[0].name}"
    data["has_output"] = any((base / "output").glob("final.*")) if (base / "output").exists() else False
    return data


@app.get("/api/projects/{project_id}/progress")
def get_project_progress(project_id: str):
    return project_processing_progress(project_id)


@app.delete("/api/projects/{project_id}")
def delete_project_api(project_id: str):
    delete_project(project_id)
    return {"deleted": True, "project_id": project_id}


@app.patch("/api/projects/{project_id}/rename")
def rename_project_api(project_id: str, req: ProjectRenameRequest):
    project_name = req.project_name.strip()
    if not project_name:
        raise HTTPException(status_code=400, detail="プロジェクト名を入力してください")
    if len(project_name) > 160:
        raise HTTPException(status_code=400, detail="プロジェクト名が長すぎます")
    updated = update_project_info(project_id, {"project_name": project_name})
    return {"project": updated}


@app.post("/api/projects/settings")
def update_project_settings(req: ProjectSettingsRequest):
    updates: dict[str, object] = {}
    current = project_info(req.project_id)
    if req.project_name is not None:
        updates["project_name"] = req.project_name
    ui_state = dict(current.get("ui_state") or {})
    if req.default_emotion_preset_id is not None:
        ui_state["default_emotion_preset_id"] = req.default_emotion_preset_id
    if req.default_subtitle_style_preset_id is not None:
        ui_state["default_subtitle_style_preset_id"] = req.default_subtitle_style_preset_id
    if req.output_profile is not None:
        ui_state["output_profile"] = req.output_profile
    if req.final_output_mode is not None:
        ui_state["final_output_mode"] = req.final_output_mode
    if req.audio_stream_index is not None:
        if req.audio_stream_index < 0:
            raise HTTPException(status_code=400, detail="音声トラックの指定が不正です")
        ui_state["audio_stream_index"] = req.audio_stream_index
    if req.audio_timing is not None:
        ui_state["audio_timing"] = req.audio_timing
    if req.transcription_mode is not None:
        if req.transcription_mode not in {"local", "gemini", "hybrid"}:
            raise HTTPException(status_code=400, detail="字幕作成方式が不正です")
        ui_state["transcription_mode"] = req.transcription_mode
    if req.subtitle_click_playback_mode is not None:
        if req.subtitle_click_playback_mode not in {"jump", "loop"}:
            raise HTTPException(status_code=400, detail="字幕選択時の再生方法が不正です")
        ui_state["subtitle_click_playback_mode"] = req.subtitle_click_playback_mode
    if req.ass_subtitle_defaults is not None:
        ui_state["ass_subtitle_defaults"] = normalize_ass_subtitle_style(req.ass_subtitle_defaults)
    if req.bilingual_subtitle_settings is not None:
        ui_state["bilingual_subtitle_settings"] = normalize_bilingual_settings(req.bilingual_subtitle_settings)
    updates["ui_state"] = ui_state
    updated = update_project_info(req.project_id, updates)
    return {"project": updated}


@app.post("/api/projects/workflow")
def update_project_workflow(req: ProjectWorkflowRequest):
    allowed_steps = {
        "STEP_PROJECT",
        "STEP_TRANSCRIBE",
        "STEP_AI_SUBTITLE",
        "STEP_CUT",
        "STEP_SUBTITLE_EDIT",
        "STEP_DECORATION",
        "STEP_PREVIEW",
        "STEP_EXPORT",
    }
    allowed_statuses = {
        "not_started",
        "current",
        "valid",
        "invalidated",
        "completed",
        "blocked",
        "error",
    }
    raw = req.workflow or {}
    current_step_id = str(raw.get("currentStepId") or "STEP_PROJECT")
    if current_step_id not in allowed_steps:
        raise HTTPException(status_code=400, detail="不正な工程IDです")
    raw_statuses = raw.get("stepStatus") or {}
    if not isinstance(raw_statuses, dict):
        raise HTTPException(status_code=400, detail="工程状態の形式が不正です")
    step_status = {
        step_id: str(status)
        for step_id, status in raw_statuses.items()
        if step_id in allowed_steps and str(status) in allowed_statuses
    }
    execution = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
    workflow = {
        "schemaVersion": "1.2.0",
        "revision": max(0, int(raw.get("revision") or 0)),
        "currentStepId": current_step_id,
        "stepStatus": step_status,
        "execution": {
            "status": str(execution.get("status") or "idle")[:40],
            "snapshot": execution.get("snapshot") if isinstance(execution.get("snapshot"), dict) else None,
        },
        "errors": list(raw.get("errors") or [])[-20:],
    }
    updated = update_project_info(req.project_id, {"workflow": workflow})
    return {"workflow": updated.get("workflow") or workflow}


@app.get("/api/settings/gemini")
def get_gemini_settings():
    return gemini_config_status()


@app.get("/api/settings/app")
def get_app_settings():
    return load_app_settings()


@app.post("/api/settings/app")
def update_app_settings(req: AppSettingsRequest):
    fields = getattr(req, "model_fields_set", getattr(req, "__fields_set__", set()))
    return save_app_settings(
        startup_mode=req.startup_mode,
        last_project_id=req.last_project_id,
        update_last_project="last_project_id" in fields,
        default_output_directory=req.default_output_directory,
        output_create_project_subdirectory=req.output_create_project_subdirectory,
    )


@app.get("/api/settings/gemini/models")
def get_gemini_models(probe: bool = False):
    return gemini_model_status(probe=probe)


@app.post("/api/settings/gemini")
def update_gemini_settings(req: GeminiConfigRequest):
    return save_gemini_config(
        req.api_key,
        req.model,
        req.clear_key,
        req.speaker_labels_enabled,
        req.srt_timing_priority,
    )


@app.get("/api/projects/{project_id}/ai/gemini")
def get_project_gemini_proposal(project_id: str):
    return {"proposal": load_gemini_proposal(project_id)}


@app.get("/api/projects/{project_id}/ai/knowledge-base")
def get_project_knowledge_base(project_id: str):
    return {"knowledge_base": load_project_knowledge_base(project_id)}


@app.get("/api/ai/knowledge-bases")
def get_shared_knowledge_bases():
    return {"databases": list_shared_knowledge_bases()}


@app.post("/api/ai/gemini/research-knowledge")
def api_gemini_research_knowledge(req: GeminiKnowledgeResearchRequest):
    return {"knowledge_base": research_project_knowledge(req.project_id, req.work_title, req.model, req.instructions)}


@app.post("/api/projects/ai/knowledge-base")
def update_project_knowledge_base(req: GeminiKnowledgeSaveRequest):
    return {"knowledge_base": save_project_knowledge_base(req.project_id, req.knowledge_base)}


@app.post("/api/ai/knowledge-bases/register")
def register_shared_knowledge_base(req: GeminiKnowledgeRegisterRequest):
    return {"knowledge_base": register_project_knowledge_as_shared(req.project_id, req.database_name)}


@app.post("/api/projects/ai/knowledge-base/link")
def update_project_knowledge_base_link(req: GeminiKnowledgeLinkRequest):
    return {"knowledge_base": link_project_knowledge_base(req.project_id, req.database_id)}


@app.post("/api/ai/gemini/analyze")
def api_gemini_analyze(req: GeminiAnalyzeRequest):
    return analyze_project_with_gemini(req.project_id, req.model, req.instructions, req.task)


@app.post("/api/ai/gemini/transcribe")
def api_gemini_transcribe(req: GeminiTranscribeRequest):
    return transcribe_project_with_gemini(
        req.project_id,
        req.model,
        req.language,
        req.bilingual_subtitle_settings,
    )


@app.post("/api/ai/gemini/translate-subtitles")
def api_gemini_translate_subtitles(req: GeminiTranslateRequest):
    return translate_project_subtitles(
        req.project_id,
        req.model,
        req.source_language,
        req.target_language,
        req.display_mode,
    )


@app.post("/api/ai/gemini/apply")
def api_gemini_apply(req: GeminiApplyRequest):
    result = apply_gemini_proposal(req.project_id, req.subtitle_edit_ids, req.chapter_ids, req.cut_ids)
    plan = result.get("edit_plan") or {}
    base = require_project(req.project_id)
    write_srt(plan.get("subtitles") or [], base / "subtitles" / "edited.srt")
    plan["scenes"] = build_scene_catalog_from_subtitles(plan.get("subtitles") or [], plan.get("scenes") or [])
    atomic_write_json(base / "edit_plan.json", plan, backup=True)
    update_project_info(req.project_id, {"scenes": plan.get("scenes") or []})
    result["edit_plan"] = plan
    return result


@app.post("/api/projects/scenes")
def update_project_scenes(req: ProjectScenesRequest):
    current = project_info(req.project_id)
    updates = {"scenes": req.scenes}
    updated = update_project_info(req.project_id, updates)
    return {"project": updated}


@app.get("/api/projects/{project_id}/media/{folder}/{filename}")
def get_project_media(project_id: str, folder: str, filename: str):
    if folder not in {"source", "preview", "output", "analysis"}:
        raise HTTPException(status_code=400, detail="不正なmedia folderです")
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="不正なfilenameです")
    path = resolve_project_path(project_id, folder, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    return FileResponse(path)


@app.get("/api/version")
def api_version():
    return version_info()


@app.post("/api/system/select-output-directory")
def api_select_output_directory(req: DirectoryPickerRequest, request: Request):
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise HTTPException(status_code=403, detail="ローカル画面から操作してください")
    selected = choose_output_directory(req.initial_directory)
    return {"directory": selected}


@app.post("/api/system/open-export-directory")
def api_open_export_directory(req: OpenExportDirectoryRequest, request: Request):
    origin = str(request.headers.get("origin") or "")
    if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise HTTPException(status_code=403, detail="ローカル画面から操作してください")
    directory = configured_export_directory(req.project_id, load_app_settings())
    open_directory_in_file_manager(directory)
    return {"directory": str(directory)}


@app.post("/api/browser/heartbeat")
def api_browser_heartbeat():
    global _browser_heartbeat_at, _browser_heartbeat_enabled, _browser_close_requested_at
    _browser_heartbeat_at = time.monotonic()
    _browser_heartbeat_enabled = True
    _browser_close_requested_at = None
    return {"ok": True, "timeout_sec": SERVER_HEARTBEAT_TIMEOUT_SEC}


@app.post("/api/browser/close")
def api_browser_close():
    global _browser_close_requested_at, _browser_heartbeat_enabled
    _browser_close_requested_at = time.monotonic()
    _browser_heartbeat_enabled = True
    return {"ok": True, "close_grace_sec": SERVER_CLOSE_GRACE_SEC}


@app.get("/api/presets")
def api_presets():
    return preset_catalog()


@app.get("/api/system/fonts")
def api_system_fonts(refresh: bool = False):
    if refresh:
        list_system_fonts.cache_clear()
    return {"fonts": list_system_fonts()}


@app.get("/api/projects/{project_id}/decoration")
def get_project_decoration(project_id: str):
    require_project(project_id)
    return {"decoration": load_project_decoration(project_id)}


@app.get("/api/projects/{project_id}/subtitles")
def get_project_subtitles(project_id: str, kind: str = "edited"):
    require_project(project_id)
    return load_project_subtitles(project_id, kind)


@app.post("/api/projects/decoration")
def update_project_decoration(req: ProjectDecorationRequest):
    updated = save_project_decoration(req.project_id, req.decoration)
    return {"decoration": updated}


@app.post("/api/decoration-presets/global")
def update_shared_decoration_presets(req: SharedDecorationPresetsRequest):
    updated = save_shared_decoration_presets(req.decoration)
    return {"decoration_presets": updated}


@app.post("/api/decoration/ass")
def api_decoration_ass(req: ProjectDecorationRequest):
    ass_path = build_decoration_ass(req.project_id, req.decoration)
    return {"ass_path": str(ass_path)}


@app.post("/api/decoration/export-ass-package")
def api_decoration_export_ass_package(req: RenderRequest):
    return export_cut_video_with_decoration_ass(req.project_id, output_profile=req.output_profile)


@app.post("/api/decoration/render")
def api_decoration_render(req: DecorationRenderRequest):
    decoration = load_project_decoration(req.project_id)
    return render_decoration_video(
        req.project_id,
        decoration,
        preview=req.preview,
        max_height=req.max_height,
        fps=req.fps,
        start_sec=req.start_sec,
        duration_sec=req.duration_sec,
    )


@app.post("/api/preview/mpv")
def api_preview_mpv(req: MpvLaunchRequest):
    return launch_mpv(req.project_id, target=req.target, path=req.path, pause=req.pause)


@app.post("/api/video/probe")
def api_probe(req: ProbeRequest):
    return probe_video(req.video_path)


@app.post("/api/audio/extract")
def api_extract_audio(req: ExtractAudioRequest):
    return extract_audio(
        req.project_id,
        req.video_path,
        req.start_sec,
        req.end_sec,
        req.compute_profile,
        req.audio_stream_index,
    )


@app.post("/api/audio/preview-track")
def api_prepare_audio_track_preview(req: AudioTrackPreviewRequest):
    return prepare_audio_track_preview(req.project_id, req.audio_stream_index)


@app.post("/api/transcribe")
def api_transcribe(req: TranscribeRequest):
    try:
        return transcribe_audio(
            req.project_id,
            req.audio_path,
            req.language,
            req.model,
            req.compute_profile,
            req.engine,
            req.silence_threshold_db,
            detection_mode=req.detection_mode,
            voice_isolation_enabled=req.voice_isolation_enabled,
            use_isolated_voice_for_vad=req.use_isolated_voice_for_vad,
            use_isolated_voice_for_whisper=req.use_isolated_voice_for_whisper,
            vad_threshold=req.vad_threshold,
            vad_min_speech_duration_ms=req.vad_min_speech_duration_ms,
            vad_min_silence_duration_ms=req.vad_min_silence_duration_ms,
            vad_speech_pad_ms=req.vad_speech_pad_ms,
            pre_margin_sec=req.pre_margin_sec,
            post_margin_sec=req.post_margin_sec,
            min_speech_duration_sec=req.min_speech_duration_sec,
            merge_silence_gap_sec=req.merge_silence_gap_sec,
            align_timestamps=req.align_timestamps,
            use_whisperx_alignment=req.use_whisperx_alignment,
        )
    except Exception as exc:
        finish_transcription_progress(req.project_id, success=False, error=str(exc))
        raise


@app.post("/api/transcribe/range")
def api_transcribe_range(req: RangeTranscribeRequest):
    return transcribe_audio_range(
        req.project_id,
        req.start_sec,
        req.end_sec,
        req.subtitles,
        language=req.language,
        model=req.model,
        compute_profile=req.compute_profile,
        engine=req.engine,
        replacement_mode=req.replacement_mode,
        analysis_padding_sec=req.analysis_padding_sec,
        detection_mode=req.detection_mode,
        voice_isolation_enabled=req.voice_isolation_enabled,
        use_isolated_voice_for_vad=req.use_isolated_voice_for_vad,
        use_isolated_voice_for_whisper=req.use_isolated_voice_for_whisper,
        vad_threshold=req.vad_threshold,
        vad_min_speech_duration_ms=req.vad_min_speech_duration_ms,
        vad_min_silence_duration_ms=req.vad_min_silence_duration_ms,
        vad_speech_pad_ms=req.vad_speech_pad_ms,
        pre_margin_sec=req.pre_margin_sec,
        post_margin_sec=req.post_margin_sec,
        min_speech_duration_sec=req.min_speech_duration_sec,
        merge_silence_gap_sec=req.merge_silence_gap_sec,
        align_timestamps=req.align_timestamps,
    )


@app.post("/api/silence/detect")
def api_detect_silence(req: SilenceRequest):
    return detect_silence(req.project_id, req.audio_path, req.threshold_db, req.min_silence_duration, req.compute_profile)


@app.post("/api/vad/detect")
def api_detect_vad(req: VadRequest):
    return detect_vad_speech_intervals(
        req.project_id,
        req.audio_path,
        compute_profile=req.compute_profile,
        vad_threshold=req.vad_threshold,
        min_speech_duration_sec=req.min_speech_duration_sec,
        min_silence_duration_sec=req.min_silence_duration_sec,
        speech_pad_sec=req.speech_pad_sec,
        merge_silence_gap_sec=req.merge_silence_gap_sec,
    )


@app.post("/api/edit-plan/create")
def api_create_edit_plan(req: EditPlanRequest):
    base = require_project(req.project_id)
    source_video = project_info(req.project_id).get("source_video")
    if not source_video:
        raise HTTPException(status_code=404, detail="元動画が見つかりません")
    plan = build_edit_plan(source_video, req.source_range, req.silences, req.transcript, req.settings)
    plan = normalize_edit_plan_source_video(req.project_id, plan)
    path = base / "edit_plan.json"
    atomic_write_json(path, plan, backup=True)
    write_srt(plan.get("subtitles", []), base / "subtitles" / "edited.srt")
    return {"edit_plan_path": str(path), "edit_plan": plan}


@app.post("/api/edit-plan/update")
def api_update_edit_plan(req: EditPlanUpdateRequest):
    base = require_project(req.project_id)
    plan = normalize_edit_plan_source_video(req.project_id, req.edit_plan or {})
    path = base / "edit_plan.json"
    atomic_write_json(path, plan, backup=True)
    write_srt(plan.get("subtitles", []), base / "subtitles" / "edited.srt")
    update_project_info(req.project_id, {"scenes": plan.get("scenes", [])})
    return {"edit_plan_path": str(path), "edit_plan": plan}


@app.post("/api/subtitles/update")
def api_update_subtitles(req: SubtitleUpdateRequest):
    path = resolve_project_path(req.project_id, "edit_plan.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail="edit_plan.jsonが見つかりません")
    plan = load_project_edit_plan(req.project_id)
    plan["subtitles"] = req.subtitles
    plan["scenes"] = build_scene_catalog_from_subtitles(req.subtitles, plan.get("scenes") or [])
    if req.speaker_roster is not None:
        plan["speaker_roster"] = req.speaker_roster
    else:
        plan["speaker_roster"] = build_speaker_roster(req.subtitles)
    atomic_write_json(path, plan, backup=True)
    srt_path = resolve_project_path(req.project_id, "subtitles", "edited.srt")
    write_srt(req.subtitles, srt_path)
    update_project_info(req.project_id, {"scenes": plan.get("scenes", [])})
    return {"srt_path": str(srt_path), "edit_plan": plan}


@app.post("/api/transcript/update")
def api_update_transcript(req: TranscriptUpdateRequest):
    path = resolve_project_path(req.project_id, "transcript", "transcript.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail="transcript.jsonが見つかりません")
    transcript = json.loads(path.read_text(encoding="utf-8"))
    transcript["subtitles"] = req.subtitles
    transcript["raw_subtitles"] = transcript.get("raw_subtitles", req.subtitles)
    transcript["aligned_subtitles"] = transcript.get("aligned_subtitles", req.subtitles)
    transcript["scenes"] = build_scene_catalog_from_subtitles(req.subtitles, transcript.get("scenes") or [])
    if req.speaker_roster is not None:
        transcript["speaker_roster"] = req.speaker_roster
    else:
        transcript["speaker_roster"] = build_speaker_roster(req.subtitles)
    atomic_write_json(path, transcript, backup=True)
    srt_path = resolve_project_path(req.project_id, "subtitles", "edited.srt")
    write_srt(req.subtitles, srt_path)
    update_project_info(req.project_id, {"scenes": transcript.get("scenes", [])})
    return {"transcript_path": str(path), "srt_path": str(srt_path), "transcript": transcript}


@app.post("/api/transcript/skip")
def api_skip_transcript(req: TranscriptSkipRequest):
    base = require_project(req.project_id)
    transcript = {
        "engine": "none",
        "status": "skipped",
        "subtitle_mode": "none",
        "created_at": time.time(),
        "subtitles": [],
        "raw_subtitles": [],
        "aligned_subtitles": [],
        "segments": [],
        "scenes": [],
        "speaker_roster": [],
    }
    transcript_path = resolve_project_path(req.project_id, "transcript", "transcript.json")
    atomic_write_json(transcript_path, transcript, backup=True)
    for filename in ("original.srt", "edited.srt"):
        write_srt([], resolve_project_path(req.project_id, "subtitles", filename))

    edit_plan_path = base / "edit_plan.json"
    edit_plan = None
    if edit_plan_path.exists():
        edit_plan = load_project_edit_plan(req.project_id)
        edit_plan["subtitles"] = []
        edit_plan["speaker_roster"] = []
        atomic_write_json(edit_plan_path, edit_plan, backup=True)

    update_project_info(req.project_id, {"scenes": []})
    audit_event("transcription.skipped", project_id=req.project_id)
    return {
        "transcript_path": str(transcript_path),
        "srt_path": str(resolve_project_path(req.project_id, "subtitles", "original.srt")),
        "transcript": transcript,
        "edit_plan": edit_plan,
    }


@app.post("/api/preview/render")
def api_preview(req: RenderRequest):
    return render_from_plan(req.project_id, preview=True, output_profile=req.output_profile)


@app.post("/api/preview/manual-cuts")
def api_preview_manual_cuts(req: DraftRenderRequest):
    base = require_project(req.project_id)
    source_video = project_info(req.project_id).get("source_video")
    if not source_video:
        raise HTTPException(status_code=404, detail="元動画が見つかりません")
    plan = build_edit_plan(source_video, req.source_range, req.silences, req.transcript, req.settings)
    plan = normalize_edit_plan_source_video(req.project_id, plan)
    return render_from_plan_data(req.project_id, plan, preview=True, burn_subtitles=req.burn_subtitles, output_profile=req.output_profile)


@app.post("/api/export/final")
def api_export(req: RenderRequest):
    result = render_from_plan(
        req.project_id,
        preview=False,
        burn_subtitles=req.burn_subtitles,
        subtitle_mode=req.subtitle_mode,
        subtitle_format=req.subtitle_format,
        output_profile=req.output_profile,
    )
    if req.destination_mode == "project":
        return result
    if req.destination_mode == "custom":
        if not str(req.output_directory or "").strip():
            raise HTTPException(status_code=400, detail="出力先フォルダを指定してください")
        if not str(req.output_filename or "").strip():
            raise HTTPException(status_code=400, detail="出力ファイル名を指定してください")
        return publish_export_result(
            req.project_id,
            result,
            req.output_directory or "",
            req.output_filename,
            create_project_subdirectory=False,
        )
    if req.destination_mode == "configured":
        info = project_info(req.project_id)
        app_settings = load_app_settings()
        configured_directory = str(app_settings.get("default_output_directory") or "").strip()
        if not configured_directory:
            return result
        return publish_export_result(
            req.project_id,
            result,
            configured_directory,
            str(info.get("project_name") or req.project_id),
            create_project_subdirectory=bool(app_settings.get("output_create_project_subdirectory", True)),
        )
    raise HTTPException(status_code=400, detail="出力先の指定方法が不正です")


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

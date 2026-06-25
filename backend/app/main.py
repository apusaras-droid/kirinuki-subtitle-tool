from __future__ import annotations

import json
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
    preset_catalog,
    build_scene_catalog_from_subtitles,
    transcribe_audio,
    render_decoration_video,
    build_decoration_ass,
    save_project_decoration,
    update_project_info,
)
from .srt import write_srt

app = FastAPI(title="切り抜き字幕作成ツール MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
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
    return response


class ProbeRequest(BaseModel):
    video_path: str


class ExtractAudioRequest(BaseModel):
    project_id: str
    video_path: str
    start_sec: float
    end_sec: float
    compute_profile: str = "auto"


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
    vad_threshold: float = 0.25
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


class SubtitleUpdateRequest(BaseModel):
    project_id: str
    subtitles: list[dict[str, Any]]
    speaker_roster: list[dict[str, Any]] | None = None


class TranscriptUpdateRequest(BaseModel):
    project_id: str
    subtitles: list[dict[str, Any]]
    speaker_roster: list[dict[str, Any]] | None = None


class RenderRequest(BaseModel):
    project_id: str
    quality: str = "low"
    burn_subtitles: bool = False


class DraftRenderRequest(BaseModel):
    project_id: str
    source_range: dict[str, float]
    silences: list[dict[str, float]] = []
    transcript: dict[str, Any] = {}
    settings: dict[str, Any] = {}
    quality: str = "low"
    burn_subtitles: bool = False


class ProjectSettingsRequest(BaseModel):
    project_id: str
    default_emotion_preset_id: str | None = None
    default_subtitle_style_preset_id: str | None = None


class ProjectScenesRequest(BaseModel):
    project_id: str
    scenes: list[dict[str, Any]]


class ProjectDecorationRequest(BaseModel):
    project_id: str
    decoration: dict[str, Any]


class DecorationRenderRequest(BaseModel):
    project_id: str
    preview: bool = True


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), project_name: str | None = Form(default=None)):
    return await create_project_from_upload(file, project_name)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    base = require_project(project_id)
    project_path = base / "project.json"
    data = json.loads(project_path.read_text(encoding="utf-8")) if project_path.exists() else {"project_id": project_id}
    edit_plan = base / "edit_plan.json"
    if edit_plan.exists():
        plan = load_project_edit_plan(project_id)
        data["edit_plan_path"] = "edit_plan.json"
        data["edit_plan"] = normalize_edit_plan_source_video(project_id, plan)
    return data


@app.post("/api/projects/settings")
def update_project_settings(req: ProjectSettingsRequest):
    updates: dict[str, object] = {}
    current = project_info(req.project_id)
    ui_state = dict(current.get("ui_state") or {})
    if req.default_emotion_preset_id is not None:
        ui_state["default_emotion_preset_id"] = req.default_emotion_preset_id
    if req.default_subtitle_style_preset_id is not None:
        ui_state["default_subtitle_style_preset_id"] = req.default_subtitle_style_preset_id
    updates["ui_state"] = ui_state
    updated = update_project_info(req.project_id, updates)
    return {"project": updated}


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


@app.get("/api/presets")
def api_presets():
    return preset_catalog()


@app.get("/api/projects/{project_id}/decoration")
def get_project_decoration(project_id: str):
    require_project(project_id)
    return {"decoration": load_project_decoration(project_id)}


@app.post("/api/projects/decoration")
def update_project_decoration(req: ProjectDecorationRequest):
    updated = save_project_decoration(req.project_id, req.decoration)
    return {"decoration": updated}


@app.post("/api/decoration/ass")
def api_decoration_ass(req: ProjectDecorationRequest):
    ass_path = build_decoration_ass(req.project_id, req.decoration)
    return {"ass_path": str(ass_path)}


@app.post("/api/decoration/render")
def api_decoration_render(req: DecorationRenderRequest):
    decoration = load_project_decoration(req.project_id)
    return render_decoration_video(req.project_id, decoration, preview=req.preview)


@app.post("/api/video/probe")
def api_probe(req: ProbeRequest):
    return probe_video(req.video_path)


@app.post("/api/audio/extract")
def api_extract_audio(req: ExtractAudioRequest):
    return extract_audio(req.project_id, req.video_path, req.start_sec, req.end_sec, req.compute_profile)


@app.post("/api/transcribe")
def api_transcribe(req: TranscribeRequest):
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


@app.post("/api/preview/render")
def api_preview(req: RenderRequest):
    return render_from_plan(req.project_id, preview=True)


@app.post("/api/preview/manual-cuts")
def api_preview_manual_cuts(req: DraftRenderRequest):
    base = require_project(req.project_id)
    source_video = project_info(req.project_id).get("source_video")
    if not source_video:
        raise HTTPException(status_code=404, detail="元動画が見つかりません")
    plan = build_edit_plan(source_video, req.source_range, req.silences, req.transcript, req.settings)
    plan = normalize_edit_plan_source_video(req.project_id, plan)
    return render_from_plan_data(req.project_id, plan, preview=True, burn_subtitles=req.burn_subtitles)


@app.post("/api/export/final")
def api_export(req: RenderRequest):
    return render_from_plan(req.project_id, preview=False, burn_subtitles=req.burn_subtitles)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

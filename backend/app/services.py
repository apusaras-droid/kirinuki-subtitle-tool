from __future__ import annotations

import json
import audioop
import math
import os
import re
import shutil
import subprocess
import sys
import wave
import uuid
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, UploadFile

from .audit import audit_event, audit_project_detail_event, audit_project_event
from .srt import normalize_subtitle_durations, parse_srt, subtitles_from_whisper, write_srt
from .timecode import format_srt_time

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "projects"
FRONTEND_DIR = ROOT / "frontend"
WHISPER_CPP_DIR = ROOT / "tools" / "whisper.cpp"
WHISPER_CPP_EXE = WHISPER_CPP_DIR / "bin" / "whisper-cli.exe"
WHISPER_CPP_MODELS = WHISPER_CPP_DIR / "models"
WHISPER_CPP_VAD_MODEL = WHISPER_CPP_MODELS / "ggml-silero-v5.1.2.bin"
DOCS_DIR = ROOT / "docs"
EMOTION_PRESETS_SAMPLE = DOCS_DIR / "emotion_presets.sample.json"
SUBTITLE_STYLE_PRESETS_SAMPLE = DOCS_DIR / "subtitle_style_presets.sample.json"
SCENES_SAMPLE = DOCS_DIR / "scenes.sample.json"
DECORATION_PRESETS_SAMPLE = DOCS_DIR / "decoration_presets.sample.json"
WAVEFORM_MAX_POINTS = 1800
MAX_HISTORY_VERSIONS = 12


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(text, encoding=encoding)
    last_error: PermissionError | None = None
    for attempt in range(5):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        failed_path = path.with_name(path.name + f".failed-{int(time.time() * 1000)}")
        try:
            if temp_path.exists():
                os.replace(temp_path, failed_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"ファイル更新中にロック競合が発生しました: {path}") from last_error


def _backup_existing_file(path: Path) -> None:
    if not path.exists():
        return
    history_dir = path.parent / f".{path.name}.history"
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = history_dir / f"{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    backups = sorted(history_dir.glob(f"*{path.suffix}"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in backups[MAX_HISTORY_VERSIONS:]:
        try:
            stale.unlink()
        except Exception:
            pass


def atomic_write_json(path: Path, data: dict | list, *, indent: int = 2, backup: bool = False) -> None:
    if backup:
        _backup_existing_file(path)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent))


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise HTTPException(status_code=500, detail=f"{name} が見つかりません。PATHに追加してください。")


def run_command(args: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path:
        proc = subprocess.run(args, text=True, capture_output=True, encoding="utf-8", errors="replace", cwd=ROOT)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=(proc.stderr or proc.stdout or "外部コマンドに失敗しました").strip())
        return proc

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write("COMMAND\n" + " ".join(args) + "\n\nSTREAM\n")
        log_file.flush()
        proc = subprocess.Popen(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )
        output_parts: list[str] = []
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.readline()
            if chunk:
                output_parts.append(chunk)
                log_file.write(chunk)
                log_file.flush()
                continue
            if proc.poll() is not None:
                break
        remaining = proc.stdout.read() or ""
        if remaining:
            output_parts.append(remaining)
            log_file.write(remaining)
            log_file.flush()
        proc.wait()
        combined = "".join(output_parts)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=(combined or "外部コマンドに失敗しました").strip())
        return subprocess.CompletedProcess(args=args, returncode=proc.returncode or 0, stdout="", stderr=combined)


def whisper_cpp_oom_message(engine: str, model: str) -> str:
    return (
        f"{engine} の GPU 実行でメモリ確保に失敗しました。"
        f" model={model}。"
        " GPUではこのモデルが重すぎるか、VRAM断片化の可能性があります。"
        " モデルを small / base に下げるか、CPUプロファイルに切り替えてください。"
    )


def raise_if_whisper_cpp_oom(error: HTTPException, engine: str, model: str) -> None:
    detail = str(error.detail or "")
    if "ErrorOutOfDeviceMemory" in detail or "GGML_ASSERT(buffer) failed" in detail or "failed to allocate Vulkan0 buffer" in detail:
        raise HTTPException(status_code=500, detail=whisper_cpp_oom_message(engine, model)) from error
    raise error


def path_for_cli(path: Path | str) -> str:
    resolved = Path(path).resolve()
    try:
        return os.path.relpath(resolved, ROOT)
    except ValueError:
        return str(resolved)


def ffmpeg_subtitles_filter(path: Path | str) -> str:
    escaped = path_for_cli(path).replace("\\", "/")
    for token, replacement in ((":", r"\:"), ("'", r"\'"), ("[", r"\["), ("]", r"\]"), (",", r"\,"), ("=", r"\=")):
        escaped = escaped.replace(token, replacement)
    return f"subtitles=filename='{escaped}'"


def ffmpeg_subtitles_filter_with_style(path: Path | str, settings: dict | None = None) -> str:
    filter_expr = ffmpeg_subtitles_filter(path)
    style = settings or {}
    font_name = str(style.get("subtitle_font_name", "Meiryo")).strip() or "Meiryo"
    font_size = int(float(style.get("subtitle_font_size", 42) or 42))
    outline_width = max(0, int(float(style.get("subtitle_outline_width", 2) or 2)))
    force_style = f"FontName={font_name},FontSize={font_size},Outline={outline_width},BorderStyle=3,OutlineColour=&H000000&,Shadow=0"
    escaped_force_style = force_style.replace("'", r"\'")
    return f"{filter_expr}:force_style='{escaped_force_style}'"


def ass_timecode(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000.0)))
    h = total_ms // 3600000
    m = (total_ms % 3600000) // 60000
    s = (total_ms % 60000) // 1000
    cs = (total_ms % 1000) // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def sanitize_ass_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\\", r"\\")
    value = value.replace("{", "(").replace("}", ")")
    value = value.replace("\n", r"\N")
    return value.strip()


def ass_color(hex_color: str) -> str:
    value = str(hex_color or "#ffffff").strip().lstrip("#")
    if len(value) != 6:
        value = "ffffff"
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    return f"&H00{bb}{gg}{rr}&"


def effect_tags(effect_group: dict | None = None, emotion: str | None = None) -> str:
    effects = [str(effect).strip() for effect in (effect_group or {}).get("effects", []) if str(effect).strip()]
    tags: list[str] = []
    if "bubble_round" in effects:
        tags.append(r"\bord4\shad1")
    if "bubble_soft" in effects:
        tags.append(r"\bord3\shad0\blur1")
    if "sparkle" in effects:
        tags.append(r"\fs1")
    if "pop_in" in effects:
        tags.append(r"\fscx115\fscy115\t(0,120,\fscx100\fscy100)")
    if "shake" in effects:
        tags.append(r"\t(0,60,\frz2)\t(60,120,\frz-2)")
    if "float_in" in effects:
        tags.append(r"\move(0,0,0,0)")
    if "heart" in effects:
        tags.append(r"\c&HCC66FF&")
    if emotion == "surprise":
        tags.append(r"\fad(60,120)\c&H00D8FF&")
    elif emotion == "joy":
        tags.append(r"\fad(40,80)\c&H55FFAA&")
    elif emotion == "sadness":
        tags.append(r"\fad(80,140)\c&HFFAA88&")
    elif emotion == "anger":
        tags.append(r"\fad(30,70)\c&H6666FF&")
    elif emotion == "teasing":
        tags.append(r"\fad(35,75)\c&HFF66E6&")
    return "".join(tags)


def resolve_emotion_preset(emotion: str | None, presets: list[dict] | None = None) -> dict:
    target = str(emotion or "neutral").strip().lower()
    for preset in presets or load_emotion_presets():
        if str(preset.get("emotion") or preset.get("id") or "").strip().lower() == target:
            return dict(preset)
    return {
        "id": "emotion_neutral",
        "name": "通常",
        "emotion": "neutral",
        "effect_group_id": "",
        "subtitle_style_preset_id": "subtitle_standard",
    }


def build_decoration_ass(project_id: str, decoration: dict, output_path: Path | None = None) -> Path:
    base = require_project(project_id)
    source_srt = decoration.get("source_srt") or str(resolve_project_path(project_id, "subtitles", "edited.srt"))
    source_path = Path(source_srt)
    if not source_path.is_absolute():
        source_path = base / source_path
    if not source_path.exists():
        fallback = resolve_project_path(project_id, "subtitles", "edited.srt")
        if fallback.exists():
            source_path = fallback
        else:
            fallback = resolve_project_path(project_id, "subtitles", "original.srt")
            if fallback.exists():
                source_path = fallback
            else:
                raise HTTPException(status_code=404, detail="字幕ファイルが見つかりません")
    subtitles = json.loads(source_path.read_text(encoding="utf-8")) if source_path.suffix.lower() == ".json" else None
    if subtitles is None:
        from .srt import parse_srt

        subtitles = parse_srt(source_path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(subtitles, dict):
        subtitles = subtitles.get("subtitles", [])
    subtitles = [item for item in subtitles or [] if item.get("enabled", True)]
    font_presets = {item.get("id"): item for item in (decoration.get("font_presets") or load_decoration_presets().get("font_presets", []))}
    effect_groups = {item.get("id"): item for item in (decoration.get("effect_groups") or load_decoration_presets().get("effect_groups", []))}
    layout_presets = {item.get("id"): item for item in (decoration.get("layout_presets") or load_decoration_presets().get("layout_presets", []))}
    emotion_presets = load_emotion_presets()
    default_font = next(iter(font_presets.values()), {"family": "Yu Gothic", "size": 44, "color": "#ffffff", "outline_color": "#000000", "outline_width": 4})
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1280",
        "PlayResY: 720",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
    ]
    style_name = "DecorDefault"
    ass_lines.append(
        "Style: "
        + ",".join(
            [
                style_name,
                str(default_font.get("family", "Yu Gothic")),
                str(int(float(default_font.get("size", 44) or 44))),
                ass_color(default_font.get("color", "#ffffff")),
                ass_color(default_font.get("color", "#ffffff")),
                ass_color(default_font.get("outline_color", "#000000")),
                ass_color("#000000"),
                "0",
                "0",
                "0",
                "0",
                "100",
                "100",
                "0",
                "0",
                "3",
                str(max(0, int(float(default_font.get("outline_width", 4) or 4)))),
                str(max(0, int(float(default_font.get("shadow_depth", 4) or 4)))),
                "2",
                "60",
                "60",
                "60",
                "1",
            ]
        )
    )
    ass_lines += [
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    default_layout = next(iter(layout_presets.values()), {"anchor": "bottom_center"})
    for item in subtitles:
        start = float(item.get("start_sec", item.get("output_start_sec", 0.0)) or 0.0)
        end = float(item.get("end_sec", item.get("output_end_sec", start + 1.0)) or (start + 1.0))
        emotion_preset = next(
            (
                preset
                for preset in emotion_presets
                if str(preset.get("id", "")).strip() == str(item.get("emotion_preset_id", "")).strip()
            ),
            resolve_emotion_preset(item.get("emotion"), emotion_presets),
        )
        font = font_presets.get(item.get("font_preset_id")) or font_presets.get(emotion_preset.get("font_preset_id")) or default_font
        effect_group = effect_groups.get(item.get("effect_group_id")) or effect_groups.get(emotion_preset.get("effect_group_id"))
        layout = layout_presets.get(item.get("layout_preset_id")) or default_layout
        font_size = int(float(font.get("size", 44) or 44))
        outline = max(0, int(float(font.get("outline_width", 4) or 4)))
        shadow = max(0, int(float(font.get("shadow_depth", 4) or 4)))
        primary = ass_color(font.get("color", "#ffffff"))
        outline_color = ass_color(font.get("outline_color", "#000000"))
        anchor = str(layout.get("anchor", "bottom_center"))
        alignment = "2" if anchor == "bottom_center" else "8" if anchor == "top_center" else "5"
        tags = [f"\\fs{font_size}", f"\\1c{primary}", f"\\3c{outline_color}", f"\\bord{outline}", f"\\shad{shadow}"]
        tags.append(effect_tags(effect_group, item.get("emotion")))
        if str(item.get("speaker_label") or "").strip():
            text = f"{item.get('speaker_label')}: {sanitize_ass_text(item.get('text', ''))}"
        else:
            text = sanitize_ass_text(item.get("text", ""))
        ass_lines.append(
            f"Dialogue: 0,{ass_timecode(start)},{ass_timecode(end)},"
            f"{style_name},,0,0,0,,{{{''.join(tags)}}}{text}"
        )
    ass_text = "\n".join(ass_lines) + "\n"
    ass_path = output_path or (base / "decoration" / "decorated.ass")
    atomic_write_text(ass_path, ass_text, encoding="utf-8")
    return ass_path


def render_decoration_video(project_id: str, decoration: dict, preview: bool = True) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    ass_path = build_decoration_ass(project_id, decoration, base / "decoration" / "decorated.ass")
    source_video = project_source_video(project_id)
    out_dir = base / ("preview" if preview else "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / ("decorated_preview.mp4" if preview else "decorated_final.mp4")
    log_path = base / "temp" / "logs" / ("decoration_preview.log" if preview else "decoration_final.log")
    run_command(
        [
            "ffmpeg",
            "-y",
            *ffmpeg_cfr_args(),
            "-i",
            str(source_video),
            "-vf",
            f"ass={path_for_cli(ass_path).replace('\\\\', '/')}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20" if preview else "18",
            "-c:a",
            "copy",
            str(output_path),
        ],
        log_path,
    )
    audit_project_event(project_id, "decoration.render", context={"preview": preview, "ass_path": str(ass_path), "output_path": str(output_path)})
    return {
        "ass_path": str(ass_path),
        "video_path": str(output_path),
        "video_url": f"/api/projects/{project_id}/media/{'preview' if preview else 'output'}/{output_path.name}",
    }


def ffmpeg_cfr_args() -> list[str]:
    try:
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-version"], text=True, capture_output=True, encoding="utf-8", errors="replace", cwd=ROOT)
    except Exception:
        return ["-fps_mode", "cfr"]
    text = (proc.stdout or proc.stderr or "").splitlines()
    version_line = next((line for line in text if line.lower().startswith("ffmpeg version")), "")
    match = re.search(r"ffmpeg version\s+(\d+)\.(\d+)", version_line, re.IGNORECASE)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        if major > 5 or (major == 5 and minor >= 1):
            return ["-fps_mode", "cfr"]
    return ["-vsync", "cfr"]


def safe_project_id(project_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise HTTPException(status_code=400, detail="不正なproject_idです")
    return project_id


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / safe_project_id(project_id)


def require_project(project_id: str) -> Path:
    path = project_dir(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
    return path


def project_info(project_id: str) -> dict:
    base = require_project(project_id)
    info_path = base / "project.json"
    if not info_path.exists():
        raise HTTPException(status_code=404, detail="project.jsonが見つかりません")
    return json.loads(info_path.read_text(encoding="utf-8"))


def update_project_info(project_id: str, updates: dict) -> dict:
    base = require_project(project_id)
    info_path = base / "project.json"
    if not info_path.exists():
        raise HTTPException(status_code=404, detail="project.jsonが見つかりません")
    current = json.loads(info_path.read_text(encoding="utf-8"))
    current.update(updates or {})
    atomic_write_json(info_path, current, backup=True)
    return current


def _safe_within_project(project_id: str, path: Path) -> bool:
    base = require_project(project_id).resolve()
    try:
        path.resolve().relative_to(base)
        return True
    except Exception:
        return False


def cleanup_project_artifacts(
    project_id: str,
    *,
    keep_audio: bool = False,
    keep_preview: bool = False,
    keep_analysis: bool = False,
    keep_raw_subtitles: bool = False,
) -> dict:
    base = require_project(project_id).resolve()
    removed: list[str] = []
    targets: list[Path] = []

    def add_target(rel_path: str) -> None:
        candidate = (base / rel_path).resolve()
        if _safe_within_project(project_id, candidate):
            targets.append(candidate)

    if not keep_audio:
        add_target("audio/source_range.wav")
    if not keep_preview:
        add_target("preview")
    if not keep_analysis:
        add_target("analysis")
        add_target("temp/segments")
    if not keep_raw_subtitles:
        add_target("subtitles/original.srt")
        add_target("subtitles/whisperx_aligned.srt")
        add_target("subtitles/aligned.srt")

    for target in targets:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(str(target.relative_to(base)))
        elif target.exists():
            target.unlink()
            removed.append(str(target.relative_to(base)))

    return {
        "project_id": project_id,
        "removed": removed,
        "keep_audio": keep_audio,
        "keep_preview": keep_preview,
        "keep_analysis": keep_analysis,
        "keep_raw_subtitles": keep_raw_subtitles,
    }


def project_source_video(project_id: str) -> Path:
    base = require_project(project_id).resolve()
    info = project_info(project_id)
    source = Path(info.get("source_video", ""))
    resolved = source if source.is_absolute() else (base / source)
    resolved = resolved.resolve()
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="元動画が見つかりません")
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="元動画がプロジェクト外です") from exc
    return resolved


def resolve_project_path(project_id: str, *parts: str) -> Path:
    base = require_project(project_id).resolve()
    target = base.joinpath(*parts).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="プロジェクト外のパスは参照できません") from exc
    return target


def normalize_compute_profile(compute_profile: str) -> str:
    normalized = (compute_profile or "auto").strip().lower()
    if normalized not in {"auto", "cpu", "gpu"}:
        raise HTTPException(status_code=400, detail="compute_profile は auto / cpu / gpu を指定してください")
    return normalized


def infer_whisper_cpp_device(stderr_text: str) -> str:
    text = stderr_text.lower()
    if "use gpu    = 0" in text or "use gpu = 0" in text:
        return "cpu"
    if "using vulkan" in text or "ggml_vulkan" in text or "vulkan0 backend" in text:
        return "vulkan"
    if "whisper_backend_init_cpu" in text or "using cpu" in text:
        return "cpu"
    return "unknown"


def load_project_edit_plan(project_id: str) -> dict:
    path = resolve_project_path(project_id, "edit_plan.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail="edit_plan.jsonが見つかりません")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_file(path: Path, fallback: list[dict] | dict) -> list[dict] | dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return fallback


def load_emotion_presets() -> list[dict]:
    fallback = [
        {
            "id": "emotion_neutral",
            "name": "通常",
            "emotion": "neutral",
            "target_scope": "scene",
            "effect_group_id": "",
            "subtitle_style_preset_id": "subtitle_standard",
            "font_preset_id": "font_standard",
            "description": "標準字幕",
        },
        {
            "id": "emotion_joy_default",
            "name": "喜び",
            "emotion": "joy",
            "target_scope": "scene",
            "effect_group_id": "effect_group_manga_pop",
            "subtitle_style_preset_id": "subtitle_emotion_joy",
            "font_preset_id": "font_pop",
            "description": "明るい色と弾む演出",
        },
        {
            "id": "emotion_anger_default",
            "name": "怒り",
            "emotion": "anger",
            "target_scope": "scene",
            "effect_group_id": "effect_group_manga_pop",
            "subtitle_style_preset_id": "subtitle_emotion_anger",
            "font_preset_id": "font_pop",
            "description": "赤寄りの強い演出",
        },
        {
            "id": "emotion_sadness_default",
            "name": "哀しみ",
            "emotion": "sadness",
            "target_scope": "scene",
            "effect_group_id": "effect_group_yume_kawaii",
            "subtitle_style_preset_id": "subtitle_emotion_sadness",
            "font_preset_id": "font_standard",
            "description": "落ち着いた見た目",
        },
        {
            "id": "emotion_surprise_default",
            "name": "驚き",
            "emotion": "surprise",
            "target_scope": "scene",
            "effect_group_id": "effect_group_manga_pop",
            "subtitle_style_preset_id": "subtitle_emotion_surprise",
            "font_preset_id": "font_pop",
            "description": "驚きシーンの既定字幕",
        },
    ]
    data = _load_json_file(EMOTION_PRESETS_SAMPLE, fallback)
    return data if isinstance(data, list) else fallback


def load_subtitle_style_presets() -> list[dict]:
    fallback = [
        {
            "id": "subtitle_standard",
            "name": "標準",
            "font_name": "Meiryo",
            "font_size": 42,
            "font_weight": "bold",
            "text_color": "#FFFFFF",
            "outline_color": "#000000",
            "outline_width": 3,
            "bubble_style": "speech",
            "bubble_fill_color": "#222222",
            "bubble_outline_color": "#FFFFFF",
            "bubble_outline_width": 2,
            "shadow_enabled": True,
            "shadow_color": "#000000",
            "shadow_blur": 4,
        },
        {
            "id": "subtitle_emotion_surprise",
            "name": "驚き",
            "font_name": "Meiryo",
            "font_size": 48,
            "font_weight": "heavy",
            "text_color": "#FFFFFF",
            "outline_color": "#000000",
            "outline_width": 4,
            "bubble_style": "burst",
            "bubble_fill_color": "#1E90FF",
            "bubble_outline_color": "#FFFFFF",
            "bubble_outline_width": 3,
            "shadow_enabled": True,
            "shadow_color": "#000000",
            "shadow_blur": 5,
        },
        {
            "id": "subtitle_emotion_joy",
            "name": "喜び",
            "font_name": "Yu Gothic",
            "font_size": 50,
            "font_weight": "bold",
            "text_color": "#FFF06A",
            "outline_color": "#FFFFFF",
            "outline_width": 4,
            "bubble_style": "speech",
            "bubble_fill_color": "#FFFFFF",
            "bubble_outline_color": "#55FFAA",
            "bubble_outline_width": 3,
            "shadow_enabled": True,
            "shadow_color": "#004422",
            "shadow_blur": 4,
        },
        {
            "id": "subtitle_emotion_anger",
            "name": "怒り",
            "font_name": "Yu Gothic",
            "font_size": 52,
            "font_weight": "heavy",
            "text_color": "#FF7A7A",
            "outline_color": "#FFFFFF",
            "outline_width": 5,
            "bubble_style": "burst",
            "bubble_fill_color": "#25000A",
            "bubble_outline_color": "#FF5A5A",
            "bubble_outline_width": 4,
            "shadow_enabled": True,
            "shadow_color": "#330000",
            "shadow_blur": 5,
        },
        {
            "id": "subtitle_emotion_sadness",
            "name": "哀しみ",
            "font_name": "Yu Gothic",
            "font_size": 46,
            "font_weight": "regular",
            "text_color": "#A7D7FF",
            "outline_color": "#FFFFFF",
            "outline_width": 4,
            "bubble_style": "soft",
            "bubble_fill_color": "#D9F0FF",
            "bubble_outline_color": "#A7D7FF",
            "bubble_outline_width": 3,
            "shadow_enabled": True,
            "shadow_color": "#003366",
            "shadow_blur": 4,
        },
    ]
    data = _load_json_file(SUBTITLE_STYLE_PRESETS_SAMPLE, fallback)
    return data if isinstance(data, list) else fallback


def load_scene_catalog() -> list[dict]:
    fallback = [
        {
            "id": "scene_001",
            "start_sec": 12.5,
            "end_sec": 28.0,
            "emotion": "surprise",
            "effect_group_id": "",
            "subtitle_style_preset_id": "subtitle_emotion_surprise",
            "comment_ids": ["sub_0007", "sub_0008"],
        }
    ]
    data = _load_json_file(SCENES_SAMPLE, fallback)
    return data if isinstance(data, list) else fallback


def load_decoration_presets() -> dict:
    fallback = {
        "font_presets": [
            {
                "id": "font_standard",
                "name": "標準",
                "family": "Yu Gothic",
                "size": 44,
                "color": "#ffffff",
                "outline_color": "#000000",
                "outline_width": 4,
                "shadow_color": "#000000",
                "shadow_depth": 4,
            },
            {
                "id": "font_pop",
                "name": "ポップ",
                "family": "Yu Gothic",
                "size": 54,
                "color": "#ff5fa8",
                "outline_color": "#ffffff",
                "outline_width": 5,
                "shadow_color": "#6b4a5a",
                "shadow_depth": 3,
            },
        ],
        "effect_groups": [
            {
                "id": "effect_group_manga_pop",
                "name": "漫画ポップ",
                "effects": ["bubble_round", "sparkle", "pop_in", "shake"],
                "description": "吹き出しとポップ演出をまとめた基本セット",
            },
            {
                "id": "effect_group_yume_kawaii",
                "name": "ゆめかわ",
                "effects": ["bubble_soft", "heart", "float_in"],
                "description": "淡い色と軽い浮遊感のセット",
            },
        ],
        "layout_presets": [
            {
                "id": "layout_bottom_center",
                "name": "下中央",
                "anchor": "bottom_center",
            },
            {
                "id": "layout_mid_lower",
                "name": "やや下",
                "anchor": "mid_lower",
            },
        ],
    }
    data = _load_json_file(DECORATION_PRESETS_SAMPLE, fallback)
    return data if isinstance(data, dict) else fallback


def preset_catalog() -> dict:
    return {
        "emotion_presets": load_emotion_presets(),
        "subtitle_style_presets": load_subtitle_style_presets(),
        "scenes": load_scene_catalog(),
        "decoration_presets": load_decoration_presets(),
        "emotion_labels": ["neutral", "joy", "anger", "sadness", "surprise", "fear", "embarrassment", "teasing"],
    }


def build_scene_catalog_from_subtitles(subtitles: list[dict], existing_scenes: list[dict] | None = None) -> list[dict]:
    by_id: dict[str, dict] = {}
    for scene in existing_scenes or []:
        scene_id = str(scene.get("id", "")).strip()
        if not scene_id:
            continue
        by_id[scene_id] = dict(scene)
        by_id[scene_id]["comment_ids"] = list(scene.get("comment_ids") or [])
    for sub in subtitles or []:
        scene_id = str(sub.get("scene_id", "")).strip()
        if not scene_id:
            continue
        start = float(sub.get("start_sec", sub.get("output_start_sec", 0.0)) or 0.0)
        end = float(sub.get("end_sec", sub.get("output_end_sec", start)) or start)
        if scene_id not in by_id:
            by_id[scene_id] = {
                "id": scene_id,
                "start_sec": start,
                "end_sec": end,
                "emotion": str(sub.get("emotion", "neutral") or "neutral"),
                "effect_group_id": str(sub.get("effect_group_id", "") or ""),
                "subtitle_style_preset_id": str(sub.get("subtitle_style_preset_id", "") or ""),
                "comment_ids": [],
            }
        scene = by_id[scene_id]
        scene["start_sec"] = round(min(float(scene.get("start_sec", start)), start), 3)
        scene["end_sec"] = round(max(float(scene.get("end_sec", end)), end), 3)
        scene["emotion"] = str(scene.get("emotion") or sub.get("emotion") or "neutral")
        scene["effect_group_id"] = str(scene.get("effect_group_id") or sub.get("effect_group_id") or "")
        scene["subtitle_style_preset_id"] = str(scene.get("subtitle_style_preset_id") or sub.get("subtitle_style_preset_id") or "")
        comment_ids = scene.get("comment_ids") or []
        if sub.get("id") and sub["id"] not in comment_ids:
            comment_ids.append(sub["id"])
        scene["comment_ids"] = comment_ids
    return sorted(
        [
            {
                "id": scene_id,
                "start_sec": round(float(scene.get("start_sec", 0.0)), 3),
                "end_sec": round(float(scene.get("end_sec", 0.0)), 3),
                "emotion": str(scene.get("emotion") or "neutral"),
                "effect_group_id": str(scene.get("effect_group_id") or ""),
                "subtitle_style_preset_id": str(scene.get("subtitle_style_preset_id") or ""),
                "comment_ids": list(scene.get("comment_ids") or []),
            }
            for scene_id, scene in by_id.items()
        ],
        key=lambda item: (float(item.get("start_sec", 0.0)), float(item.get("end_sec", 0.0)), item["id"]),
    )


def normalize_edit_plan_source_video(project_id: str, plan: dict) -> dict:
    normalized = dict(plan)
    source = project_source_video(project_id)
    base = require_project(project_id).resolve()
    try:
        normalized["source_video"] = str(source.relative_to(base))
    except ValueError:
        normalized["source_video"] = str(source)
    return normalized


def create_project_dirs(base: Path) -> None:
    for name in ["source", "audio", "transcript", "subtitles", "analysis", "preview", "output", "decoration", "temp/segments", "temp/logs"]:
        (base / name).mkdir(parents=True, exist_ok=True)


def create_project_from_local_file(source_file: Path, project_name: str | None = None) -> dict:
    ext = source_file.suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="対応形式は mp4, mkv, mov, webm です")
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="動画ファイルが存在しません")
    project_id = re.sub(r"[^A-Za-z0-9_-]+", "_", project_name or source_file.stem).strip("_")
    project_id = project_id[:48] or "project"
    project_id = f"{project_id}_{uuid.uuid4().hex[:8]}"
    base = PROJECTS_DIR / project_id
    create_project_dirs(base)
    source_path = base / "source" / f"input{ext}"
    shutil.copy2(source_file, source_path)
    info = {
        "project_id": project_id,
        "source_video": str(source_path.relative_to(base)),
        "source_video_url": f"/api/projects/{project_id}/media/source/{source_path.name}",
        "scenes": [],
        "decoration": {},
        "ui_state": {
            "default_emotion_preset_id": "emotion_neutral",
            "default_subtitle_style_preset_id": "subtitle_standard",
        },
    }
    atomic_write_json(base / "project.json", info)
    audit_project_event(project_id, "project.created", context={"source_file": str(source_file)})
    return {
        **info,
        "source_video": str(source_path),
    }


def load_project_decoration(project_id: str) -> dict:
    path = require_project(project_id) / "decoration" / "decoration_project.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    info = project_info(project_id)
    presets = load_decoration_presets()
    return {
        "project_id": project_id,
        "source_srt": str(resolve_project_path(project_id, "subtitles", "edited.srt")),
        "events": [],
        "effect_groups": presets.get("effect_groups", []),
        "font_presets": presets.get("font_presets", []),
        "layout_presets": presets.get("layout_presets", []),
        "scenes": info.get("scenes", []),
        "ui_state": info.get("ui_state", {}),
    }


def load_project_subtitles(project_id: str, kind: str = "edited") -> dict:
    kind = (kind or "edited").strip().lower()
    if kind not in {"edited", "final", "original"}:
        raise HTTPException(status_code=400, detail="不正な字幕種別です")
    if kind == "final":
        candidates = [resolve_project_path(project_id, "output", "final.srt")]
    elif kind == "original":
        candidates = [resolve_project_path(project_id, "subtitles", "original.srt")]
    else:
        candidates = [resolve_project_path(project_id, "subtitles", "edited.srt"), resolve_project_path(project_id, "subtitles", "original.srt")]
    for path in candidates:
        if path.exists():
            subtitles = parse_srt(path.read_text(encoding="utf-8", errors="replace"))
            return {"kind": kind, "path": str(path), "subtitles": subtitles}
    raise HTTPException(status_code=404, detail="字幕ファイルが見つかりません")


def save_project_decoration(project_id: str, decoration: dict) -> dict:
    path = require_project(project_id) / "decoration" / "decoration_project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    presets = load_decoration_presets()
    current = {
        "project_id": project_id,
        "source_srt": decoration.get("source_srt") or str(resolve_project_path(project_id, "subtitles", "edited.srt")),
        "events": decoration.get("events") or [],
        "effect_groups": decoration.get("effect_groups") or presets.get("effect_groups", []),
        "font_presets": decoration.get("font_presets") or presets.get("font_presets", []),
        "layout_presets": decoration.get("layout_presets") or presets.get("layout_presets", []),
        "scenes": decoration.get("scenes") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(path, current, backup=True)
    update_project_info(project_id, {"decoration": current})
    return current


async def create_project_from_upload(file: UploadFile, project_name: str | None) -> dict:
    ext = Path(file.filename or "input.mp4").suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="対応形式は mp4, mkv, mov, webm です")
    temp_dir = PROJECTS_DIR / "temp_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"{uuid.uuid4().hex}{ext}"
    with temp_file.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    try:
        return create_project_from_local_file(temp_file, project_name)
    finally:
        if temp_file.exists():
            temp_file.unlink()


def probe_video(video_path: str) -> dict:
    ensure_tool("ffprobe")
    path = Path(video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="動画ファイルが存在しません")
    audit_event("probe_video", context={"video_path": str(path)})
    proc = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    raw = json.loads(proc.stdout)
    video_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = 0.0
    rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
    if "/" in rate:
        num, den = rate.split("/", 1)
        fps = float(num) / float(den) if float(den) else 0.0
    else:
        fps = float(rate)
    return {
        "filename": path.name,
        "duration_sec": float(raw.get("format", {}).get("duration", 0.0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": round(fps, 3),
        "has_audio": audio_stream is not None,
        "audio_sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else None,
        "file_size": int(raw.get("format", {}).get("size", path.stat().st_size)),
    }


def extract_audio(project_id: str, video_path: str, start_sec: float, end_sec: float, compute_profile: str = "auto") -> dict:
    ensure_tool("ffmpeg")
    if start_sec < 0 or end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="指定区間が不正です")
    normalized_profile = normalize_compute_profile(compute_profile)
    base = require_project(project_id)
    output = base / "audio" / "source_range.wav"
    log = base / "temp" / "logs" / "audio_extract.log"
    run_command(
        [
            "ffmpeg",
            "-y",
            *ffmpeg_cfr_args(),
            "-ss",
            f"{start_sec:.3f}",
            "-to",
            f"{end_sec:.3f}",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        log,
    )
    audit_project_event(project_id, "extract_audio", context={"start_sec": start_sec, "end_sec": end_sec, "compute_profile": normalized_profile})
    return {"audio_path": str(output), "compute_profile": normalized_profile}


def transcribe_with_faster_whisper(project_id: str, audio_path: str, language: str, model: str, vad_filter: bool = False, word_timestamps: bool = False) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"faster-whisperを読み込めません: {exc}") from exc

    whisper_model = WhisperModel(model, device="auto", compute_type="auto")
    use_vad = bool(vad_filter)
    segments, info = whisper_model.transcribe(
        audio_path,
        language=language,
        beam_size=1,
        best_of=1,
        temperature=(0.0, 0.2, 0.4),
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.35 if use_vad else 0.4,
        condition_on_previous_text=False,
        prompt_reset_on_temperature=0.2,
        word_timestamps=word_timestamps,
        vad_filter=use_vad,
        hallucination_silence_threshold=0.5 if use_vad else 0.8,
    )
    transcript_segments: list[dict] = []
    for seg in segments:
        words = []
        for word in getattr(seg, "words", None) or []:
            words.append(
                {
                    "word": getattr(word, "word", ""),
                    "start": float(getattr(word, "start", 0.0) or 0.0),
                    "end": float(getattr(word, "end", 0.0) or 0.0),
                    "probability": float(getattr(word, "probability", 0.0) or 0.0),
                }
            )
        transcript_segments.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text,
                "words": words,
            }
        )
    return {
        "language": info.language,
        "engine": "faster-whisper-vad" if vad_filter else "faster-whisper",
        "model": model,
        "device": "auto",
        "compute_type": "auto",
        "vad_filter": use_vad,
        "hallucination_silence_threshold": 0.5 if use_vad else 0.8,
        "transcription": transcript_segments,
        "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in transcript_segments],
    }


def transcribe_audio(
    project_id: str,
    audio_path: str,
    language: str,
    model: str,
    compute_profile: str = "auto",
    engine: str = "whisper.cpp",
    silence_threshold_db: float = -35.0,
    vad_threshold: float = 0.25,
    vad_min_speech_duration_ms: int = 100,
    vad_min_silence_duration_ms: int = 80,
    vad_speech_pad_ms: int = 50,
    voice_isolation_enabled: bool = False,
    voice_isolation_engine: str = "demucs",
    use_isolated_voice_for_vad: bool = False,
    use_isolated_voice_for_whisper: bool = False,
    output_audio_mode: str = "original",
    detection_mode: str = "silencedetect",
    speaker_diarization_enabled: bool = False,
    speaker_diarization_engine: str = "speechbrain",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    pre_margin_sec: float = 0.3,
    post_margin_sec: float = 0.5,
    min_speech_duration_sec: float = 0.2,
    merge_silence_gap_sec: float = 0.5,
    align_timestamps: bool = False,
) -> dict:
    base = require_project(project_id)
    audio = Path(audio_path)
    if not audio.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")

    normalized_profile = normalize_compute_profile(compute_profile)

    gpu_blockers: list[str] = []
    if normalized_profile == "gpu":
        if engine not in {"whisper.cpp", "whisper.cpp-vad"}:
            gpu_blockers.append(f"文字起こしエンジン {engine}")
        if gpu_blockers:
            raise HTTPException(
                status_code=400,
                detail="GPUプロファイルでは文字起こしエンジンがGPU対応ではないため実行できません: " + " / ".join(gpu_blockers),
            )

    voice_isolation = isolate_voice_audio(project_id, str(audio), voice_isolation_engine) if voice_isolation_enabled else {
        "enabled": False,
        "engine": "none",
        "status": "skipped",
        "source_audio_path": str(audio),
        "isolated_audio_path": None,
    }
    isolated_audio_path = voice_isolation.get("isolated_audio_path")
    whisper_source_audio = isolated_audio_path if use_isolated_voice_for_whisper and isolated_audio_path else str(audio)
    vad_source_audio = isolated_audio_path if use_isolated_voice_for_vad and isolated_audio_path else str(audio)
    prepared_audio_cache: dict[str, str] = {}

    def prepared_audio(source_path: str, purpose: str) -> str:
        cache_key = f"{purpose}:{source_path}"
        if cache_key not in prepared_audio_cache:
            prepared_audio_cache[cache_key] = prepare_transcription_audio(project_id, source_path, purpose=purpose)
        return prepared_audio_cache[cache_key]

    whisper_audio_path = prepared_audio(whisper_source_audio, "whisper")
    vad_audio_path = prepared_audio(vad_source_audio, "vad")
    if engine == "whisper.cpp":
        result = transcribe_with_whisper_cpp(project_id, whisper_audio_path, language, model, normalized_profile)
    elif engine == "whisper.cpp-vad":
        result = transcribe_with_whisper_cpp_vad(
            project_id,
            whisper_audio_path,
            language,
            model,
            normalized_profile,
            vad_threshold=vad_threshold,
            vad_min_speech_duration_ms=vad_min_speech_duration_ms,
            vad_min_silence_duration_ms=vad_min_silence_duration_ms,
            vad_speech_pad_ms=vad_speech_pad_ms,
        )
    elif engine == "faster-whisper":
        result = transcribe_with_faster_whisper(project_id, whisper_audio_path, language, model, vad_filter=False, word_timestamps=False)
    elif engine == "faster-whisper-vad":
        result = transcribe_with_faster_whisper(project_id, whisper_audio_path, language, model, vad_filter=True, word_timestamps=True)
    else:
        try:
            import whisper
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"openai-whisperを読み込めません: {exc}") from exc
        whisper_model = whisper.load_model(model)
        result = whisper_model.transcribe(whisper_audio_path, language=language, verbose=False)

    if normalized_profile == "gpu" and engine.startswith("whisper.cpp"):
        whisper_device = str(result.get("device") or "").lower()
        if whisper_device not in {"vulkan", "gpu", "cuda"}:
            raise HTTPException(
                status_code=400,
                detail=f"GPUプロファイルでwhisper.cppがGPU実行できませんでした: device={result.get('device')}",
            )

    raw_subtitles = normalize_subtitle_durations(subtitles_from_whisper(result))
    need_vad = detection_mode in {"vad", "hybrid"} or speaker_diarization_enabled or align_timestamps
    vad_intervals = {"speech_intervals": [], "compute_profile": normalized_profile, "status": "skipped"}
    if need_vad:
        vad_intervals = detect_vad_speech_intervals(
            project_id,
            vad_audio_path,
            vad_threshold=vad_threshold,
            min_speech_duration_sec=min_speech_duration_sec,
            min_silence_duration_sec=vad_min_silence_duration_ms / 1000.0,
            speech_pad_sec=vad_speech_pad_ms / 1000.0,
            merge_silence_gap_sec=merge_silence_gap_sec,
        )
    speaker_diarization = run_speaker_diarization(
        project_id,
        diarization_audio_path=isolated_audio_path or str(audio),
        enabled=speaker_diarization_enabled,
        engine=speaker_diarization_engine,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        speech_intervals=vad_intervals.get("speech_intervals", []),
    )
    raw_subtitles = assign_speaker_labels_to_subtitles(
        raw_subtitles,
        speaker_diarization.get("speaker_segments", []),
        speaker_roster=speaker_diarization.get("speaker_roster", []),
    )
    waveform_profile = build_waveform_analysis(vad_audio_path)
    waveform_json_path = base / "analysis" / "waveform.json"
    waveform_png_path = base / "analysis" / "waveform.png"
    waveform_json_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(waveform_json_path, waveform_profile)
    render_waveform_png(waveform_profile, waveform_png_path)
    audit_project_detail_event(
        project_id,
        "transcribe.waveform_analysis",
        stream="processing",
        context={
            "audio_path": str(audio),
            "voice_isolation_enabled": voice_isolation_enabled,
            "voice_isolation_engine": voice_isolation_engine,
            "whisper_audio_path": whisper_audio_path,
            "vad_audio_path": vad_audio_path,
            "sample_rate": waveform_profile.get("sample_rate"),
            "window_ms": waveform_profile.get("window_ms"),
            "duration_sec": waveform_profile.get("duration_sec"),
            "point_count": waveform_profile.get("point_count"),
            "analysis_path": str(waveform_json_path),
            "image_path": str(waveform_png_path),
        },
    )
    result["raw_subtitles"] = raw_subtitles
    result["vad_intervals"] = vad_intervals.get("speech_intervals", [])
    result["speech_intervals"] = result["vad_intervals"]
    result["voice_isolation"] = voice_isolation
    result["voice_isolated_audio_path"] = isolated_audio_path
    result["whisper_audio_path"] = whisper_audio_path
    result["vad_audio_path"] = vad_audio_path
    result["output_audio_mode"] = output_audio_mode
    result["detection_mode"] = detection_mode
    result["speaker_diarization"] = speaker_diarization
    result["speaker_roster"] = speaker_diarization.get("speaker_roster", [])
    result["subtitle_correction"] = {
        "pre_margin_sec": pre_margin_sec,
        "post_margin_sec": post_margin_sec,
        "min_speech_duration_sec": min_speech_duration_sec,
        "merge_silence_gap_sec": merge_silence_gap_sec,
        "silence_threshold_db": silence_threshold_db,
    }
    result["subtitles"] = raw_subtitles
    result["waveform"] = waveform_profile
    result["waveform_analysis_path"] = str(waveform_json_path)
    result["waveform_image_path"] = str(waveform_png_path)
    result["processing_summary"] = {
        "compute_profile": normalized_profile,
        "whisper": {
            "engine": result.get("engine", engine),
            "model": result.get("model", model),
            "audio_path": whisper_audio_path,
            "device": result.get("device", "auto" if engine.startswith("faster-whisper") else "cpu"),
            "gpu_used": result.get("gpu_used"),
        },
        "voice_isolation": {
            "enabled": voice_isolation_enabled,
            "engine": voice_isolation_engine,
            "status": voice_isolation.get("status"),
            "audio_path": isolated_audio_path,
        },
        "vad": {
            "engine": "silero",
            "audio_path": vad_audio_path,
            "device": "cpu",
        },
        "speaker_diarization": {
            "enabled": speaker_diarization_enabled,
            "engine": speaker_diarization_engine,
            "device": speaker_diarization.get("device", "cpu"),
            "status": speaker_diarization.get("status"),
        },
        "alignment": {
            "enabled": align_timestamps,
            "engine": result.get("alignment_engine", "none"),
            "device": "cpu" if align_timestamps else "none",
            "status": result.get("alignment_status", "skipped" if not align_timestamps else "unknown"),
        },
    }
    audit_project_detail_event(
        project_id,
        "voice_isolation.result",
        stream="processing",
        context={
            "voice_isolation_enabled": voice_isolation_enabled,
            "voice_isolation_engine": voice_isolation_engine,
            "use_isolated_voice_for_vad": use_isolated_voice_for_vad,
            "use_isolated_voice_for_whisper": use_isolated_voice_for_whisper,
            "output_audio_mode": output_audio_mode,
            "compute_profile": normalized_profile,
            "gpu_blockers": gpu_blockers,
            "voice_isolation_status": voice_isolation.get("status"),
            "voice_isolated_audio_path": isolated_audio_path,
            "whisper_audio_path": whisper_audio_path,
            "vad_audio_path": vad_audio_path,
            "speaker_diarization_enabled": speaker_diarization_enabled,
            "speaker_diarization_engine": speaker_diarization_engine,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
        },
    )
    transcript_path = base / "transcript" / "transcript.json"
    original_srt_path = base / "subtitles" / "original.srt"
    write_srt(raw_subtitles, original_srt_path)
    aligned_srt_path = None
    result["original_srt_path"] = str(original_srt_path)
    result["aligned_srt_path"] = None

    alignment_error: str | None = None
    if align_timestamps:
        try:
            aligned_result = align_subtitles_with_whisperx(project_id, whisper_audio_path, result, waveform_profile=waveform_profile)
            aligned_subtitles = aligned_result.get("aligned_subtitles", []) or aligned_result.get("subtitles", [])
            result.update(
                {
                    "alignment_engine": aligned_result.get("alignment_engine"),
                    "alignment_language": aligned_result.get("alignment_language"),
                    "aligned_transcription": aligned_result.get("aligned_transcription", []),
                    "aligned_segments": aligned_result.get("aligned_segments", []),
                    "aligned_subtitles": aligned_subtitles,
                    "waveform_refined_subtitles": aligned_result.get("waveform_refined_subtitles", []),
                    "whisperx_aligned_srt_path": aligned_result.get("whisperx_aligned_srt_path"),
                    "alignment_status": "ok",
                }
            )
            if aligned_subtitles:
                result["subtitles"] = aligned_subtitles
                result["aligned_srt_path"] = aligned_result.get("whisperx_aligned_srt_path")
        except Exception as exc:
            alignment_error = str(exc)
            result["alignment_error"] = alignment_error
            result["alignment_status"] = "fallback_vad"

    atomic_write_json(transcript_path, result, backup=True)
    audit_project_event(
        project_id,
        "transcribe_audio",
        context={
                "engine": engine,
                "model": model,
                "language": language,
                "silence_threshold_db": silence_threshold_db,
                "align_timestamps": align_timestamps,
                "alignment_error": alignment_error,
                "voice_isolation_enabled": voice_isolation_enabled,
                "voice_isolation_engine": voice_isolation_engine,
                "use_isolated_voice_for_vad": use_isolated_voice_for_vad,
                "use_isolated_voice_for_whisper": use_isolated_voice_for_whisper,
                "output_audio_mode": output_audio_mode,
                "compute_profile": normalized_profile,
                "gpu_blockers": gpu_blockers,
                "detection_mode": detection_mode,
                "speaker_diarization_enabled": speaker_diarization_enabled,
                "speaker_diarization_engine": speaker_diarization_engine,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
                "pre_margin_sec": pre_margin_sec,
                "post_margin_sec": post_margin_sec,
                "min_speech_duration_sec": min_speech_duration_sec,
                "merge_silence_gap_sec": merge_silence_gap_sec,
                "vad_interval_count": len(result.get("vad_intervals", [])),
            "raw_subtitle_count": len(raw_subtitles),
        },
    )
    audit_project_detail_event(
        project_id,
        "transcribe.output_paths",
        stream="processing",
        context={
            "transcript_path": str(transcript_path),
            "original_srt_path": str(original_srt_path),
            "aligned_srt_path": str(aligned_srt_path) if aligned_srt_path else None,
            "voice_isolated_audio_path": isolated_audio_path,
            "whisper_audio_path": whisper_audio_path,
            "vad_audio_path": vad_audio_path,
            "waveform_image_path": str(waveform_png_path),
            "waveform_analysis_path": str(waveform_json_path),
        },
    )
    return {
        "transcript_path": str(transcript_path),
        "srt_path": str(original_srt_path),
        "aligned_srt_path": result.get("aligned_srt_path"),
        "waveform_image_path": str(waveform_png_path),
        "waveform_image_url": f"/api/projects/{project_id}/media/analysis/{waveform_png_path.name}",
        "waveform_analysis_path": str(waveform_json_path),
        "whisperx_aligned_srt_path": result.get("whisperx_aligned_srt_path"),
        "voice_isolation": voice_isolation,
        "voice_isolated_audio_path": isolated_audio_path,
        "whisper_audio_path": whisper_audio_path,
        "vad_audio_path": vad_audio_path,
        "raw_subtitles": result.get("raw_subtitles", raw_subtitles),
        "aligned_subtitles": result.get("aligned_subtitles", []),
        "subtitles": result.get("subtitles", raw_subtitles),
        "vad_intervals": result["vad_intervals"],
        "speaker_diarization": speaker_diarization,
        "speaker_roster": speaker_diarization.get("speaker_roster", []),
        "processing_summary": result.get("processing_summary", {}),
    }


def detect_silence(project_id: str, audio_path: str, threshold_db: float, min_silence_duration: float, compute_profile: str = "auto") -> dict:
    ensure_tool("ffmpeg")
    normalized_profile = normalize_compute_profile(compute_profile)
    base = require_project(project_id)
    log = base / "temp" / "logs" / "silencedetect.log"
    proc = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            audio_path,
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_silence_duration}",
            "-f",
            "null",
            "-",
        ],
        log,
    )
    text = proc.stderr
    starts = [float(v) for v in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    silences = []
    for idx, start in enumerate(starts):
        end = ends[idx] if idx < len(ends) else start
        if end > start:
            silences.append({"start_sec": round(start, 3), "end_sec": round(end, 3)})
    audit_project_event(project_id, "detect_silence", context={"threshold_db": threshold_db, "min_silence_duration": min_silence_duration, "silence_count": len(silences), "compute_profile": normalized_profile})
    return {"silences": silences, "compute_profile": normalized_profile}


def detect_vad_speech_intervals(
    project_id: str,
    audio_path: str,
    *,
    compute_profile: str = "auto",
    vad_threshold: float = 0.25,
    min_speech_duration_sec: float = 0.2,
    min_silence_duration_sec: float = 0.5,
    speech_pad_sec: float = 0.05,
    merge_silence_gap_sec: float = 0.5,
) -> dict:
    normalized_profile = normalize_compute_profile(compute_profile)
    intervals = detect_silero_speech_intervals(
        audio_path,
        vad_threshold=vad_threshold,
        min_speech_duration_sec=min_speech_duration_sec,
        min_silence_duration_sec=min_silence_duration_sec,
        speech_pad_sec=speech_pad_sec,
        merge_silence_gap_sec=merge_silence_gap_sec,
    )
    speech_intervals = [
        {
            "speech_start_sec": float(item["start_sec"]),
            "speech_end_sec": float(item["end_sec"]),
            "start_sec": float(item["start_sec"]),
            "end_sec": float(item["end_sec"]),
        }
        for item in intervals
    ]
    audit_project_event(
        project_id,
        "detect_vad_speech_intervals",
        context={
            "vad_threshold": vad_threshold,
            "min_speech_duration_sec": min_speech_duration_sec,
            "min_silence_duration_sec": min_silence_duration_sec,
            "speech_pad_sec": speech_pad_sec,
            "merge_silence_gap_sec": merge_silence_gap_sec,
            "speech_count": len(speech_intervals),
            "compute_profile": normalized_profile,
        },
    )
    return {"speech_intervals": speech_intervals, "compute_profile": normalized_profile}


@lru_cache(maxsize=1)
def _load_silero_vad_resources() -> tuple[object, tuple[object, ...]]:
    try:
        import torch
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"torchを読み込めません: {exc}") from exc
    try:
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
        return model, utils
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Silero VADを読み込めません: {exc}") from exc


def detect_silero_speech_intervals(
    audio_path: str,
    *,
    vad_threshold: float = 0.25,
    min_speech_duration_sec: float = 0.2,
    min_silence_duration_sec: float = 0.5,
    speech_pad_sec: float = 0.05,
    merge_silence_gap_sec: float = 0.5,
) -> list[dict]:
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが見つかりません")
    try:
        from whisperx.audio import load_audio
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"whisperx.audioを読み込めません: {exc}") from exc

    model, utils = _load_silero_vad_resources()
    get_speech_timestamps = utils[0]
    wav = load_audio(str(path))
    timestamps = get_speech_timestamps(
        wav,
        model,
        threshold=float(vad_threshold),
        min_speech_duration_ms=int(max(0.0, min_speech_duration_sec) * 1000),
        min_silence_duration_ms=int(max(0.0, min_silence_duration_sec) * 1000),
        speech_pad_ms=int(max(0.0, speech_pad_sec) * 1000),
        return_seconds=True,
    )
    intervals = [
        (float(item.get("start", 0.0)), float(item.get("end", 0.0)))
        for item in timestamps
        if float(item.get("end", 0.0)) > float(item.get("start", 0.0))
    ]
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max(0.0, merge_silence_gap_sec):
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return [{"start_sec": round(start, 3), "end_sec": round(end, 3)} for start, end in merged]


@lru_cache(maxsize=4)
def _load_speaker_diarization_pipeline(engine: str, token: str, device_name: str):
    try:
        from whisperx.diarize import DiarizationPipeline
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"whisperx.diarizeを読み込めません: {exc}") from exc

    model_name = "pyannote/speaker-diarization-3.1" if engine == "pyannote" else None
    return DiarizationPipeline(model_name=model_name, token=token, device=device_name)


def _resolve_hf_token() -> str | None:
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "PYANNOTE_AUTH_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def run_speaker_diarization(
    project_id: str,
    *,
    diarization_audio_path: str,
    enabled: bool = True,
    engine: str = "speechbrain",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    speech_intervals: list[dict] | None = None,
) -> dict:
    normalized_engine = (engine or "none").strip().lower()
    if not enabled or normalized_engine == "none":
        audit_project_detail_event(
            project_id,
            "speaker_diarization.result",
            stream="processing",
            context={
                "engine": "none",
                "status": "skipped",
                "source_audio_path": str(diarization_audio_path),
            },
        )
        return {
            "enabled": False,
            "engine": "none",
            "status": "skipped",
            "source_audio_path": str(diarization_audio_path),
            "speaker_segments": [],
            "speaker_roster": [],
        }
    source = Path(diarization_audio_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="話者分離用音声が見つかりません")
    try:
        if normalized_engine == "speechbrain":
            result = _run_speaker_diarization_speechbrain(
                project_id,
                source,
                speech_intervals or [],
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
        elif normalized_engine in {"whisperx", "pyannote"}:
            result = _run_speaker_diarization_pyannote(
                project_id,
                source,
                engine=normalized_engine,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
        else:
            raise HTTPException(status_code=400, detail="speaker_diarization_engine は speechbrain / whisperx / pyannote / none を指定してください")
        return result
    except Exception as exc:
        audit_project_detail_event(
            project_id,
            "speaker_diarization.failed",
            stream="processing",
            status="error",
            context={
                "engine": normalized_engine,
                "source_audio_path": str(source),
                "error": str(exc),
            },
        )
        return {
            "enabled": True,
            "engine": normalized_engine,
            "status": "fallback_disabled",
            "error": str(exc),
            "source_audio_path": str(source),
            "speaker_segments": [],
            "speaker_roster": [],
        }


def _segment_audio_window(audio: "object", sample_rate: int, start_sec: float, end_sec: float, *, pad_sec: float = 0.25, min_duration_sec: float = 1.2):
    import numpy as np

    audio_array = np.asarray(audio, dtype=np.float32).reshape(-1)
    total_sec = len(audio_array) / float(sample_rate)
    start = max(0.0, start_sec - pad_sec)
    end = min(total_sec, end_sec + pad_sec)
    if end - start < min_duration_sec:
        missing = min_duration_sec - (end - start)
        start = max(0.0, start - missing / 2)
        end = min(total_sec, end + missing / 2)
    if end <= start:
        return None
    start_idx = int(start * sample_rate)
    end_idx = max(start_idx + 1, int(end * sample_rate))
    segment = audio_array[start_idx:end_idx]
    if len(segment) < int(sample_rate * 0.35):
        return None
    return start, end, segment


@lru_cache(maxsize=1)
def _load_speechbrain_speaker_model():
    try:
        import torch
        from speechbrain.inference.speaker import SpeakerRecognition
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"speechbrainを読み込めません: {exc}") from exc

    cache_dir = ROOT / "temp" / "speechbrain_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(cache_dir),
        run_opts={"device": device},
    )
    return model, device


def _cluster_speaker_embeddings(embeddings: list[list[float]]) -> list[int]:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.preprocessing import normalize

    if not embeddings:
        return []
    matrix = normalize(np.asarray(embeddings, dtype=np.float32))
    if len(matrix) == 1:
        return [0]
    try:
        cluster = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.65,
            linkage="average",
            metric="cosine",
        )
        return cluster.fit_predict(matrix).tolist()
    except TypeError:
        cluster = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.65,
            linkage="average",
            affinity="cosine",
        )
        return cluster.fit_predict(matrix).tolist()


def _run_speaker_diarization_speechbrain(
    project_id: str,
    source: Path,
    speech_intervals: list[dict],
    *,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    if not speech_intervals:
        result = {
            "enabled": True,
            "engine": "speechbrain",
            "status": "skipped_no_speech",
            "source_audio_path": str(source),
            "speaker_segments": [],
            "speaker_roster": [],
            "model": "speechbrain/spkrec-ecapa-voxceleb",
        }
        audit_project_detail_event(
            project_id,
            "speaker_diarization.result",
            stream="processing",
            context={"engine": "speechbrain", "status": "skipped_no_speech", "source_audio_path": str(source)},
        )
        return result

    try:
        import numpy as np
        import torch
        from whisperx.audio import load_audio
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"speechbrain diarization の依存を読み込めません: {exc}") from exc

    model, device_name = _load_speechbrain_speaker_model()
    audio = load_audio(str(source))
    sample_rate = 16000
    segments_for_embedding: list[dict] = []
    embeddings: list[list[float]] = []
    for interval in sorted(speech_intervals, key=lambda x: float(x.get("start_sec", 0.0))):
        start_sec = float(interval.get("start_sec", interval.get("speech_start_sec", 0.0)))
        end_sec = float(interval.get("end_sec", interval.get("speech_end_sec", start_sec)))
        window = _segment_audio_window(audio, sample_rate, start_sec, end_sec)
        if window is None:
            continue
        seg_start, seg_end, seg_audio = window
        wav = torch.tensor(np.asarray(seg_audio, dtype=np.float32), dtype=torch.float32).unsqueeze(0)
        wav_lens = torch.tensor([1.0], dtype=torch.float32)
        with torch.no_grad():
            emb = model.encode_batch(wav, wav_lens=wav_lens, normalize=True)
        emb_array = emb.detach().cpu().numpy().reshape(-1).astype(float).tolist()
        segments_for_embedding.append(
            {
                "start_sec": round(seg_start, 3),
                "end_sec": round(seg_end, 3),
                "source_start_sec": round(start_sec, 3),
                "source_end_sec": round(end_sec, 3),
            }
        )
        embeddings.append(emb_array)

    if not segments_for_embedding:
        result = {
            "enabled": True,
            "engine": "speechbrain",
            "status": "skipped_no_embedded_segments",
            "source_audio_path": str(source),
            "speaker_segments": [],
            "speaker_roster": [],
            "model": "speechbrain/spkrec-ecapa-voxceleb",
        }
        audit_project_detail_event(
            project_id,
            "speaker_diarization.result",
            stream="processing",
            context={"engine": "speechbrain", "status": "skipped_no_embedded_segments", "source_audio_path": str(source)},
        )
        return result

    labels = _cluster_speaker_embeddings(embeddings)
    cluster_map: dict[int, str] = {}
    speaker_segments: list[dict] = []
    for idx, seg in enumerate(segments_for_embedding):
        cluster = labels[idx] if idx < len(labels) else 0
        if cluster not in cluster_map:
            cluster_map[cluster] = f"SPEAKER_{len(cluster_map) + 1:02d}"
        speaker_segments.append(
            {
                "start_sec": seg["start_sec"],
                "end_sec": seg["end_sec"],
                "speaker_id": cluster_map[cluster],
                "speaker_label": cluster_map[cluster],
                "speaker_source_label": f"cluster_{cluster:02d}",
            }
        )

    merged_segments: list[dict] = []
    gap_limit = 0.35
    for seg in speaker_segments:
        if not merged_segments:
            merged_segments.append(dict(seg))
            continue
        prev = merged_segments[-1]
        if prev["speaker_id"] == seg["speaker_id"] and seg["start_sec"] - prev["end_sec"] <= gap_limit:
            prev["end_sec"] = max(prev["end_sec"], seg["end_sec"])
        else:
            merged_segments.append(dict(seg))

    speaker_roster = [
        {"speaker_id": speaker_id, "speaker_source_label": f"cluster_{cluster:02d}", "display_name": speaker_id}
        for cluster, speaker_id in sorted(cluster_map.items(), key=lambda item: item[1])
    ]
    result = {
        "enabled": True,
        "engine": "speechbrain",
        "status": "ok",
        "model": "speechbrain/spkrec-ecapa-voxceleb",
        "source_audio_path": str(source),
        "speaker_segments": merged_segments,
        "speaker_roster": speaker_roster,
        "speaker_count": len(speaker_roster),
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "device": device_name,
    }
    audit_project_detail_event(
        project_id,
        "speaker_diarization.result",
        stream="processing",
        context={
            "engine": "speechbrain",
            "status": "ok",
            "speaker_count": len(speaker_roster),
            "segment_count": len(merged_segments),
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
            "source_audio_path": str(source),
            "device": device_name,
        },
    )
    return result


def _run_speaker_diarization_pyannote(
    project_id: str,
    source: Path,
    *,
    engine: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    token = _resolve_hf_token()
    if not token:
        audit_project_detail_event(
            project_id,
            "speaker_diarization.result",
            stream="processing",
            context={
                "engine": engine,
                "status": "skipped_no_token",
                "source_audio_path": str(source),
            },
        )
        return {
            "enabled": True,
            "engine": engine,
            "status": "skipped_no_token",
            "reason": "HF_TOKEN / HUGGINGFACE_TOKEN / PYANNOTE_AUTH_TOKEN が設定されていません",
            "source_audio_path": str(source),
            "speaker_segments": [],
            "speaker_roster": [],
        }

    try:
        import torch
        from whisperx.audio import load_audio
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"話者分離の依存を読み込めません: {exc}") from exc

    audio = load_audio(str(source))
    device_name = "cuda" if torch.cuda.is_available() else "cpu"
    pipeline = _load_speaker_diarization_pipeline(engine, token, device_name)
    kwargs: dict[str, int] = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = max(1, int(min_speakers))
    if max_speakers is not None:
        kwargs["max_speakers"] = max(1, int(max_speakers))
    if kwargs.get("min_speakers") and kwargs.get("max_speakers") and kwargs["min_speakers"] > kwargs["max_speakers"]:
        kwargs["min_speakers"], kwargs["max_speakers"] = kwargs["max_speakers"], kwargs["min_speakers"]

    diarize_df = pipeline(audio, **kwargs)
    rows = []
    for row in diarize_df.sort_values(["start", "end"]).itertuples(index=False):
        start = float(getattr(row, "start", 0.0) or 0.0)
        end = float(getattr(row, "end", 0.0) or 0.0)
        source_label = str(getattr(row, "speaker", "") or getattr(row, "label", "") or "SPEAKER_00").strip()
        if end <= start:
            continue
        rows.append({"start_sec": round(start, 3), "end_sec": round(end, 3), "speaker_source_label": source_label})
    label_map: dict[str, str] = {}
    speaker_segments: list[dict] = []
    speaker_roster: list[dict] = []
    for item in rows:
        source_label = item["speaker_source_label"]
        if source_label not in label_map:
            label_map[source_label] = f"SPEAKER_{len(label_map) + 1:02d}"
            speaker_roster.append(
                {
                    "speaker_id": label_map[source_label],
                    "speaker_source_label": source_label,
                    "display_name": label_map[source_label],
                }
            )
        speaker_id = label_map[source_label]
        speaker_segments.append(
            {
                "start_sec": item["start_sec"],
                "end_sec": item["end_sec"],
                "speaker_id": speaker_id,
                "speaker_label": speaker_id,
                "speaker_source_label": source_label,
            }
        )
    result = {
        "enabled": True,
        "engine": engine,
        "status": "ok",
        "model": "pyannote/speaker-diarization-3.1" if engine == "pyannote" else "pyannote/speaker-diarization-community-1",
        "source_audio_path": str(source),
        "speaker_segments": speaker_segments,
        "speaker_roster": speaker_roster,
        "speaker_count": len(speaker_roster),
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
        "device": device_name,
    }
    audit_project_detail_event(
        project_id,
        "speaker_diarization.result",
        stream="processing",
        context={
            "engine": engine,
            "status": "ok",
            "speaker_count": len(speaker_roster),
            "segment_count": len(speaker_segments),
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
            "source_audio_path": str(source),
            "device": device_name,
        },
    )
    return result


def assign_speaker_labels_to_subtitles(
    subtitles: list[dict],
    speaker_segments: list[dict],
    *,
    speaker_roster: list[dict] | None = None,
    max_gap_sec: float = 0.75,
) -> list[dict]:
    if not subtitles:
        return []
    roster_map = {str(item.get("speaker_id", "")).strip(): str(item.get("display_name", item.get("speaker_id", ""))).strip() for item in (speaker_roster or []) if item.get("speaker_id")}
    ordered_segments = sorted(
        [
            {
                "start_sec": float(seg.get("start_sec", 0.0)),
                "end_sec": float(seg.get("end_sec", 0.0)),
                "speaker_id": str(seg.get("speaker_id", seg.get("speaker_label", ""))).strip(),
                "speaker_label": str(seg.get("speaker_label", seg.get("speaker_id", ""))).strip(),
                "speaker_source_label": str(seg.get("speaker_source_label", seg.get("speaker_label", ""))).strip(),
            }
            for seg in speaker_segments
            if float(seg.get("end_sec", 0.0)) > float(seg.get("start_sec", 0.0))
        ],
        key=lambda item: (item["start_sec"], item["end_sec"]),
    )
    if not ordered_segments:
        return [dict(sub) for sub in subtitles]

    assigned: list[dict] = []
    for sub in subtitles:
        item = dict(sub)
        original_start = float(item.get("original_start_sec", item.get("source_start_sec", item.get("whisper_start_sec", item.get("output_start_sec", 0.0)))))
        original_end = float(item.get("original_end_sec", item.get("source_end_sec", item.get("whisper_end_sec", item.get("output_end_sec", original_start)))))
        if original_end <= original_start:
            assigned.append(item)
            continue
        if item.get("speaker_label") and item.get("speaker_id"):
            assigned.append(item)
            continue
        best_id = None
        best_label = None
        best_overlap = 0.0
        best_gap = None
        for seg in ordered_segments:
            overlap = min(original_end, seg["end_sec"]) - max(original_start, seg["start_sec"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = seg["speaker_id"]
                best_label = seg["speaker_label"] or roster_map.get(seg["speaker_id"], seg["speaker_id"])
            elif overlap <= 0:
                gap = max(seg["start_sec"] - original_end, original_start - seg["end_sec"])
                if gap <= max_gap_sec and (best_gap is None or gap < best_gap):
                    best_gap = gap
                    best_id = seg["speaker_id"]
                    best_label = seg["speaker_label"] or roster_map.get(seg["speaker_id"], seg["speaker_id"])
        if best_id:
            item["speaker_id"] = best_id
            item["speaker_label"] = roster_map.get(best_id, best_label or best_id)
            item["speaker_confidence"] = round(max(0.0, best_overlap) / max(0.001, original_end - original_start), 3)
        assigned.append(item)
    return assigned


def prepare_transcription_audio(project_id: str, audio_path: str, purpose: str = "enhanced") -> str:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    source = Path(audio_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source.stem).strip("_")[:32] or "audio"
    safe_purpose = re.sub(r"[^A-Za-z0-9_-]+", "_", purpose).strip("_")[:24] or "enhanced"
    prepared = base / "temp" / f"transcribe_{safe_purpose}_{safe_stem}.wav"
    log = base / "temp" / "logs" / f"transcribe_{safe_purpose}_{safe_stem}.log"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            "highpass=f=90,lowpass=f=7800,afftdn=nf=-25",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(prepared),
        ],
        log,
    )
    return str(prepared)


def isolate_voice_audio(project_id: str, audio_path: str, engine: str = "demucs") -> dict:
    base = require_project(project_id)
    source = Path(audio_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")
    normalized_engine = (engine or "none").strip().lower()
    if normalized_engine == "none":
        return {
            "enabled": False,
            "engine": "none",
            "status": "skipped",
            "source_audio_path": str(source),
            "isolated_audio_path": None,
        }
    if normalized_engine == "uvr":
        normalized_engine = "demucs"
    if normalized_engine != "demucs":
        raise HTTPException(status_code=400, detail="voice_isolation_engine は demucs / uvr / none を指定してください")

    output_dir = base / "analysis" / "voice_isolation"
    output_dir.mkdir(parents=True, exist_ok=True)
    isolated_audio = output_dir / "voice_isolated.wav"
    log_path = base / "temp" / "logs" / "voice_isolation_demucs.log"
    if isolated_audio.exists():
        return {
            "enabled": True,
            "engine": engine,
            "status": "cached",
            "source_audio_path": str(source),
            "isolated_audio_path": str(isolated_audio),
        }

    try:
        work_root = Path(os.environ.get("TEMP", str(ROOT / "temp"))) / "cutsubtitle_voice_isolation" / safe_project_id(project_id)
        work_root.mkdir(parents=True, exist_ok=True)
        work_input = work_root / "input.wav"
        work_output = work_root / "output"
        if work_input.exists():
            work_input.unlink()
        if work_output.exists():
            shutil.rmtree(work_output)
        shutil.copy2(source, work_input)
        proc = run_command(
            [
                sys.executable,
                "-m",
                "demucs.separate",
                "--two-stems",
                "vocals",
                "--mp3",
                "-n",
                "htdemucs",
                "-o",
                str(work_output),
                str(work_input),
            ],
            log_path,
        )
        _ = proc
        candidates = sorted(list(work_output.rglob("vocals.mp3")) + list(work_output.rglob("vocals.wav")), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(status_code=500, detail="demucs の出力から vocals.wav を見つけられませんでした")
        candidate = candidates[0]
        if candidate.suffix.lower() == ".mp3":
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(candidate),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(isolated_audio),
                ],
                log_path.with_name("voice_isolation_demucs_convert.log"),
            )
        else:
            shutil.copy2(candidate, isolated_audio)
        return {
            "enabled": True,
            "engine": "demucs",
            "status": "ok",
            "source_audio_path": str(source),
            "isolated_audio_path": str(isolated_audio),
            "model": "htdemucs",
            "log_path": str(log_path),
        }
    except Exception as exc:
        audit_project_detail_event(
            project_id,
            "voice_isolation.failed",
            stream="processing",
            context={
                "engine": normalized_engine,
                "source_audio_path": str(source),
                "error": str(exc),
            },
        )
        return {
            "enabled": True,
            "engine": "demucs",
            "status": "fallback_original",
            "error": str(exc),
            "source_audio_path": str(source),
            "isolated_audio_path": None,
            "log_path": str(log_path),
        }


def build_waveform_analysis(audio_path: str, max_points: int = WAVEFORM_MAX_POINTS, window_ms: int = 20) -> dict:
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")

    points: list[dict] = []
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        if channels != 1 or sample_width != 2:
            raise HTTPException(status_code=500, detail="waveform analysis needs mono 16-bit PCM wav")
        frame_samples = max(1, int(sample_rate * window_ms / 1000))
        total_frames = wf.getnframes()
        for frame_index in range(0, total_frames, frame_samples):
            chunk = wf.readframes(frame_samples)
            if not chunk:
                break
            rms = audioop.rms(chunk, sample_width)
            peak = audioop.max(chunk, sample_width)
            db = -120.0 if rms <= 0 else 20.0 * math.log10(rms / 32768.0)
            start_sec = frame_index / sample_rate
            end_frames = frame_index + len(chunk) // (sample_width * channels)
            end_sec = min(total_frames / sample_rate, end_frames / sample_rate)
            points.append(
                {
                    "start_sec": round(start_sec, 3),
                    "end_sec": round(end_sec, 3),
                    "rms": int(rms),
                    "peak": int(peak),
                    "db": round(db, 3),
                }
            )

    if len(points) > max_points:
        bucket_size = math.ceil(len(points) / max_points)
        condensed: list[dict] = []
        for i in range(0, len(points), bucket_size):
            chunk = points[i : i + bucket_size]
            if not chunk:
                continue
            condensed.append(
                {
                    "start_sec": chunk[0]["start_sec"],
                    "end_sec": chunk[-1]["end_sec"],
                    "rms": max(item["rms"] for item in chunk),
                    "peak": max(item["peak"] for item in chunk),
                    "db": round(max(item["db"] for item in chunk), 3),
                }
            )
        points = condensed

    duration = points[-1]["end_sec"] if points else 0.0
    return {
        "audio_path": str(path),
        "sample_rate": sample_rate,
        "window_ms": window_ms,
        "duration_sec": round(duration, 3),
        "point_count": len(points),
        "points": points,
    }


def render_waveform_png(profile: dict, path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    width = 1800
    height = 240
    mid = height // 2
    background = (250, 250, 250)
    line_color = (42, 62, 92)
    fill_color = (116, 138, 168)
    baseline_color = (214, 219, 228)
    highlight_color = (36, 41, 54)

    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    draw.line((0, mid, width, mid), fill=baseline_color, width=1)

    points = profile.get("points") or []
    if points:
        duration = float(profile.get("duration_sec", 0.0)) or float(points[-1].get("end_sec", 0.0)) or 1.0
        max_peak = max(int(point.get("peak", 0)) for point in points) or 1
        for point in points:
            start = float(point.get("start_sec", 0.0))
            end = float(point.get("end_sec", start))
            peak = int(point.get("peak", 0))
            x0 = int((start / duration) * width)
            x1 = max(x0 + 1, int((end / duration) * width))
            top = int(mid - (peak / max_peak) * (mid - 12))
            bottom = int(mid + (peak / max_peak) * (mid - 12))
            draw.rectangle((x0, top, x1, bottom), fill=fill_color)
        # highlight the loudest sections to make the graph readable
        sorted_points = sorted(points, key=lambda item: int(item.get("peak", 0)), reverse=True)[: max(3, len(points) // 100)]
        for point in sorted_points:
            start = float(point.get("start_sec", 0.0))
            end = float(point.get("end_sec", start))
            x0 = int((start / duration) * width)
            x1 = max(x0 + 1, int((end / duration) * width))
            peak = int(point.get("peak", 0))
            top = int(mid - (peak / max_peak) * (mid - 12))
            bottom = int(mid + (peak / max_peak) * (mid - 12))
            draw.rectangle((x0, top, x1, bottom), fill=highlight_color)

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def find_waveform_edge(
    audio_path: str,
    target_sec: float,
    direction: str,
    threshold_db: float = -38.0,
    window_ms: int = 20,
    search_pad_sec: float = 0.7,
) -> float:
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")
    if direction not in {"start", "end"}:
        raise HTTPException(status_code=400, detail="direction must be start or end")

    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        if channels != 1 or sample_width != 2:
            raise HTTPException(status_code=500, detail="waveform edge detection needs mono 16-bit PCM wav")
        total_duration = wf.getnframes() / sample_rate
        frame_samples = max(1, int(sample_rate * window_ms / 1000))
        start_sec = max(0.0, target_sec - search_pad_sec)
        end_sec = min(total_duration, target_sec + search_pad_sec)
        windows: list[tuple[float, float, float]] = []
        current = 0.0
        while current < total_duration:
            wf.setpos(int(current * sample_rate))
            chunk = wf.readframes(frame_samples)
            if not chunk:
                break
            rms = audioop.rms(chunk, sample_width)
            db = -120.0 if rms <= 0 else 20.0 * math.log10(rms / 32768.0)
            chunk_end = min(total_duration, current + len(chunk) / (sample_width * channels * sample_rate))
            windows.append((current, chunk_end, db))
            current = chunk_end

    if direction == "start":
        for window_start, window_end, db in windows:
            if window_end < start_sec:
                continue
            if window_start > end_sec:
                break
            if db >= threshold_db:
                return round(max(0.0, window_start), 3)
        return round(target_sec, 3)

    chosen = None
    for window_start, window_end, db in windows:
        if window_end < start_sec:
            continue
        if window_start > end_sec:
            break
        if db >= threshold_db:
            chosen = window_end
    return round(chosen if chosen is not None else target_sec, 3)


def refine_subtitles_with_waveform(
    audio_path: str,
    subtitles: list[dict],
    threshold_db: float = -38.0,
    search_pad_sec: float = 0.7,
    min_duration_sec: float = 0.55,
    project_id: str | None = None,
) -> list[dict]:
    refined: list[dict] = []
    for sub in subtitles:
        item = dict(sub)
        start = float(item.get("aligned_source_start_sec", item.get("source_start_sec", item.get("output_start_sec", 0.0))))
        end = float(item.get("aligned_source_end_sec", item.get("source_end_sec", item.get("output_end_sec", start))))
        original_start = start
        original_end = end
        waveform_start = find_waveform_edge(audio_path, start, "start", threshold_db=threshold_db, search_pad_sec=search_pad_sec)
        waveform_end = find_waveform_edge(audio_path, end, "end", threshold_db=threshold_db, search_pad_sec=search_pad_sec)
        if waveform_end <= waveform_start:
            waveform_end = max(waveform_start + min_duration_sec, end)
        if waveform_end - waveform_start < min_duration_sec:
            waveform_end = waveform_start + min_duration_sec
        item["waveform_refined_source_start_sec"] = round(waveform_start, 3)
        item["waveform_refined_source_end_sec"] = round(waveform_end, 3)
        item["source_start_sec"] = round(waveform_start, 3)
        item["source_end_sec"] = round(waveform_end, 3)
        item["range_relative_start_sec"] = round(waveform_start, 3)
        item["range_relative_end_sec"] = round(waveform_end, 3)
        item["output_start_sec"] = round(waveform_start, 3)
        item["output_end_sec"] = round(waveform_end, 3)
        if waveform_start != start or waveform_end != end:
            item["waveform_adjusted"] = True
            if project_id:
                audit_project_detail_event(
                    project_id,
                    "subtitle.waveform_adjusted",
                    stream="processing",
                    context={
                        "subtitle_id": item.get("id"),
                        "text": item.get("text", ""),
                        "before": {"start_sec": round(original_start, 3), "end_sec": round(original_end, 3)},
                        "after": {"start_sec": round(waveform_start, 3), "end_sec": round(waveform_end, 3)},
                        "threshold_db": threshold_db,
                        "search_pad_sec": search_pad_sec,
                        "min_duration_sec": min_duration_sec,
                    },
                )
        refined.append(item)
    return refined


@lru_cache(maxsize=8)
def load_whisperx_align_model(language_code: str, device: str = "cpu"):
    try:
        import whisperx
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"whisperxを読み込めません: {exc}") from exc

    return whisperx.load_align_model(language_code=language_code, device=device)


def align_subtitles_with_whisperx(project_id: str, audio_path: str, transcript: dict, waveform_profile: dict | None = None) -> dict:
    try:
        import whisperx
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"whisperxを読み込めません: {exc}") from exc

    base = require_project(project_id)
    audio_file = Path(audio_path)
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが存在しません")

    segments = transcript.get("segments") or []
    if not segments:
        raise HTTPException(status_code=400, detail="align対象の字幕がありません")

    language = str(transcript.get("language") or "ja")
    device = "cpu"
    model_a, metadata = load_whisperx_align_model(language, device)
    audio = whisperx.load_audio(str(audio_file))
    aligned = whisperx.align(segments, model_a, metadata, audio, device, return_char_alignments=False)
    aligned_segments = aligned.get("segments") or []
    aligned_subtitles = normalize_subtitle_durations(
        subtitles_from_whisper({"transcription": aligned_segments, "segments": aligned_segments})
    )
    source_subtitles = transcript.get("subtitles") or transcript.get("raw_subtitles") or []
    for subtitle, source_subtitle in zip(aligned_subtitles, source_subtitles):
        for key in ("speaker_id", "speaker_label", "speaker_confidence", "speaker_source_label"):
            if source_subtitle.get(key) is not None:
                subtitle[key] = source_subtitle.get(key)
    detailed_alignments: list[dict] = []
    for idx, (subtitle, aligned_segment) in enumerate(zip(aligned_subtitles, aligned_segments)):
        words = aligned_segment.get("words") or []
        scores = [float(word.get("score", 0.0) or 0.0) for word in words if str(word.get("word", "")).strip()]
        alignment_score = sum(scores) / len(scores) if scores else 0.0
        alignment_duration = max(0.0, float(aligned_segment.get("end", 0.0)) - float(aligned_segment.get("start", 0.0)))
        subtitle["alignment_score"] = round(alignment_score, 3)
        subtitle["alignment_duration_sec"] = round(alignment_duration, 3)
        subtitle["aligned_source_start_sec"] = round(float(aligned_segment.get("start", subtitle.get("source_start_sec", 0.0))), 3)
        subtitle["aligned_source_end_sec"] = round(float(aligned_segment.get("end", subtitle.get("source_end_sec", 0.0))), 3)
        text = str(subtitle.get("text", "")).strip()
        visible_chars = len(re.sub(r"\s+", "", text))
        if visible_chars <= 1 and alignment_duration < 0.5 and alignment_score < 0.2:
            subtitle["enabled"] = False
            subtitle["review_reason"] = "low_confidence_short_segment"
        elif alignment_duration < 0.15 and visible_chars <= 2:
            subtitle["enabled"] = False
            subtitle["review_reason"] = "ultra_short_segment"
        detailed_alignments.append(
            {
                "subtitle_id": subtitle.get("id"),
                "text": subtitle.get("text", ""),
                "source_start_sec": round(float(subtitle.get("source_start_sec", 0.0)), 3),
                "source_end_sec": round(float(subtitle.get("source_end_sec", 0.0)), 3),
                "aligned_source_start_sec": subtitle["aligned_source_start_sec"],
                "aligned_source_end_sec": subtitle["aligned_source_end_sec"],
                "alignment_score": subtitle["alignment_score"],
                "alignment_duration_sec": subtitle["alignment_duration_sec"],
                "enabled": subtitle.get("enabled", True),
                "review_reason": subtitle.get("review_reason"),
            }
        )
    waveform_profile = waveform_profile or build_waveform_analysis(audio_path)
    waveform_json_path = base / "analysis" / "waveform.json"
    waveform_png_path = base / "analysis" / "waveform.png"
    waveform_json_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(waveform_json_path, waveform_profile)
    render_waveform_png(waveform_profile, waveform_png_path)
    waveform_refined_subtitles = refine_subtitles_with_waveform(audio_path, aligned_subtitles, project_id=project_id)
    whisperx_srt_path = base / "subtitles" / "whisperx_aligned.srt"
    write_srt(waveform_refined_subtitles, whisperx_srt_path)
    audit_project_detail_event(
        project_id,
        "transcribe.alignment_summary",
        stream="processing",
        context={
            "subtitle_count": len(aligned_subtitles),
            "enabled_count": sum(1 for item in aligned_subtitles if item.get("enabled", True)),
            "disabled_count": sum(1 for item in aligned_subtitles if item.get("enabled", True) is False),
            "waveform_adjusted_count": sum(1 for item in waveform_refined_subtitles if item.get("waveform_adjusted")),
            "waveform_threshold_db": -38.0,
            "waveform_search_pad_sec": 0.7,
            "waveform_min_duration_sec": 0.55,
            "details": detailed_alignments,
        },
    )

    result = dict(transcript)
    result["alignment_engine"] = "whisperx"
    result["alignment_language"] = language
    result["aligned_transcription"] = aligned_segments
    result["aligned_segments"] = aligned_segments
    result["aligned_subtitles"] = aligned_subtitles
    result["waveform"] = waveform_profile
    result["waveform_analysis_path"] = str(waveform_json_path)
    result["waveform_image_path"] = str(waveform_png_path)
    result["waveform_refined_subtitles"] = waveform_refined_subtitles
    result["waveform_refined"] = True
    result["whisperx_aligned_srt_path"] = str(whisperx_srt_path)
    result["subtitles"] = waveform_refined_subtitles
    return result


def detect_speech_intervals(
    audio_path: str,
    threshold_db: float = -40.0,
    frame_ms: int = 30,
    min_gap_ms: int = 120,
    min_speech_ms: int = 150,
) -> list[dict]:
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="音声ファイルが見つかりません")

    raw_intervals: list[tuple[float, float]] = []
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        if channels != 1 or sample_width != 2:
            raise HTTPException(status_code=500, detail="speech interval detection needs mono 16-bit PCM wav")
        frame_samples = max(1, int(sample_rate * frame_ms / 1000))
        total_frames = wf.getnframes()
        active_start: float | None = None
        active_end: float | None = None
        for frame_index in range(0, total_frames, frame_samples):
            chunk = wf.readframes(frame_samples)
            if not chunk:
                break
            rms = audioop.rms(chunk, sample_width)
            db = -120.0 if rms <= 0 else 20.0 * math.log10(rms / 32768.0)
            start_sec = frame_index / sample_rate
            end_frames = frame_index + len(chunk) // (sample_width * channels)
            end_sec = min(total_frames / sample_rate, end_frames / sample_rate)
            if db >= threshold_db:
                if active_start is None:
                    active_start = start_sec
                active_end = end_sec
            else:
                if active_start is not None and active_end is not None and (active_end - active_start) >= min_speech_ms / 1000.0:
                    raw_intervals.append((active_start, active_end))
                active_start = None
                active_end = None
        if active_start is not None and active_end is not None and (active_end - active_start) >= min_speech_ms / 1000.0:
            raw_intervals.append((active_start, active_end))

    merged: list[tuple[float, float]] = []
    for start, end in raw_intervals:
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        if start - prev_end <= min_gap_ms / 1000.0:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return [{"start_sec": round(start, 3), "end_sec": round(end, 3)} for start, end in merged]


def split_text_for_windows(text: str, window_count: int) -> list[str]:
    cleaned = text.strip()
    if window_count <= 1 or not cleaned:
        return [cleaned]
    if " " in cleaned:
        words = cleaned.split()
        if window_count >= len(words):
            return words
        size = math.ceil(len(words) / window_count)
        return [" ".join(words[i : i + size]).strip() for i in range(0, len(words), size) if " ".join(words[i : i + size]).strip()]
    chars = list(cleaned)
    if window_count >= len(chars):
        return chars
    size = math.ceil(len(chars) / window_count)
    return ["".join(chars[i : i + size]).strip() for i in range(0, len(chars), size) if "".join(chars[i : i + size]).strip()]


def refine_subtitles_with_speech_intervals(subtitles: list[dict], speech_intervals: list[dict]) -> list[dict]:
    if not speech_intervals:
        return subtitles
    refined: list[dict] = []
    for sub in subtitles:
        start = float(sub.get("source_start_sec", sub.get("output_start_sec", 0.0)))
        end = float(sub.get("source_end_sec", sub.get("output_end_sec", start)))
        overlaps = [
            (max(start, float(interval["start_sec"])), min(end, float(interval["end_sec"])))
            for interval in speech_intervals
            if min(end, float(interval["end_sec"])) > max(start, float(interval["start_sec"]))
        ]
        if not overlaps:
            refined.append(sub)
            continue
        if len(overlaps) == 1:
            clipped = dict(sub)
            clipped["source_start_sec"] = overlaps[0][0]
            clipped["source_end_sec"] = overlaps[0][1]
            clipped["range_relative_start_sec"] = overlaps[0][0]
            clipped["range_relative_end_sec"] = overlaps[0][1]
            clipped["output_start_sec"] = overlaps[0][0]
            clipped["output_end_sec"] = overlaps[0][1]
            refined.append(clipped)
            continue

        pieces = split_text_for_windows(str(sub.get("text", "")), len(overlaps))
        total = sum(max(0.0, end - start) for start, end in overlaps) or 1.0
        cursor = 0
        for idx, (window_start, window_end) in enumerate(overlaps):
            window_duration = max(0.05, window_end - window_start)
            take = max(1, round(len(pieces) * (window_duration / total))) if pieces else 1
            if idx == len(overlaps) - 1:
                take = len(pieces) - cursor
            part_text = " ".join(pieces[cursor : cursor + take]).strip() if " " in str(sub.get("text", "")) else "".join(pieces[cursor : cursor + take]).strip()
            cursor += take
            if not part_text:
                part_text = str(sub.get("text", "")).strip()
            clipped = dict(sub)
            clipped["id"] = f"{sub.get('id', 'sub')}_{idx + 1}"
            clipped["source_start_sec"] = window_start
            clipped["source_end_sec"] = window_end
            clipped["range_relative_start_sec"] = window_start
            clipped["range_relative_end_sec"] = window_end
            clipped["output_start_sec"] = window_start
            clipped["output_end_sec"] = window_end
            clipped["text"] = part_text
            refined.append(clipped)
    for idx, item in enumerate(refined, start=1):
        item["id"] = item.get("id") or f"sub_{idx:04}"
    return refined


def resolve_whisper_cpp_model(model: str) -> Path:
    candidate = Path(model)
    if candidate.exists():
        return candidate
    normalized = model.strip()
    names = [
        normalized,
        f"ggml-{normalized}.bin",
        f"{normalized}.bin",
    ]
    for name in names:
        path = WHISPER_CPP_MODELS / name
        if path.exists():
            return path
    available = ", ".join(p.name for p in WHISPER_CPP_MODELS.glob("*.bin")) or "なし"
    raise HTTPException(status_code=404, detail=f"whisper.cppモデルが見つかりません: {model}。利用可能: {available}")


def resolve_whisper_cpp_vad_model() -> Path:
    if WHISPER_CPP_VAD_MODEL.exists():
        return WHISPER_CPP_VAD_MODEL
    available = ", ".join(p.name for p in WHISPER_CPP_MODELS.glob("*.bin")) or "なし"
    raise HTTPException(status_code=404, detail=f"whisper.cpp VADモデルが見つかりません: {WHISPER_CPP_VAD_MODEL.name}。利用可能: {available}")


def transcribe_with_whisper_cpp(project_id: str, audio_path: str, language: str, model: str, compute_profile: str = "auto") -> dict:
    base = require_project(project_id)
    if not WHISPER_CPP_EXE.exists():
        raise HTTPException(status_code=500, detail=f"whisper.cpp実行ファイルが見つかりません: {WHISPER_CPP_EXE}")
    model_path = resolve_whisper_cpp_model(model)
    output_base = base / "temp" / "whisper_cpp_result"
    json_path = output_base.with_suffix(".json")
    if json_path.exists():
        json_path.unlink()
    args = [
            path_for_cli(WHISPER_CPP_EXE),
            "-m",
            path_for_cli(model_path),
            "-f",
            path_for_cli(audio_path),
            "-l",
            language or "ja",
            "-sow",
            "-ojf",
            "-nf",
            "-mc",
            "0",
            "-et",
            "2.80",
            "-nfa",
            "-lpt",
            "-1.00",
            "-nth",
            "0.35",
            "-of",
            path_for_cli(output_base),
        ]
    if normalize_compute_profile(compute_profile) == "cpu":
        args.insert(1, "-ng")
    try:
        proc = run_command(
            args,
            base / "temp" / "logs" / "whisper_cpp.log",
        )
    except HTTPException as exc:
        raise_if_whisper_cpp_oom(exc, "whisper.cpp", str(model_path))
    if not json_path.exists():
        raise HTTPException(status_code=500, detail="whisper.cppのJSON出力が見つかりません")
    raw = json.loads(json_path.read_bytes().decode("utf-8", errors="replace"))
    device = infer_whisper_cpp_device(proc.stderr)
    transcription = raw.get("transcription", [])
    segments: list[dict] = []
    for item in transcription:
        offsets = item.get("offsets", {})
        tokens = item.get("tokens") or []
        token_starts = [float(token.get("offsets", {}).get("from", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        token_ends = [float(token.get("offsets", {}).get("to", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        start = min(token_starts) if token_starts else float(offsets.get("from", 0)) / 1000.0
        end = max(token_ends) if token_ends else float(offsets.get("to", 0)) / 1000.0
        segments.append({"start": start, "end": end, "text": str(item.get("text", "")).strip()})
    return {
        "language": raw.get("result", {}).get("language", language),
        "engine": "whisper.cpp",
        "model": str(model_path),
        "device": device,
        "gpu_used": device == "vulkan",
        "transcription": transcription,
        "segments": segments,
        "raw": raw,
    }


def transcribe_with_whisper_cpp_vad(
    project_id: str,
    audio_path: str,
    language: str,
    model: str,
    compute_profile: str = "auto",
    vad_threshold: float = 0.25,
    vad_min_speech_duration_ms: int = 100,
    vad_min_silence_duration_ms: int = 80,
    vad_speech_pad_ms: int = 50,
) -> dict:
    base = require_project(project_id)
    if not WHISPER_CPP_EXE.exists():
        raise HTTPException(status_code=500, detail=f"whisper.cpp実行ファイルが見つかりません: {WHISPER_CPP_EXE}")
    model_path = resolve_whisper_cpp_model(model)
    vad_model_path = resolve_whisper_cpp_vad_model()
    output_base = base / "temp" / "whisper_cpp_vad_result"
    json_path = output_base.with_suffix(".json")
    if json_path.exists():
        json_path.unlink()
    args = [
            path_for_cli(WHISPER_CPP_EXE),
            "-m",
            path_for_cli(model_path),
            "-f",
            path_for_cli(audio_path),
            "-l",
            language or "ja",
            "-sow",
            "-ojf",
            "-nf",
            "-mc",
            "0",
            "-et",
            "2.80",
            "-nfa",
            "-lpt",
            "-1.00",
            "-nth",
            "0.35",
            "--vad",
            "-vm",
            path_for_cli(vad_model_path),
            "-vt",
            f"{float(vad_threshold):.2f}",
            "-vspd",
            str(int(vad_min_speech_duration_ms)),
            "-vsd",
            str(int(vad_min_silence_duration_ms)),
            "-vp",
            str(int(vad_speech_pad_ms)),
            "-of",
            path_for_cli(output_base),
        ]
    if normalize_compute_profile(compute_profile) == "cpu":
        args.insert(1, "-ng")
    try:
        proc = run_command(
            args,
            base / "temp" / "logs" / "whisper_cpp_vad.log",
        )
    except HTTPException as exc:
        raise_if_whisper_cpp_oom(exc, "whisper.cpp-vad", str(model_path))
    if not json_path.exists():
        raise HTTPException(status_code=500, detail="whisper.cpp VADのJSON出力が見つかりません")
    raw = json.loads(json_path.read_bytes().decode("utf-8", errors="replace"))
    device = infer_whisper_cpp_device(proc.stderr)
    transcription = []
    for item in raw.get("transcription", []):
        adjusted = dict(item)
        base_offset_ms = int(float(adjusted.get("offsets", {}).get("from", 0) or 0))
        tokens = []
        for token in adjusted.get("tokens") or []:
            token_offsets = dict(token.get("offsets", {}))
            if "from" in token_offsets:
                token_offsets["from"] = int(float(token_offsets.get("from", 0) or 0) + base_offset_ms)
            if "to" in token_offsets:
                token_offsets["to"] = int(float(token_offsets.get("to", 0) or 0) + base_offset_ms)
            token = dict(token)
            token["offsets"] = token_offsets
            timestamps = dict(token.get("timestamps", {}))
            if "from" in timestamps:
                timestamps["from"] = format_srt_time(float(token_offsets.get("from", 0)) / 1000.0)
            if "to" in timestamps:
                timestamps["to"] = format_srt_time(float(token_offsets.get("to", 0)) / 1000.0)
            token["timestamps"] = timestamps
            tokens.append(token)
        adjusted["tokens"] = tokens
        transcription.append(adjusted)
    segments: list[dict] = []
    for item in transcription:
        offsets = item.get("offsets", {})
        tokens = item.get("tokens") or []
        token_starts = [float(token.get("offsets", {}).get("from", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        token_ends = [float(token.get("offsets", {}).get("to", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        start = min(token_starts) if token_starts else float(offsets.get("from", 0)) / 1000.0
        end = max(token_ends) if token_ends else float(offsets.get("to", 0)) / 1000.0
        segments.append({"start": start, "end": end, "text": str(item.get("text", "")).strip()})
    return {
        "language": raw.get("result", {}).get("language", language),
        "engine": "whisper.cpp-vad",
        "model": str(model_path),
        "vad_model": str(vad_model_path),
        "device": device,
        "gpu_used": device == "vulkan",
        "vad_threshold": float(vad_threshold),
        "vad_min_speech_duration_ms": int(vad_min_speech_duration_ms),
        "vad_min_silence_duration_ms": int(vad_min_silence_duration_ms),
        "vad_speech_pad_ms": int(vad_speech_pad_ms),
        "transcription": transcription,
        "segments": segments,
        "raw": raw,
    }


def _render_plan_media(project_id: str, plan: dict, preview: bool = False, burn_subtitles: bool = False, persist_final_plan: bool = False) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    settings = plan.get("settings", {})
    transcript_path = base / "transcript" / "transcript.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.exists() else {}
    segments = [s for s in plan.get("segments", []) if s.get("enabled", True)]
    if not segments:
        raise HTTPException(status_code=400, detail="出力対象の区間がありません")
    segment_dir = base / "temp" / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_files: list[Path] = []
    source = project_source_video(project_id)
    output_audio_mode = str(plan.get("settings", {}).get("output_audio_mode", transcript.get("output_audio_mode", "original"))).strip().lower()
    isolated_audio_source = None
    if output_audio_mode == "isolated_voice":
        candidate = transcript.get("voice_isolated_audio_path") or transcript.get("vad_audio_path") or transcript.get("whisper_audio_path")
        if candidate and Path(candidate).exists():
            isolated_audio_source = Path(candidate)
        else:
            output_audio_mode = "original"
    for idx, segment in enumerate(segments, start=1):
        out = segment_dir / f"segment_{idx:04}.mp4"
        video_start = float(segment["source_start_sec"])
        video_end = float(segment["source_end_sec"])
        args = [
            "ffmpeg",
            "-y",
        ]
        if isolated_audio_source is None:
            args += [
                "-ss",
                f"{video_start:.3f}",
                "-to",
                f"{video_end:.3f}",
                "-i",
                str(source),
            ]
            if preview:
                args += ["-vf", "scale='min(1280,iw)':-2", "-preset", "ultrafast", "-crf", "30"]
            else:
                args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
            args += ["-c:a", "aac", "-movflags", "+faststart", str(out)]
        else:
            audio_start = float(segment.get("range_relative_start_sec", 0.0))
            audio_end = float(segment.get("range_relative_end_sec", audio_start))
            args += [
                "-ss",
                f"{video_start:.3f}",
                "-to",
                f"{video_end:.3f}",
                "-i",
                str(source),
                "-ss",
                f"{audio_start:.3f}",
                "-to",
                f"{audio_end:.3f}",
                "-i",
                str(isolated_audio_source),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
            if preview:
                args += ["-vf", "scale='min(1280,iw)':-2", "-preset", "ultrafast", "-crf", "30"]
            else:
                args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
            args += ["-c:a", "aac", "-movflags", "+faststart", str(out)]
        run_command(args, base / "temp" / "logs" / f"segment_{idx:04}.log")
        segment_files.append(out)

    concat_list = base / "temp" / "segments" / "concat.txt"
    atomic_write_text(concat_list, "".join(f"file '{p.as_posix()}'\n" for p in segment_files))
    output_dir = base / ("preview" if preview else "output")
    video_out = output_dir / ("preview_low.mp4" if preview else "final.mp4")
    run_command(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(video_out)],
        base / "temp" / "logs" / ("preview_concat.log" if preview else "final_concat.log"),
    )
    srt_out = output_dir / ("preview.srt" if preview else "final.srt")
    write_srt(plan.get("subtitles", []), srt_out)
    if burn_subtitles and srt_out.exists():
        burn_srt_out = srt_out.with_suffix(".burn.srt")
        write_srt(plan.get("subtitles", []), burn_srt_out, strict_burn=True)
        burned_out = video_out.with_name(f"{video_out.stem}_burned{video_out.suffix}")
        burn_args = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_out),
            "-vf",
            ffmpeg_subtitles_filter_with_style(burn_srt_out, settings),
            "-c:v",
            "libx264",
        ]
        if preview:
            burn_args += ["-preset", "ultrafast", "-crf", "30"]
        else:
            burn_args += ["-preset", "veryfast", "-crf", "20"]
        burn_args += ["-c:a", "copy", "-movflags", "+faststart", str(burned_out)]
        run_command(
            burn_args,
            base / "temp" / "logs" / ("preview_burn.log" if preview else "final_burn.log"),
        )
        burned_out.replace(video_out)
        try:
            burn_srt_out.unlink()
        except Exception:
            pass
    if not preview:
        normalized_plan = normalize_edit_plan_source_video(project_id, plan)
        if persist_final_plan:
            atomic_write_json(output_dir / "edit_plan_final.json", normalized_plan)
    result_key = "preview_video_path" if preview else "video_path"
    audit_project_event(project_id, "render_from_plan", context={"preview": preview, "burn_subtitles": burn_subtitles, "segment_count": len(segments), "output_audio_mode": output_audio_mode, "audio_mode_resolved": "isolated_voice" if isolated_audio_source else "original"})
    return {result_key: str(video_out), "srt_path": str(srt_out), "video_url": f"/api/projects/{project_id}/media/{'preview' if preview else 'output'}/{video_out.name}"}


def render_from_plan(project_id: str, preview: bool = False, burn_subtitles: bool = False) -> dict:
    base = require_project(project_id)
    plan = load_project_edit_plan(project_id)
    return _render_plan_media(project_id, plan, preview=preview, burn_subtitles=burn_subtitles, persist_final_plan=not preview)


def render_from_plan_data(project_id: str, plan: dict, preview: bool = True, burn_subtitles: bool = False) -> dict:
    base = require_project(project_id)
    (base / "temp" / "segments").mkdir(parents=True, exist_ok=True)
    return _render_plan_media(project_id, plan, preview=preview, burn_subtitles=burn_subtitles, persist_final_plan=False)

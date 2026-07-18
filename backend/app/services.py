from __future__ import annotations

import json
import audioop
import copy
import contextlib
import hashlib
import io
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
from .edit_plan import build_edit_plan, map_subtitles_to_output
from .srt import apply_vad_subtitle_corrections, filter_repetitive_hallucinations, normalize_subtitle_durations, parse_srt, subtitles_from_whisper, write_srt
from .timecode import format_srt_time

ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = ROOT / "projects"
FRONTEND_DIR = ROOT / "frontend"
WHISPER_CPP_DIR = ROOT / "tools" / "whisper.cpp"
WHISPER_CPP_EXE = WHISPER_CPP_DIR / "bin" / "whisper-cli.exe"
WHISPER_CPP_MODELS = WHISPER_CPP_DIR / "models"
WHISPER_CPP_VAD_MODEL = WHISPER_CPP_MODELS / "ggml-silero-v6.2.0.bin"
DOCS_DIR = ROOT / "docs"
EMOTION_PRESETS_SAMPLE = DOCS_DIR / "emotion_presets.sample.json"
SUBTITLE_STYLE_PRESETS_SAMPLE = DOCS_DIR / "subtitle_style_presets.sample.json"
SCENES_SAMPLE = DOCS_DIR / "scenes.sample.json"
DECORATION_PRESETS_SAMPLE = DOCS_DIR / "decoration_presets.sample.json"
APP_DATA_DIR = ROOT / "data"
DECORATION_PRESETS_SHARED = APP_DATA_DIR / "shared" / "decoration_presets.json"
TRANSCRIPTION_RUNTIME_HISTORY = APP_DATA_DIR / "shared" / "transcription_runtime_history.json"
DECORATION_PRESETS_SHARED_LEGACY = PROJECTS_DIR / "_shared" / "decoration_presets.json"
WAVEFORM_MAX_POINTS = 1800
MAX_HISTORY_VERSIONS = 12

DEFAULT_ASS_SUBTITLE_STYLE = {
    "preset_id": "ass_standard",
    "font_name": "Noto Sans JP",
    "font_size": 44,
    "primary_color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 3.0,
    "shadow_depth": 1.0,
    "bold": True,
    "italic": False,
    "alignment": 2,
    "margin_l": 60,
    "margin_r": 60,
    "margin_v": 48,
    "spacing": 0.0,
}


def normalize_ass_subtitle_style(value: dict | None, *, include_enabled: bool = False) -> dict:
    raw = value if isinstance(value, dict) else {}

    def number(key: str, fallback: float, low: float, high: float) -> float:
        try:
            return max(low, min(high, float(raw.get(key, fallback))))
        except (TypeError, ValueError):
            return fallback

    def color(key: str, fallback: str) -> str:
        candidate = str(raw.get(key, fallback) or fallback).strip().upper()
        return candidate if re.fullmatch(r"#[0-9A-F]{6}", candidate) else fallback

    font_name = clean_font_family_name(str(raw.get("font_name") or DEFAULT_ASS_SUBTITLE_STYLE["font_name"]))[:120]
    result = {
        "preset_id": str(raw.get("preset_id") or "ass_custom")[:80],
        "font_name": font_name or DEFAULT_ASS_SUBTITLE_STYLE["font_name"],
        "font_size": int(round(number("font_size", 44, 8, 160))),
        "primary_color": color("primary_color", "#FFFFFF"),
        "outline_color": color("outline_color", "#000000"),
        "outline_width": round(number("outline_width", 3.0, 0, 20), 2),
        "shadow_depth": round(number("shadow_depth", 1.0, 0, 20), 2),
        "bold": bool(raw.get("bold", True)),
        "italic": bool(raw.get("italic", False)),
        "alignment": int(round(number("alignment", 2, 1, 9))),
        "margin_l": int(round(number("margin_l", 60, 0, 1000))),
        "margin_r": int(round(number("margin_r", 60, 0, 1000))),
        "margin_v": int(round(number("margin_v", 48, 0, 1000))),
        "spacing": round(number("spacing", 0.0, -10, 40), 2),
    }
    if include_enabled:
        result["enabled"] = bool(raw.get("enabled", False))
    return result


@lru_cache(maxsize=1)
def list_system_fonts() -> list[str]:
    names: set[str] = set()
    font_dirs = (
        [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Microsoft" / "Windows" / "Fonts",
        ]
        if os.name == "nt"
        else [Path("/usr/share/fonts"), Path.home() / ".fonts"]
    )
    for font_dir in font_dirs:
        if not font_dir.exists():
            continue
        for path in font_dir.rglob("*"):
            if path.suffix.lower() not in {".ttf", ".otf", ".ttc"} or not font_file_has_japanese_glyphs(path):
                continue
            internal_names = japanese_font_family_names_from_file(path)
            if internal_names:
                names.update(internal_names)
            else:
                names.add(path.stem.replace("_", " ").strip())
    for fallback in ["Noto Sans JP", "Noto Serif JP", "Meiryo", "Yu Gothic", "Yu Mincho", "BIZ UDPGothic", "BIZ UDMincho"]:
        if find_font_file(fallback):
            names.add(fallback)
    return sorted(names, key=lambda item: item.lower())


def clean_font_family_name(value: str | None) -> str:
    cleaned = str(value or "").strip().strip(";")
    cleaned = re.sub(r"\s*\((TrueType|OpenType|Type 1)\)\s*;?\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def font_family_candidates(value: str | None) -> list[str]:
    cleaned = clean_font_family_name(value)
    candidates = [cleaned] if cleaned else []
    for part in re.split(r"\s*&\s*", cleaned):
        part = clean_font_family_name(part)
        if part and part not in candidates:
            candidates.append(part)
    return candidates


def font_file_has_japanese_glyphs(path: Path) -> bool:
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except Exception:
        return False
    sample_codepoints = {ord("あ"), ord("ア"), ord("漢")}
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            fonts = TTCollection(str(path)).fonts if path.suffix.lower() == ".ttc" else [TTFont(str(path), lazy=True)]
            for font in fonts:
                cmap = font.getBestCmap() or {}
                if any(codepoint in cmap for codepoint in sample_codepoints):
                    return True
    except Exception:
        return False
    return False


@lru_cache(maxsize=4096)
def japanese_font_family_names_from_file(path: Path) -> list[str]:
    try:
        from fontTools.ttLib import TTCollection, TTFont
    except Exception:
        return []
    names: set[str] = set()
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            fonts = TTCollection(str(path)).fonts if path.suffix.lower() == ".ttc" else [TTFont(str(path), lazy=True)]
            for font in fonts:
                for record in font["name"].names:
                    if record.nameID not in {1, 4, 16}:
                        continue
                    try:
                        value = record.toUnicode().strip()
                    except Exception:
                        continue
                    if value:
                        names.add(clean_font_family_name(value))
    except Exception:
        return []
    return sorted(names, key=lambda item: item.lower())


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


def read_json_repairing_extra_data(path: Path) -> dict | list:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        try:
            data, end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            raise exc
        if not text[end:].strip():
            return data
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = path.with_name(f"{path.name}.corrupt-{timestamp}")
        try:
            shutil.copy2(path, backup_path)
        except Exception:
            backup_path = None
        atomic_write_json(path, data)
        audit_event(
            "json.repaired_extra_data",
            status="warning",
            context={
                "path": str(path),
                "backup_path": str(backup_path) if backup_path else "",
                "extra_chars": len(text) - end,
            },
        )
        return data


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise HTTPException(status_code=500, detail=f"{name} が見つかりません。PATHに追加してください。")


def run_command(args: list[str], log_path: Path | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path:
        proc = subprocess.run(args, text=True, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd or ROOT)
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
            cwd=cwd or ROOT,
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


def parse_ffmpeg_timecode(value: str) -> float:
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", text)
    if not match:
        return 0.0
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2) or 0)
    seconds = float(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def latest_ffmpeg_progress_from_log(log_path: Path) -> dict:
    if not log_path.exists():
        return {}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    matches = list(
        re.finditer(
            r"frame=\s*(?P<frame>\d+).*?time=(?P<time>\d+:\d{2}:\d{2}(?:\.\d+)?).*?speed=\s*(?P<speed>[0-9.]+)x(?:\s+elapsed=(?P<elapsed>\d+:\d{2}:\d{2}(?:\.\d+)?))?",
            text,
            flags=re.DOTALL,
        )
    )
    if not matches:
        return {}
    match = matches[-1]
    return {
        "frame": int(match.group("frame")),
        "current_sec": parse_ffmpeg_timecode(match.group("time")),
        "speed": float(match.group("speed") or 0.0),
        "elapsed_sec": parse_ffmpeg_timecode(match.group("elapsed") or "") if match.group("elapsed") else None,
        "log_path": str(log_path),
        "log_updated_at": datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def _audio_duration_sec(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            return wav_file.getnframes() / max(1, wav_file.getframerate())
    except Exception:
        return 0.0


def _transcription_history_key(
    engine: str,
    model: str,
    compute_profile: str,
    voice_isolation_enabled: bool,
    use_whisperx_alignment: bool,
) -> str:
    return ":".join(
        [
            str(engine or "unknown").lower(),
            str(model or "unknown").lower(),
            str(compute_profile or "auto").lower(),
            "voice" if voice_isolation_enabled else "original",
            "whisperx" if use_whisperx_alignment else "standard",
        ]
    )


def estimate_transcription_duration(
    duration_sec: float,
    engine: str,
    model: str,
    compute_profile: str,
    voice_isolation_enabled: bool,
    use_whisperx_alignment: bool,
) -> tuple[float, str, str]:
    duration_sec = max(1.0, float(duration_sec or 0.0))
    history_key = _transcription_history_key(engine, model, compute_profile, voice_isolation_enabled, use_whisperx_alignment)
    try:
        history = read_json_repairing_extra_data(TRANSCRIPTION_RUNTIME_HISTORY) if TRANSCRIPTION_RUNTIME_HISTORY.exists() else {}
    except Exception:
        history = {}
    samples = history.get(history_key, []) if isinstance(history, dict) else []
    rtfs = sorted(float(item.get("rtf", 0.0) or 0.0) for item in samples if float(item.get("rtf", 0.0) or 0.0) > 0)
    if rtfs:
        median_rtf = rtfs[len(rtfs) // 2]
        return max(15.0, duration_sec * median_rtf), "history", history_key

    model_name = str(model or "small").lower()
    model_group = "large" if "large" in model_name else model_name
    profile = str(compute_profile or "auto").lower()
    if profile == "cpu":
        rtf_table = {"base": 0.45, "small": 0.85, "medium": 1.55, "large": 2.5}
    else:
        rtf_table = {"base": 0.08, "small": 0.16, "medium": 0.32, "large": 0.58}
    rtf = rtf_table.get(model_group, 0.4)
    if not str(engine or "").startswith("whisper.cpp"):
        rtf *= 1.35
    if voice_isolation_enabled:
        rtf += 0.55
    if use_whisperx_alignment:
        rtf += 0.8
    return max(30.0, duration_sec * rtf + 20.0), "profile", history_key


def begin_transcription_progress(
    project_id: str,
    audio_path: Path,
    engine: str,
    model: str,
    compute_profile: str,
    voice_isolation_enabled: bool,
    use_whisperx_alignment: bool,
) -> None:
    base = require_project(project_id)
    duration_sec = _audio_duration_sec(audio_path)
    estimated_total_sec, estimate_source, history_key = estimate_transcription_duration(
        duration_sec, engine, model, compute_profile, voice_isolation_enabled, use_whisperx_alignment
    )
    now = time.time()
    atomic_write_json(
        base / "temp" / "transcription_progress.json",
        {
            "status": "running",
            "stage": "文字起こし準備",
            "stage_id": "transcription_prepare",
            "started_at_epoch": now,
            "stage_started_at_epoch": now,
            "audio_duration_sec": duration_sec,
            "estimated_total_sec": estimated_total_sec,
            "estimate_source": estimate_source,
            "history_key": history_key,
            "engine": engine,
            "model": model,
            "compute_profile": compute_profile,
            "percent_start": 0.0,
            "percent_end": 3.0,
            "stage_estimate_sec": max(2.0, estimated_total_sec * 0.03),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def update_transcription_progress(
    project_id: str,
    stage: str,
    stage_id: str,
    percent_start: float,
    percent_end: float,
    estimated_fraction: float,
) -> None:
    base = require_project(project_id)
    path = base / "temp" / "transcription_progress.json"
    try:
        progress = read_json_repairing_extra_data(path) if path.exists() else {}
    except Exception:
        progress = {}
    if not isinstance(progress, dict) or progress.get("status") != "running":
        return
    estimated_total_sec = max(1.0, float(progress.get("estimated_total_sec", 1.0) or 1.0))
    progress.update(
        {
            "stage": stage,
            "stage_id": stage_id,
            "stage_started_at_epoch": time.time(),
            "percent_start": float(percent_start),
            "percent_end": float(percent_end),
            "stage_estimate_sec": max(1.0, estimated_total_sec * max(0.01, float(estimated_fraction))),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    atomic_write_json(path, progress)


def finish_transcription_progress(project_id: str, *, success: bool, error: str | None = None) -> None:
    base = require_project(project_id)
    path = base / "temp" / "transcription_progress.json"
    try:
        progress = read_json_repairing_extra_data(path) if path.exists() else {}
    except Exception:
        progress = {}
    if not isinstance(progress, dict) or not progress or progress.get("status") != "running":
        return
    elapsed_sec = max(0.0, time.time() - float(progress.get("started_at_epoch", time.time()) or time.time()))
    progress.update(
        {
            "status": "completed" if success else "failed",
            "stage": "字幕作成完了" if success else "字幕作成失敗",
            "stage_id": "transcription_complete" if success else "transcription_failed",
            "elapsed_sec": elapsed_sec,
            "percent_start": 100.0 if success else float(progress.get("percent_start", 0.0) or 0.0),
            "percent_end": 100.0 if success else float(progress.get("percent_end", 0.0) or 0.0),
            "error": str(error or "")[:1000] if not success else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    atomic_write_json(path, progress)
    duration_sec = float(progress.get("audio_duration_sec", 0.0) or 0.0)
    history_key = str(progress.get("history_key") or "")
    if success and duration_sec > 0 and elapsed_sec > 0 and history_key:
        TRANSCRIPTION_RUNTIME_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        try:
            history = read_json_repairing_extra_data(TRANSCRIPTION_RUNTIME_HISTORY) if TRANSCRIPTION_RUNTIME_HISTORY.exists() else {}
        except Exception:
            history = {}
        if not isinstance(history, dict):
            history = {}
        samples = list(history.get(history_key) or [])
        samples.append(
            {
                "rtf": elapsed_sec / duration_sec,
                "elapsed_sec": elapsed_sec,
                "audio_duration_sec": duration_sec,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        history[history_key] = samples[-8:]
        atomic_write_json(TRANSCRIPTION_RUNTIME_HISTORY, history)


def project_processing_progress(project_id: str) -> dict:
    base = require_project(project_id)
    transcription_progress_path = base / "temp" / "transcription_progress.json"
    if transcription_progress_path.exists():
        try:
            transcription_progress = read_json_repairing_extra_data(transcription_progress_path)
        except Exception:
            transcription_progress = {}
        if isinstance(transcription_progress, dict) and transcription_progress.get("status") == "running":
            now = time.time()
            started_at = float(transcription_progress.get("started_at_epoch", now) or now)
            stage_started_at = float(transcription_progress.get("stage_started_at_epoch", started_at) or started_at)
            elapsed_sec = max(0.0, now - started_at)
            stage_elapsed_sec = max(0.0, now - stage_started_at)
            estimated_total_sec = max(1.0, float(transcription_progress.get("estimated_total_sec", 1.0) or 1.0))
            stage_estimate_sec = max(1.0, float(transcription_progress.get("stage_estimate_sec", 1.0) or 1.0))
            percent_start = max(0.0, min(99.0, float(transcription_progress.get("percent_start", 0.0) or 0.0)))
            percent_end = max(percent_start, min(99.5, float(transcription_progress.get("percent_end", percent_start) or percent_start)))
            stage_fraction = min(0.97, stage_elapsed_sec / stage_estimate_sec)
            percent = percent_start + (percent_end - percent_start) * stage_fraction
            future_sec = estimated_total_sec * max(0.0, 1.0 - percent_end / 100.0)
            stage_remaining_sec = (
                stage_estimate_sec - stage_elapsed_sec
                if stage_elapsed_sec <= stage_estimate_sec
                else max(30.0, stage_elapsed_sec * 0.15)
            )
            stale_limit_sec = max(3600.0, estimated_total_sec * 4.0)
            active = elapsed_sec < stale_limit_sec
            return {
                **transcription_progress,
                "active": active,
                "elapsed_sec": elapsed_sec,
                "stage_elapsed_sec": stage_elapsed_sec,
                "percent": percent,
                "remaining_sec": max(1.0, stage_remaining_sec + future_sec) if active else None,
                "speed": 0.0,
                "estimate": True,
            }
    logs_dir = base / "temp" / "logs"
    output_video = base / "output" / "final.mp4"
    candidates = [
        ("final_burn.log", "装飾焼き込み", "decorated_burn"),
        ("final_concat.log", "カット動画結合", "concat"),
        ("preview_render.log", "仮出力", "preview"),
        ("decoration_preview.log", "装飾プレビュー", "decoration_preview"),
    ]
    active_logs = []
    for file_name, stage_label, stage_id in candidates:
        path = logs_dir / file_name
        if path.exists():
            active_logs.append((path.stat().st_mtime, path, stage_label, stage_id))
    segment_logs = sorted(logs_dir.glob("segment_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    if segment_logs:
        active_logs.append((segment_logs[0].stat().st_mtime, segment_logs[0], "カット区間エンコード", "segment_encode"))
    if not active_logs:
        return {"active": False, "stage": "待機中"}
    _, log_path, stage_label, stage_id = sorted(active_logs, key=lambda item: item[0], reverse=True)[0]
    progress = latest_ffmpeg_progress_from_log(log_path)
    duration_sec = None
    if stage_id == "decorated_burn" and output_video.exists():
        try:
            info = probe_video(str(output_video))
            duration_sec = float(info.get("duration_sec") or 0.0)
        except Exception:
            duration_sec = None
    if duration_sec is None and stage_id in {"concat", "segment_encode", "preview", "decoration_preview"}:
        try:
            plan = load_project_edit_plan(project_id)
            duration_sec = max((float(seg.get("output_end_sec", 0.0) or 0.0) for seg in plan.get("segments") or []), default=0.0)
        except Exception:
            duration_sec = None
    current_sec = float(progress.get("current_sec") or 0.0)
    speed = float(progress.get("speed") or 0.0)
    percent = None
    remaining_sec = None
    if duration_sec and duration_sec > 0:
        percent = max(0.0, min(100.0, current_sec / duration_sec * 100.0))
        if speed > 0:
            remaining_sec = max(0.0, (duration_sec - current_sec) / speed)
    recent = (time.time() - log_path.stat().st_mtime) < 45
    return {
        "active": recent and (percent is None or percent < 99.9),
        "stage": stage_label,
        "stage_id": stage_id,
        "duration_sec": duration_sec,
        "current_sec": current_sec,
        "percent": percent,
        "speed": speed,
        "remaining_sec": remaining_sec,
        **progress,
    }


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


def rgb_from_hex(hex_color: str | None, fallback: tuple[int, int, int] = (0, 0, 0)) -> tuple[int, int, int]:
    value = str(hex_color or "").strip().lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except Exception:
        return fallback


def ff_expr(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".") or "0"


def ffmpeg_drawtext_symbol_filter(symbol: str, color: str, intensity: float, count: int = 8) -> str:
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msgothic.ttc"
    font_expr = ""
    if font_path.exists():
        escaped_font_path = str(font_path).replace("\\", "/").replace(":", r"\:")
        font_expr = f"fontfile='{escaped_font_path}':"
    escaped_text = symbol.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    opacity = max(0.15, min(0.95, intensity))
    filters: list[str] = []
    for idx in range(max(1, count)):
        size = int(round(18 + (idx % 4) * 7 + intensity * 10))
        x_seed = (idx * 97 + 31) % 100
        speed = 0.08 + (idx % 5) * 0.025
        y_expr = f"mod(H+{idx * 47}-t*H*{speed:.3f}\\,H+80)-40"
        x_expr = f"(W*{x_seed / 100:.3f})+sin(t*{0.7 + idx * 0.13:.3f})*{12 + idx % 4 * 5}"
        filters.append(
            f"drawtext={font_expr}text='{escaped_text}':x='{x_expr}':y='{y_expr}':fontsize={size}:fontcolor={color}@{opacity:.3f}:borderw=1:bordercolor=black@0.25"
        )
    return ",".join(filters)


def ffmpeg_drawtext_motion_symbol_filter(effect: dict, symbol: str, fallback_color: str, diagonal: bool = True) -> str:
    intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.85) or 0.85)))
    count = max(1, min(40, int(round(float(effect.get("symbol_count", 8) or 8)))))
    speed = max(0.1, min(3.0, float(effect.get("speed", 1.0) or 1.0)))
    angle = math.radians(float(effect.get("direction_angle", -35) or -35))
    vx = math.cos(angle)
    vy = math.sin(angle)
    color = str(effect.get("color") or fallback_color)
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msgothic.ttc"
    font_expr = ""
    if font_path.exists():
        escaped_font_path = str(font_path).replace("\\", "/").replace(":", r"\:")
        font_expr = f"fontfile='{escaped_font_path}':"
    escaped_text = symbol.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    filters: list[str] = []
    for idx in range(count):
        size = int(round(18 + (idx % 5) * 8 + intensity * 8))
        start_x = ((idx * 83 + 17) % 100) / 100.0
        start_y = ((idx * 47 + 29) % 100) / 100.0
        travel = 0.18 + (idx % 5) * 0.035
        drift = 18 + (idx % 4) * 8
        x_expr = f"mod(W*{start_x:.3f}+t*W*{travel * speed * vx:.4f}+sin(t*{0.8 + idx * 0.11:.3f})*{drift}\\,W+80)-40"
        y_expr = f"mod(H*{start_y:.3f}+t*H*{travel * speed * vy:.4f}+cos(t*{0.7 + idx * 0.09:.3f})*{drift}\\,H+80)-40"
        filters.append(
            f"drawtext={font_expr}text='{escaped_text}':x='{x_expr}':y='{y_expr}':fontsize={size}:fontcolor={color}@{max(0.15, min(0.95, intensity)):.3f}:borderw=1:bordercolor=black@0.20"
        )
    return ",".join(filters)


SPEED_LINE_EFFECT_IDS = {
    "speed_lines",
    "speed_lines_sparse",
    "speed_lines_white",
    "speed_lines_slash",
    "speed_lines_frame",
    "speed_lines_burst",
    "speed_lines_outward",
}


def render_speed_lines_overlay_image(effect: dict, output_path: Path, canvas_size: tuple[int, int] = (1280, 720), seed: int = 0) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    import random

    width, height = canvas_size
    scale = 2
    sw, sh = width * scale, height * scale
    rng = random.Random(seed)
    effect_id = str(effect.get("id") or "speed_lines").strip()
    animation_phase = float(effect.get("_animation_phase", 0.0) or 0.0)
    animation_pulse = float(effect.get("_animation_pulse", 0.0) or 0.0)
    intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.85) or 0.85)))
    spokes = max(16, min(220, int(round(float(effect.get("spokes", 96) or 96)))))
    line_width = max(0.001, min(0.06, float(effect.get("line_width", 0.01) or 0.01)))
    center_gap = max(0.0, min(0.85, float(effect.get("center_gap", 0.10) or 0.10)))
    edge_bias = max(0.02, min(0.98, float(effect.get("edge_bias", 0.18) or 0.18)))
    color = rgb_from_hex(effect.get("color"), (0, 0, 0))
    alpha = int(round(255 * intensity))
    alpha = max(0, min(255, int(alpha * (0.84 + 0.16 * animation_pulse))))
    center_x, center_y = sw / 2.0, sh / 2.0
    min_side = min(sw, sh)
    outer_radius = math.hypot(sw, sh) * 0.58
    inner_base = min_side * (0.08 + center_gap * 0.42)
    inner_jitter = min_side * 0.05
    base_width = max(2.0, min_side * line_width)

    img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    if effect_id == "speed_lines_slash":
        count = max(18, min(180, spokes))
        angle = math.radians(-18)
        ux, uy = math.cos(angle), math.sin(angle)
        px, py = -uy, ux
        span = math.hypot(sw, sh)
        for idx in range(count):
            offset = ((idx / max(1, count - 1) + animation_phase * 0.65) % 1.0 - 0.5) * (sw + sh) * 1.35 + rng.uniform(-20, 20) * scale
            cx = center_x + px * offset
            cy = center_y + py * offset
            length = span * rng.uniform(0.26, 0.64) * (0.92 + 0.18 * animation_pulse)
            half_w = base_width * rng.uniform(0.7, 1.8)
            line_alpha = max(35, min(255, int(alpha * rng.uniform(0.42, 0.95))))
            points = [
                (cx - ux * length * 0.5 + px * half_w, cy - uy * length * 0.5 + py * half_w),
                (cx - ux * length * 0.5 - px * half_w, cy - uy * length * 0.5 - py * half_w),
                (cx + ux * length * 0.5 - px * half_w * 0.35, cy + uy * length * 0.5 - py * half_w * 0.35),
                (cx + ux * length * 0.5 + px * half_w * 0.35, cy + uy * length * 0.5 + py * half_w * 0.35),
            ]
            draw.polygon(points, fill=(*color, line_alpha))
    elif effect_id == "speed_lines_outward":
        travel = animation_phase
        for idx in range(spokes):
            angle = (math.tau * idx / spokes) + rng.uniform(-0.008, 0.008)
            ux, uy = math.cos(angle), math.sin(angle)
            px, py = -uy, ux
            base_inner = inner_base * (0.15 + 1.35 * travel)
            segment_len = min_side * (0.22 + 0.18 * animation_pulse) * rng.uniform(0.75, 1.25)
            inner = base_inner + rng.uniform(-inner_jitter * 0.45, inner_jitter * 0.45)
            outer = inner + segment_len
            if outer > outer_radius * 1.08:
                outer = outer_radius * 1.08
            inner_x = center_x + ux * inner
            inner_y = center_y + uy * inner
            outer_x = center_x + ux * outer
            outer_y = center_y + uy * outer
            inner_w = base_width * rng.uniform(0.22, 0.55)
            outer_w = base_width * rng.uniform(1.0, 2.2)
            fade = 1.0 - max(0.0, travel - 0.68) / 0.32
            line_alpha = max(0, min(255, int(alpha * fade * rng.uniform(0.65, 1.0))))
            if line_alpha <= 0:
                continue
            points = [
                (outer_x + px * outer_w, outer_y + py * outer_w),
                (outer_x - px * outer_w, outer_y - py * outer_w),
                (inner_x - px * inner_w, inner_y - py * inner_w),
                (inner_x + px * inner_w, inner_y + py * inner_w),
            ]
            draw.polygon(points, fill=(*color, line_alpha))
    else:
        for idx in range(spokes):
            if effect_id == "speed_lines_frame":
                edge = idx % 4
                pos = ((idx // 4 + rng.uniform(-0.18, 0.18)) / max(1, math.ceil(spokes / 4)) + animation_phase * 0.22) % 1.0
                if edge == 0:
                    outer_x, outer_y = pos * sw, -min_side * 0.08
                elif edge == 1:
                    outer_x, outer_y = sw + min_side * 0.08, pos * sh
                elif edge == 2:
                    outer_x, outer_y = (1.0 - pos) * sw, sh + min_side * 0.08
                else:
                    outer_x, outer_y = -min_side * 0.08, (1.0 - pos) * sh
                dx, dy = center_x - outer_x, center_y - outer_y
                length = max(1.0, math.hypot(dx, dy))
                ux, uy = dx / length, dy / length
                px, py = -uy, ux
                inner = inner_base + min_side * center_gap * 0.25 + rng.uniform(-inner_jitter, inner_jitter)
                inner_x = center_x - ux * inner
                inner_y = center_y - uy * inner
            else:
                rotation_speed = 0.06
                if effect_id == "speed_lines_sparse":
                    rotation_speed = -0.045
                elif effect_id == "speed_lines_white":
                    rotation_speed = 0.035
                elif effect_id == "speed_lines_burst":
                    rotation_speed = 0.085
                angle = (math.tau * idx / spokes) + rng.uniform(-0.012, 0.012) + animation_phase * math.tau * rotation_speed
                if effect_id == "speed_lines_burst":
                    angle += math.sin(idx * 1.7 + animation_phase * math.tau * 2.0) * 0.055
                ux, uy = math.cos(angle), math.sin(angle)
                px, py = -uy, ux
                inner = inner_base * (0.94 + 0.12 * animation_pulse) + rng.uniform(-inner_jitter, inner_jitter)
                outer = outer_radius * (edge_bias + (1.0 - edge_bias) * rng.uniform(0.78, 1.04)) * (0.96 + 0.08 * animation_pulse)
                if effect_id == "speed_lines_sparse":
                    outer *= rng.uniform(0.88, 1.18)
                    inner *= rng.uniform(0.75, 1.35)
                elif effect_id == "speed_lines_burst":
                    outer *= rng.uniform(0.62, 1.16)
                    inner *= rng.uniform(0.35, 1.15)
                inner_x = center_x + ux * inner
                inner_y = center_y + uy * inner
                outer_x = center_x + ux * outer
                outer_y = center_y + uy * outer
            inner_w = base_width * rng.uniform(0.14, 0.48)
            outer_w = base_width * rng.uniform(1.0, 2.6)
            if effect_id == "speed_lines_sparse":
                outer_w *= rng.uniform(1.2, 2.4)
            elif effect_id == "speed_lines_burst":
                outer_w *= rng.uniform(1.4, 3.0)
            elif effect_id == "speed_lines_white":
                inner_w *= 0.75
                outer_w *= 0.9
            line_alpha = max(40, min(255, int(alpha * rng.uniform(0.55, 1.0))))
            points = [
                (outer_x + px * outer_w, outer_y + py * outer_w),
                (outer_x - px * outer_w, outer_y - py * outer_w),
                (inner_x - px * inner_w, inner_y - py * inner_w),
                (inner_x + px * inner_w, inner_y + py * inner_w),
            ]
            draw.polygon(points, fill=(*color, line_alpha))

        if effect_id == "speed_lines_burst":
            for idx in range(max(8, spokes // 5)):
                angle = math.tau * idx / max(1, spokes // 5) + rng.uniform(-0.08, 0.08) + animation_phase * math.tau * 0.12
                radius = min_side * rng.uniform(0.04, max(0.05, 0.10 + center_gap * 0.2)) * (0.75 + 0.55 * animation_pulse)
                x = center_x + math.cos(angle) * radius
                y = center_y + math.sin(angle) * radius
                dot_r = base_width * rng.uniform(0.9, 2.4)
                draw.ellipse((x - dot_r, y - dot_r, x + dot_r, y + dot_r), fill=(*color, max(35, int(alpha * 0.55))))

    if intensity < 0.95:
        img = img.filter(ImageFilter.GaussianBlur(radius=max(0.0, (1.0 - intensity) * 0.35 * scale)))
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def render_speed_lines_overlay_video(
    project_id: str,
    effect: dict,
    output_path: Path,
    duration_sec: float,
    canvas_size: tuple[int, int] = (1280, 720),
    fps: int = 24,
) -> Path:
    try:
        from PIL import Image
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    duration = max(0.1, float(duration_sec or 0.1))
    speed = max(0.05, min(4.0, float(effect.get("speed", 1.0) or 1.0)))
    frame_count = max(2, int(math.ceil(duration * fps)))
    effect_id = str(effect.get("id") or "speed_lines").strip()
    frame_dir = output_path.with_suffix("")
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    for frame_index in range(frame_count):
        progress = frame_index / max(1, frame_count - 1)
        phase = (progress * speed) % 1.0
        pulse = 0.5 + 0.5 * math.sin(phase * math.tau)
        frame_effect = dict(effect)
        frame_effect["_animation_phase"] = phase
        frame_effect["_animation_pulse"] = pulse
        # Pattern-specific movement: subtle enough for reading subtitles, visible enough to avoid a still overlay.
        if effect_id == "speed_lines_slash":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.0) or 0.0))
            seed = 7000
        elif effect_id == "speed_lines_outward":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.08) or 0.08))
            seed = 7600
        elif effect_id == "speed_lines_frame":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.42) or 0.42) + math.sin(phase * math.tau) * 0.025)
            seed = 8000
        elif effect_id == "speed_lines_burst":
            pulse = 0.5 + 0.5 * math.sin(phase * math.tau * 1.25)
            frame_effect["_animation_pulse"] = pulse
            frame_effect["line_width"] = max(0.001, float(effect.get("line_width", 0.02) or 0.02) * (0.85 + 0.35 * pulse))
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.08) or 0.08) + 0.06 * pulse)
            seed = 9000
        else:
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.10) or 0.10) + 0.025 * pulse)
            frame_effect["line_width"] = max(0.001, float(effect.get("line_width", 0.01) or 0.01) * (0.92 + 0.16 * pulse))
            seed = 6000
        still_path = frame_dir / f"frame_{frame_index:04d}.png"
        render_speed_lines_overlay_image(frame_effect, still_path, canvas_size=canvas_size, seed=seed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_path = require_project(project_id) / "temp" / "logs" / f"{output_path.stem}.log"
    except HTTPException:
        log_path = output_path.with_suffix(".log")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%04d.png"),
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            str(output_path),
        ],
        log_path,
    )
    shutil.rmtree(frame_dir, ignore_errors=True)
    return output_path


def render_speed_lines_overlay_sequence(
    effect: dict,
    frame_dir: Path,
    duration_sec: float,
    canvas_size: tuple[int, int] = (1280, 720),
    fps: int = 24,
) -> str:
    duration = max(0.1, float(duration_sec or 0.1))
    speed = max(0.05, min(4.0, float(effect.get("speed", 1.0) or 1.0)))
    frame_count = max(2, int(math.ceil(duration * fps)))
    effect_id = str(effect.get("id") or "speed_lines").strip()
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    for frame_index in range(frame_count):
        progress = frame_index / max(1, frame_count - 1)
        phase = (progress * speed) % 1.0
        pulse = 0.5 + 0.5 * math.sin(phase * math.tau)
        frame_effect = dict(effect)
        frame_effect["_animation_phase"] = phase
        frame_effect["_animation_pulse"] = pulse
        if effect_id == "speed_lines_slash":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.0) or 0.0))
            seed = 7000
        elif effect_id == "speed_lines_outward":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.08) or 0.08))
            seed = 7600
        elif effect_id == "speed_lines_frame":
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.42) or 0.42) + math.sin(phase * math.tau) * 0.025)
            seed = 8000
        elif effect_id == "speed_lines_burst":
            pulse = 0.5 + 0.5 * math.sin(phase * math.tau * 1.25)
            frame_effect["_animation_pulse"] = pulse
            frame_effect["line_width"] = max(0.001, float(effect.get("line_width", 0.02) or 0.02) * (0.85 + 0.35 * pulse))
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.08) or 0.08) + 0.06 * pulse)
            seed = 9000
        else:
            frame_effect["center_gap"] = max(0.0, float(effect.get("center_gap", 0.10) or 0.10) + 0.025 * pulse)
            frame_effect["line_width"] = max(0.001, float(effect.get("line_width", 0.01) or 0.01) * (0.92 + 0.16 * pulse))
            seed = 6000
        render_speed_lines_overlay_image(frame_effect, frame_dir / f"frame_{frame_index:04d}.png", canvas_size=canvas_size, seed=seed)
    return str(frame_dir / "frame_%04d.png")


def screen_effect_cache_path(base: Path, prefix: str, payload: dict, suffix: str) -> Path:
    cache_dir = base / "temp" / "screen_effect_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:20]
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("_") or "effect"
    return cache_dir / f"{safe_prefix}_{digest}{suffix}"


def render_heart_wipe_overlay_image(effect: dict, output_path: Path, canvas_size: tuple[int, int] = (1280, 720)) -> Path:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    width, height = canvas_size
    intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.9) or 0.9)))
    cx = max(0.0, min(1.0, float(effect.get("position_x", 0.5) or 0.5))) * width
    cy = max(0.0, min(1.0, float(effect.get("position_y", 0.5) or 0.5))) * height
    radius = max(0.15, min(1.8, float(effect.get("radius", 1.05) or 1.05))) * min(width, height)
    color = rgb_from_hex(effect.get("color"), (255, 92, 168))
    alpha = int(round(255 * intensity))
    points: list[tuple[float, float]] = []
    for step in range(360):
        t = math.tau * step / 360.0
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        points.append((cx + x * radius / 18.0, cy + y * radius / 18.0))
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.polygon(points, fill=(*color, alpha))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def heart_shape_points(cx: float, cy: float, radius: float, steps: int = 240) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for step in range(max(24, steps)):
        t = math.tau * step / max(24, steps)
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        points.append((cx + x * radius / 18.0, cy + y * radius / 18.0))
    return points


def render_heart_burst_overlay_video(
    project_id: str,
    effect: dict,
    output_path: Path,
    duration_sec: float,
    canvas_size: tuple[int, int] = (1280, 720),
    fps: int = 30,
) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    width, height = canvas_size
    duration = max(0.2, min(8.0, float(duration_sec or 1.0)))
    frame_count = max(2, int(math.ceil(duration * fps)))
    intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.9) or 0.9)))
    cx = max(0.0, min(1.0, float(effect.get("position_x", 0.5) or 0.5))) * width
    cy = max(0.0, min(1.0, float(effect.get("position_y", 0.5) or 0.5))) * height
    base_radius = max(0.05, min(1.5, float(effect.get("radius", 0.18) or 0.18))) * min(width, height)
    expansion = max(0.2, min(3.0, float(effect.get("expansion_speed", 1.0) or 1.0)))
    end_radius = base_radius * (2.4 + expansion * 1.2)
    color = rgb_from_hex(effect.get("color"), (255, 92, 168))
    line_width_base = max(3, int(round(min(width, height) * 0.012)))
    frame_dir = output_path.with_suffix("")
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    for frame_index in range(frame_count):
        progress = frame_index / max(1, frame_count - 1)
        eased = 1.0 - (1.0 - progress) ** 3
        radius = base_radius + (end_radius - base_radius) * eased
        alpha = int(round(255 * intensity * (1.0 - progress) ** 1.35))
        line_width = max(1, int(round(line_width_base * (1.0 + progress * 0.65))))
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")
        points = heart_shape_points(cx, cy, radius)
        glow_alpha = max(0, int(alpha * 0.24))
        if glow_alpha:
            glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow, "RGBA")
            glow_draw.line(points + [points[0]], fill=(*color, glow_alpha), width=line_width * 3, joint="curve")
            img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(1.0, line_width * 0.9))))
        draw.line(points + [points[0]], fill=(*color, alpha), width=line_width, joint="curve")
        inner_alpha = max(0, int(alpha * 0.16))
        if inner_alpha:
            draw.polygon(points, fill=(*color, inner_alpha))
        img.save(frame_dir / f"frame_{frame_index:04d}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_path = require_project(project_id) / "temp" / "logs" / f"{output_path.stem}.log"
    except HTTPException:
        log_path = output_path.with_suffix(".log")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%04d.png"),
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            str(output_path),
        ],
        log_path,
    )
    shutil.rmtree(frame_dir, ignore_errors=True)
    return output_path


def draw_heart_shape(
    draw,
    cx: float,
    cy: float,
    radius: float,
    color: tuple[int, int, int],
    alpha: int,
    outline: bool = False,
    width: int = 2,
) -> None:
    points = heart_shape_points(cx, cy, max(1.0, radius), steps=120)
    if outline:
        draw.line(points + [points[0]], fill=(*color, alpha), width=max(1, int(width)), joint="curve")
    else:
        draw.polygon(points, fill=(*color, alpha))


def render_heart_particle_overlay_video(
    project_id: str,
    effect: dict,
    output_path: Path,
    duration_sec: float,
    canvas_size: tuple[int, int] = (1280, 720),
    fps: int = 15,
) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    import random

    mode = str(effect.get("id") or "heart_rain").strip()
    width, height = canvas_size
    duration = max(0.2, min(10.0, float(duration_sec or 1.0)))
    frame_count = max(2, int(math.ceil(duration * fps)))
    intensity = max(0.0, min(1.0, float(effect.get("intensity", 0.85) or 0.85)))
    speed = max(0.1, min(3.0, float(effect.get("speed", 1.0) or 1.0)))
    count = max(4, min(96, int(round(float(effect.get("symbol_count", 24) or 24)))))
    cx = max(0.0, min(1.0, float(effect.get("position_x", 0.5) or 0.5))) * width
    cy = max(0.0, min(1.0, float(effect.get("position_y", 0.5) or 0.5))) * height
    base_radius = max(0.02, min(0.25, float(effect.get("radius", 0.07) or 0.07))) * min(width, height)
    color = rgb_from_hex(effect.get("color"), (255, 92, 168))
    seed = int(float(effect.get("seed", 1337) or 1337))
    mode_seed = sum((index + 1) * ord(char) for index, char in enumerate(mode))
    rng = random.Random(seed + mode_seed)
    particles: list[dict] = []
    for index in range(count):
        particles.append(
            {
                "x": rng.random() * width,
                "y": rng.random() * height,
                "phase": rng.random(),
                "size": base_radius * rng.uniform(0.45, 1.3),
                "drift": rng.uniform(-0.08, 0.08) * width,
                "angle": rng.uniform(0, math.tau),
                "speed": rng.uniform(0.55, 1.35) * speed,
                "alpha": rng.uniform(0.55, 1.0),
            }
        )

    frame_dir = output_path.with_suffix("")
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    for frame_index in range(frame_count):
        progress = frame_index / max(1, frame_count - 1)
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img, "RGBA")
        if mode == "heart_tunnel":
            for ring in range(7):
                local = (progress * speed + ring / 7.0) % 1.0
                eased = local * local * (3 - 2 * local)
                radius = min(width, height) * (0.10 + eased * 0.92)
                alpha = int(255 * intensity * (1.0 - local) ** 1.45)
                line_width = max(2, int(min(width, height) * (0.008 + 0.012 * (1.0 - local))))
                draw_heart_shape(draw, cx, cy, radius, color, alpha, outline=True, width=line_width)
        elif mode == "heart_confetti":
            for particle in particles:
                local = min(1.0, max(0.0, progress * particle["speed"]))
                angle = particle["angle"]
                distance = min(width, height) * (0.04 + local * (0.75 + 0.25 * particle["phase"]))
                x = cx + math.cos(angle) * distance + math.sin(progress * math.tau * 2 + particle["phase"]) * 18
                y = cy + math.sin(angle) * distance + math.cos(progress * math.tau * 2 + particle["phase"]) * 18
                alpha = int(255 * intensity * particle["alpha"] * (1.0 - local) ** 1.1)
                draw_heart_shape(draw, x, y, particle["size"], color, alpha)
        elif mode == "heart_orbit_burst":
            orbit_count = max(6, min(32, count))
            launch_span = 0.58
            orbit_radius = min(width, height) * (0.06 + 0.03 * math.sin(progress * math.tau * 2.0))
            for idx in range(orbit_count):
                delay = (idx / orbit_count) * 0.34
                local = max(0.0, min(1.0, (progress - delay) / max(0.12, launch_span)))
                base_angle = math.tau * idx / orbit_count
                spin_angle = base_angle + progress * math.tau * speed * 1.8
                burst_angle = base_angle + math.sin(idx * 1.913) * 0.28
                if local <= 0.02:
                    distance = orbit_radius
                    angle = spin_angle
                    alpha = int(255 * intensity * 0.95)
                    size = base_radius * (0.74 + 0.22 * math.sin(progress * math.tau * 3 + idx))
                else:
                    eased = 1.0 - (1.0 - local) ** 3
                    distance = orbit_radius + min(width, height) * (0.12 + 0.78 * eased)
                    angle = burst_angle + (1.0 - local) * math.tau * 0.36
                    alpha = int(255 * intensity * (1.0 - local) ** 1.25)
                    size = base_radius * (0.82 + 0.50 * (1.0 - local))
                x = cx + math.cos(angle) * distance
                y = cy + math.sin(angle) * distance
                draw_heart_shape(draw, x, y, size, color, alpha)
        elif mode == "heart_sparkle":
            for particle in particles:
                twinkle = 0.5 + 0.5 * math.sin((progress * speed + particle["phase"]) * math.tau * 3.0)
                alpha = int(255 * intensity * particle["alpha"] * twinkle)
                size = particle["size"] * (0.65 + 0.55 * twinkle)
                x = particle["x"] + math.sin(progress * math.tau + particle["phase"] * 7) * 12
                y = particle["y"] + math.cos(progress * math.tau + particle["phase"] * 5) * 8
                draw_heart_shape(draw, x, y, size, color, alpha)
        else:
            upward = mode in {"heart_float_up", "heart_bubbles"}
            for particle in particles:
                local = (particle["phase"] + progress * particle["speed"]) % 1.0
                x = particle["x"] + math.sin((progress * speed + particle["phase"]) * math.tau * 1.4) * particle["drift"]
                if upward:
                    y = height + particle["size"] - local * (height + particle["size"] * 2)
                else:
                    y = -particle["size"] + local * (height + particle["size"] * 2)
                alpha = int(255 * intensity * particle["alpha"] * (0.75 + 0.25 * math.sin(local * math.pi)))
                draw_heart_shape(draw, x, y, particle["size"], color, alpha)
        if mode in {"heart_tunnel", "heart_sparkle", "heart_orbit_burst"}:
            img = img.filter(ImageFilter.GaussianBlur(radius=0.35))
        img.save(frame_dir / f"frame_{frame_index:04d}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_path = require_project(project_id) / "temp" / "logs" / f"{output_path.stem}.log"
    except HTTPException:
        log_path = output_path.with_suffix(".log")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%04d.png"),
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            str(output_path),
        ],
        log_path,
    )
    shutil.rmtree(frame_dir, ignore_errors=True)
    return output_path


def screen_effect_intervals(plan: dict, decoration: dict, effect_id: str) -> list[dict]:
    stacks = {str(stack.get("id") or "").strip(): stack for stack in (decoration.get("screen_effect_stacks") or []) if str(stack.get("id") or "").strip()}
    targets = decoration.get("screen_effect_targets") or {"global_stack_ids": [], "scene_stack_ids": {}}
    output_duration = max((float(seg.get("output_end_sec", 0.0) or 0.0) for seg in plan.get("segments") or []), default=0.0)
    if output_duration <= 0:
        return []
    intervals: list[dict] = []

    def stack_interval(stack: dict, target_start: float, target_end: float) -> tuple[float, float]:
        if str(stack.get("timing_mode") or "full").strip().lower() != "custom":
            return target_start, target_end
        raw_start = float(stack.get("effect_start_sec", 0.0) or 0.0)
        raw_end = float(stack.get("effect_end_sec", max(0.0, target_end - target_start)) or max(0.0, target_end - target_start))
        if str(stack.get("timing_basis") or "relative").strip().lower() == "absolute":
            start = raw_start
            end = raw_end
        else:
            start = target_start + raw_start
            end = target_start + raw_end
        return max(target_start, start), min(target_end, end)

    def add_from_stack_ids(stack_ids: list[str], start: float, end: float) -> None:
        if end <= start:
            return
        for stack_id in stack_ids:
            stack = stacks.get(str(stack_id or "").strip())
            if not stack:
                continue
            effect_start, effect_end = stack_interval(stack, max(0.0, start), min(output_duration, end))
            if effect_end <= effect_start:
                continue
            for effect in stack.get("effects") or []:
                if str(effect.get("id") or "").strip() == effect_id:
                    intervals.append({"start_sec": effect_start, "end_sec": effect_end, "effect": dict(effect)})

    add_from_stack_ids([str(item) for item in targets.get("global_stack_ids", []) if str(item).strip()], 0.0, output_duration)
    for scene in plan.get("scenes") or decoration.get("scenes") or []:
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            continue
        start = float(scene.get("start_sec", 0.0) or 0.0)
        end = float(scene.get("end_sec", start) or start)
        add_from_stack_ids([str(item) for item in targets.get("scene_stack_ids", {}).get(scene_id, []) if str(item).strip()], start, end)
    return intervals


def generate_screen_effect_overlays(
    project_id: str,
    plan: dict,
    decoration: dict,
    canvas_size: tuple[int, int] = (1280, 720),
    sequence_fps: int = 24,
    speed_lines_as_video: bool = False,
) -> list[dict]:
    base = require_project(project_id)
    overlay_dir = base / "temp" / "screen_effect_overlays"
    if overlay_dir.exists():
        shutil.rmtree(overlay_dir, ignore_errors=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlays: list[dict] = []
    speed_line_index = 1
    for effect_id in sorted(SPEED_LINE_EFFECT_IDS):
        for interval in screen_effect_intervals(plan, decoration, effect_id):
            start_sec = float(interval.get("start_sec", 0.0) or 0.0)
            end_sec = float(interval.get("end_sec", start_sec + 1.0) or (start_sec + 1.0))
            frame_dir = overlay_dir / f"{effect_id}_{speed_line_index:04d}"
            effect = dict(interval["effect"])
            effect["id"] = effect_id
            if speed_lines_as_video:
                duration_sec = max(0.1, end_sec - start_sec)
                path = screen_effect_cache_path(
                    base,
                    effect_id,
                    {
                        "kind": "speed_lines_video",
                        "effect": effect,
                        "duration_sec": round(duration_sec, 3),
                        "canvas_size": canvas_size,
                        "fps": sequence_fps,
                    },
                    ".mov",
                )
                if not path.exists() or path.stat().st_size <= 0:
                    render_speed_lines_overlay_video(project_id, effect, path, duration_sec, canvas_size=canvas_size, fps=sequence_fps)
                overlays.append({
                    "path": str(path),
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "type": effect_id,
                    "animated": True,
                })
            else:
                pattern = render_speed_lines_overlay_sequence(effect, frame_dir, end_sec - start_sec, canvas_size=canvas_size, fps=sequence_fps)
                overlays.append({
                    "path": pattern,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "type": effect_id,
                    "animated": True,
                    "sequence": True,
                    "framerate": sequence_fps,
                })
            speed_line_index += 1
    heart_intervals = [
        *screen_effect_intervals(plan, decoration, "heart_wipe"),
        *screen_effect_intervals(plan, decoration, "heart_expand"),
    ]
    for index, interval in enumerate(heart_intervals, start=1):
        path = overlay_dir / f"heart_wipe_{index:04d}.png"
        render_heart_wipe_overlay_image(interval["effect"], path, canvas_size=canvas_size)
        overlays.append({
            "path": str(path),
            "start_sec": float(interval.get("start_sec", 0.0) or 0.0),
            "end_sec": float(interval.get("end_sec", 0.0) or 0.0),
            "type": "heart_wipe",
        })
    for index, interval in enumerate(screen_effect_intervals(plan, decoration, "heart_burst"), start=1):
        start_sec = float(interval.get("start_sec", 0.0) or 0.0)
        end_sec = float(interval.get("end_sec", start_sec + 1.0) or (start_sec + 1.0))
        duration_sec = max(0.1, end_sec - start_sec)
        path = screen_effect_cache_path(
            base,
            "heart_burst",
            {
                "kind": "heart_burst_video",
                "effect": interval["effect"],
                "duration_sec": round(duration_sec, 3),
                "canvas_size": canvas_size,
            },
            ".mov",
        )
        if not path.exists() or path.stat().st_size <= 0:
            render_heart_burst_overlay_video(project_id, interval["effect"], path, duration_sec, canvas_size=canvas_size)
        overlays.append({
            "path": str(path),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "type": "heart_burst",
            "animated": True,
        })
    animated_heart_effects = ["heart_rain", "heart_float_up", "heart_confetti", "heart_sparkle", "heart_tunnel", "heart_orbit_burst"]
    for effect_id in animated_heart_effects:
        for index, interval in enumerate(screen_effect_intervals(plan, decoration, effect_id), start=1):
            start_sec = float(interval.get("start_sec", 0.0) or 0.0)
            end_sec = float(interval.get("end_sec", start_sec + 1.0) or (start_sec + 1.0))
            duration_sec = max(0.1, end_sec - start_sec)
            path = screen_effect_cache_path(
                base,
                effect_id,
                {
                    "kind": "heart_particle_video",
                    "effect_id": effect_id,
                    "effect": interval["effect"],
                    "duration_sec": round(duration_sec, 3),
                    "canvas_size": canvas_size,
                },
                ".mov",
            )
            if not path.exists() or path.stat().st_size <= 0:
                render_heart_particle_overlay_video(project_id, interval["effect"], path, duration_sec, canvas_size=canvas_size)
            overlays.append({
                "path": str(path),
                "start_sec": start_sec,
                "end_sec": end_sec,
                "type": effect_id,
                "animated": True,
            })
    return overlays


def ffmpeg_video_zoom_filter(effect: dict, start_sec: float | None = None, end_sec: float | None = None) -> str | None:
    item = dict(effect or {})
    zoom_scale = max(0.25, min(3.0, float(item.get("zoom_scale", 1.0) or 1.0)))
    if abs(zoom_scale - 1.0) < 0.001:
        return None
    cx = max(0.0, min(1.0, float(item.get("position_x", 0.5) or 0.5)))
    cy = max(0.0, min(1.0, float(item.get("position_y", 0.5) or 0.5)))
    if start_sec is not None and end_sec is not None and end_sec > start_sec:
        active = f"between(T\\,{float(start_sec):.3f}\\,{float(end_sec):.3f})"
        z_expr = f"if({active}\\,{zoom_scale:.5f}\\,1)"
    else:
        z_expr = f"{zoom_scale:.5f}"
    src_x = f"W*{cx:.5f}+(X-W*{cx:.5f})/({z_expr})"
    src_y = f"H*{cy:.5f}+(Y-H*{cy:.5f})/({z_expr})"
    valid = f"between({src_x}\\,0\\,W-1)*between({src_y}\\,0\\,H-1)"
    return (
        "format=rgba,"
        f"geq=r='if({valid}\\,r({src_x}\\,{src_y})\\,0)':"
        f"g='if({valid}\\,g({src_x}\\,{src_y})\\,0)':"
        f"b='if({valid}\\,b({src_x}\\,{src_y})\\,0)':"
        "a='alpha(X\\,Y)',format=yuv420p"
    )


def ffmpeg_screen_effect_filter(effect: dict) -> str | None:
    item = dict(effect or {})
    effect_id = str(item.get("id") or "").strip()
    intensity = max(0.0, min(1.0, float(item.get("intensity", 1.0) or 0.0)))
    if intensity <= 0:
        return None
    if effect_id == "video_zoom":
        return ffmpeg_video_zoom_filter(item)
    if effect_id == "shutter_24fps":
        return "fps=24"
    if effect_id == "sepia":
        return f"colorchannelmixer=.393:.769:.189:.349:.686:.168:.272:.534:.131"
    if effect_id == "monochrome":
        return "hue=s=0"
    if effect_id == "vignette":
        angle = max(0.15, 0.45 * intensity)
        return f"vignette=PI/{1.0 / angle:.2f}" if angle > 0 else "vignette"
    if effect_id == "cinema":
        contrast = 1.0 + intensity * 0.18
        saturation = 1.0 + intensity * 0.12
        return f"eq=contrast={contrast:.3f}:saturation={saturation:.3f}"
    if effect_id == "cinematic_border":
        bar = max(2, int(round(54 * intensity)))
        color = str(item.get("border_color") or item.get("color") or "black").strip() or "black"
        opacity = max(0.0, min(1.0, float(item.get("border_opacity", 0.85) or 0.85)))
        return f"drawbox=x=0:y=0:w=iw:h={bar}:color={color}@{opacity:.3f}:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color={color}@{opacity:.3f}:t=fill"
    if effect_id == "old_tv":
        return f"eq=contrast={1.0 + intensity * 0.08:.3f}:saturation={1.0 - intensity * 0.22:.3f},noise=alls={int(8 + intensity * 18)}:allf=t+u"
    if effect_id == "vhs":
        return f"eq=contrast={1.0 + intensity * 0.12:.3f}:saturation={1.0 + intensity * 0.18:.3f},noise=alls={int(4 + intensity * 12)}:allf=t+u"
    if effect_id == "crt":
        return f"eq=contrast={1.0 + intensity * 0.08:.3f}:brightness={1.0 - intensity * 0.03:.3f},noise=alls={int(3 + intensity * 9)}:allf=t+u"
    if effect_id == "scanlines":
        density = max(0.5, min(4.0, float(item.get("line_density", 1.0) or 1.0)))
        opacity = max(0.0, min(0.8, float(item.get("line_opacity", 0.22) or 0.22) * intensity))
        period = max(2, int(round(4.0 / density)))
        return f"format=rgba,geq=r='r(X\\,Y)*(1-{opacity:.4f}*not(mod(Y\\,{period})))':g='g(X\\,Y)*(1-{opacity:.4f}*not(mod(Y\\,{period})))':b='b(X\\,Y)*(1-{opacity:.4f}*not(mod(Y\\,{period})))':a='alpha(X\\,Y)',format=yuv420p"
    if effect_id == "disco":
        return f"hue=h='45*sin(2*PI*t*{max(0.2, float(item.get('speed', 1.0) or 1.0)):.3f})':s={1.0 + intensity * 0.9:.3f}"
    if effect_id == "retro_game":
        px = max(3, int(round(10 + intensity * 14)))
        return f"scale=iw/{px}:ih/{px}:flags=neighbor,scale=iw:ih:flags=neighbor,eq=saturation={1.0 + intensity * 0.35:.3f}:contrast={1.0 + intensity * 0.20:.3f}"
    if effect_id == "horror":
        return f"hue=s={max(0.0, 1.0 - intensity * 0.75):.3f},eq=contrast={1.0 + intensity * 0.35:.3f}:brightness={1.0 - intensity * 0.10:.3f},vignette=PI/3.8"
    if effect_id == "neon":
        color = rgb_from_hex(item.get("color"), (255, 80, 220))
        return f"eq=contrast={1.0 + intensity * 0.20:.3f}:saturation={1.0 + intensity * 0.75:.3f},colorbalance=rs={color[0] / 255 * 0.18 * intensity:.3f}:bs={color[2] / 255 * 0.18 * intensity:.3f}"
    if effect_id == "cyberpunk":
        return f"eq=contrast={1.0 + intensity * 0.22:.3f}:saturation={1.0 + intensity * 0.65:.3f},colorbalance=rs={0.12 * intensity:.3f}:bs={0.20 * intensity:.3f}"
    if effect_id == "dream":
        return f"gblur=sigma={max(0.3, intensity * 2.0):.3f},eq=brightness={1.0 + intensity * 0.04:.3f}"
    if effect_id == "rainy":
        return f"gblur=sigma={max(0.1, intensity * 0.8):.3f},eq=brightness={1.0 - intensity * 0.08:.3f}:saturation={1.0 - intensity * 0.12:.3f}"
    if effect_id == "sunset":
        return f"eq=contrast={1.0 + intensity * 0.10:.3f}:saturation={1.0 + intensity * 0.14:.3f},hue=h={int(10 + intensity * 20)}"
    if effect_id == "docu_low_sat":
        return f"hue=s={max(0.0, 1.0 - intensity * 0.65):.3f}"
    if effect_id == "pop_high_sat":
        return f"eq=saturation={1.0 + intensity * 0.85:.3f}:contrast={1.0 + intensity * 0.08:.3f}"
    if effect_id == "noise" or effect_id == "film_grain":
        return f"noise=alls={int(8 + intensity * 24)}:allf=t+u"
    if effect_id == "glitch":
        shift = max(1, int(round(float(item.get("glitch_shift", 0.06) or 0.06) * 120 * intensity)))
        return f"rgbashift=rh={shift}:bh=-{shift}:edge=smear,noise=alls={int(4 + intensity * 12)}:allf=t+u"
    if effect_id in {"rgb_shift", "chromatic_aberration"}:
        shift = max(1, int(round(float(item.get("color_shift", 0.012) or 0.012) * 900 * intensity)))
        return f"rgbashift=rh={shift}:bh=-{shift}:edge=smear"
    if effect_id == "flash":
        return f"eq=brightness='{0.28 * intensity:.4f}*max(0\\,sin(2*PI*t*2.0))'"
    if effect_id == "strobe":
        return f"eq=brightness='{0.32 * intensity:.4f}*gte(sin(2*PI*t*8.0)\\,0)'"
    if effect_id == "fade":
        return f"eq=brightness='-{0.18 * intensity:.4f}*(0.5+0.5*sin(2*PI*t*0.6))'"
    if effect_id in {"shake", "hand_tremor", "action_shake"}:
        strength = max(2, int(round(float(item.get("shake_strength", 1.0) or 1.0) * 8 * intensity)))
        speed = max(0.2, float(item.get("shake_speed", item.get("speed", 1.0)) or 1.0))
        return f"crop=w=iw-{strength * 2}:h=ih-{strength * 2}:x='{strength}+{strength}*sin(2*PI*t*{speed * 5.0:.3f})':y='{strength}+{strength}*sin(2*PI*t*{speed * 4.1:.3f}+1.7)',scale=iw+{strength * 2}:ih+{strength * 2}"
    if effect_id == "edge_blur" or effect_id == "background_blur":
        return f"gblur=sigma={max(0.2, intensity * 2.5):.3f}"
    if effect_id == "highlight_subject" or effect_id == "shadow_boost":
        return f"eq=brightness={1.0 + intensity * 0.06:.3f}:contrast={1.0 + intensity * 0.08:.3f}:saturation={1.0 + intensity * 0.10:.3f}"
    if effect_id == "highlight_suppress":
        return f"eq=brightness={1.0 - intensity * 0.04:.3f}:contrast={1.0 + intensity * 0.06:.3f}"
    if effect_id == "sharpen" or effect_id == "game_sharp":
        return f"unsharp=5:5:{max(0.2, intensity * 1.2):.3f}:5:5:0.0"
    if effect_id == "pseudo_hdr":
        return f"eq=contrast={1.0 + intensity * 0.22:.3f}:saturation={1.0 + intensity * 0.16:.3f}:brightness={1.0 + intensity * 0.05:.3f}"
    if effect_id == "white_balance":
        temp = float(item.get("color_temperature", 0) or 0)
        return f"eq=saturation={1.0 + intensity * 0.08:.3f}:contrast={1.0 + intensity * 0.05:.3f},hue=h={int(temp * 18)}"
    if effect_id == "spotlight":
        cx = max(0.0, min(1.0, float(item.get("position_x", 0.5) or 0.5)))
        cy = max(0.0, min(1.0, float(item.get("position_y", 0.45) or 0.45)))
        radius = max(0.05, min(0.95, float(item.get("radius", 0.34) or 0.34)))
        darkness = max(0.0, min(0.95, intensity))
        dist = f"hypot(X-W*{cx:.4f}\\,Y-H*{cy:.4f})/min(W\\,H)"
        mask = f"min(1\\,max(0\\,({dist}-{radius:.4f})/{max(0.02, radius * 0.55):.4f}))"
        return (
            "format=rgba,"
            f"geq=r='r(X\\,Y)*(1-{darkness:.4f}*{mask})':"
            f"g='g(X\\,Y)*(1-{darkness:.4f}*{mask})':"
            f"b='b(X\\,Y)*(1-{darkness:.4f}*{mask})':"
            "a='alpha(X\\,Y)',format=yuv420p"
        )
    if effect_id == "iris_out":
        cx = max(0.0, min(1.0, float(item.get("position_x", 0.5) or 0.5)))
        cy = max(0.0, min(1.0, float(item.get("position_y", 0.5) or 0.5)))
        radius = max(0.1, min(1.2, float(item.get("radius", 0.65) or 0.65)))
        speed = max(0.2, min(3.0, float(item.get("speed", 1.0) or 1.0)))
        open_radius = f"max(0.001\\,{radius:.4f}*(1-min(1\\,N/25*{speed:.4f})))"
        dist = f"hypot(X-W*{cx:.4f}\\,Y-H*{cy:.4f})/min(W\\,H)"
        mask = f"min(1\\,max(0\\,({dist}-{open_radius})/0.035))"
        return (
            "format=rgba,"
            f"geq=r='r(X\\,Y)*(1-{intensity:.4f}*{mask})':"
            f"g='g(X\\,Y)*(1-{intensity:.4f}*{mask})':"
            f"b='b(X\\,Y)*(1-{intensity:.4f}*{mask})':"
            "a='alpha(X\\,Y)',format=yuv420p"
        )
    if effect_id == "drifting_stars":
        return ffmpeg_drawtext_motion_symbol_filter(item, "★", "#fff176")
    if effect_id == "drifting_hearts":
        return ffmpeg_drawtext_motion_symbol_filter(item, "♥", "#ff5ca8")
    if effect_id in {"heart_wipe", "heart_expand"}:
        return None
    if effect_id in {"auto_brightness", "text_readability"}:
        return f"eq=brightness={1.0 + intensity * 0.04:.3f}:contrast={1.0 + intensity * 0.12:.3f}:saturation={1.0 + intensity * 0.04:.3f}"
    if effect_id in {"dark_game", "skin_tone"}:
        if effect_id == "dark_game":
            return f"eq=brightness={1.0 - intensity * 0.06:.3f}:contrast={1.0 + intensity * 0.20:.3f}:saturation={1.0 + intensity * 0.10:.3f}"
        return f"eq=brightness={1.0 + intensity * 0.03:.3f}:contrast={1.0 + intensity * 0.06:.3f}:saturation={1.0 + intensity * 0.08:.3f}"
    if effect_id == "pixelate":
        px = max(2.0, float(item.get("pixel_size", 12) or 12))
        return f"scale=iw/{px}:ih/{px}:flags=neighbor,scale=iw:ih:flags=neighbor"
    if effect_id == "posterize":
        levels = max(2, min(32, int(round(float(item.get("posterize_levels", 6) or 6)))))
        step = max(1, int(round(255 / max(1, levels - 1))))
        return f"format=rgb24,lutrgb=r='floor(val/{step})*{step}':g='floor(val/{step})*{step}':b='floor(val/{step})*{step}'"
    if effect_id == "mirror":
        return "hflip"
    if effect_id == "split_mirror":
        return "split[left][right];[right]hflip[rightflip];[left][rightflip]blend=all_expr='if(lt(X,W/2),A,B)'"
    if effect_id == "kaleidoscope":
        return "split[a][b];[b]hflip,vflip[bm];[a][bm]blend=all_mode=lighten:all_opacity=0.55"
    if effect_id == "miniature":
        return f"gblur=sigma={max(0.2, intensity * 1.8):.3f},eq=saturation={1.0 + intensity * 0.25:.3f}:contrast={1.0 + intensity * 0.10:.3f}"
    if effect_id == "fisheye":
        strength = max(0.05, intensity * 0.35)
        return f"lenscorrection=k1={-strength:.3f}:k2=0.000"
    if effect_id in {"zoom_blur", "radial_blur"}:
        return f"gblur=sigma={max(0.2, float(item.get('blur_amount', 0.18) or 0.18) * 8.0 * intensity):.3f},eq=contrast={1.0 + intensity * 0.05:.3f}"
    if effect_id == "impact_flash":
        frequency = max(1.0, float(item.get("flash_frequency", 10) or 10))
        power = max(1.0, float(item.get("flash_power", 5) or 5))
        return f"eq=brightness='{0.40 * intensity:.4f}*pow(max(0\\,sin(2*PI*t*{frequency:.3f}))\\,{power:.3f})'"
    if effect_id == "anime_edge":
        threshold = max(0.02, min(0.5, float(item.get("edge_threshold", 0.18) or 0.18)))
        return f"edgedetect=low={threshold:.3f}:high={min(1.0, threshold + 0.22):.3f},eq=contrast={1.0 + intensity * 0.30:.3f}"
    if effect_id == "oil_paint":
        return f"gblur=sigma={max(0.4, intensity * 1.6):.3f},unsharp=7:7:{0.7 + intensity * 0.6:.3f}:7:7:0.0,eq=saturation={1.0 + intensity * 0.18:.3f}:contrast={1.0 + intensity * 0.12:.3f}"
    if effect_id == "watercolor":
        return f"gblur=sigma={max(0.5, intensity * 2.2):.3f},eq=saturation={1.0 + intensity * 0.22:.3f}:brightness={0.02 * intensity:.3f}:contrast={1.0 - intensity * 0.06:.3f}"
    if effect_id == "pencil_sketch":
        return f"format=gray,edgedetect=low={0.06 + intensity * 0.08:.3f}:high={0.24 + intensity * 0.20:.3f},negate,eq=contrast={1.0 + intensity * 0.30:.3f},format=yuv420p"
    if effect_id == "hearts":
        return ffmpeg_drawtext_symbol_filter("♥", str(item.get("color") or "#ff5ca8"), intensity, count=7)
    if effect_id == "stars":
        return ffmpeg_drawtext_symbol_filter("★", str(item.get("color") or "#fff176"), intensity, count=9)
    if effect_id == "balloons":
        return ffmpeg_drawtext_symbol_filter("●", str(item.get("color") or "#ff7aa8"), intensity, count=6)
    if effect_id == "snow":
        return ffmpeg_drawtext_symbol_filter("*", str(item.get("color") or "#ffffff"), intensity, count=14)
    if effect_id in SPEED_LINE_EFFECT_IDS:
        return None
    if effect_id == "halftone":
        density = max(4.0, min(96.0, float(item.get("dot_density", 28) or 28)))
        cell = max(4, min(72, int(round(720.0 / density))))
        half = cell / 2.0
        dot_scale = max(0.2, min(2.0, float(item.get("dot_scale", 1.0) or 1.0)))
        contrast = max(0.2, min(3.0, float(item.get("contrast", 1.0) or 1.0)))
        radius = half * dot_scale * intensity
        # Stable cell-centered sampling: no time-based jitter, so video dots do not flicker.
        expr = (
            f"if(lt(hypot(mod(X\\,{cell})-{half:.3f}\\,mod(Y\\,{cell})-{half:.3f})\\,"
            f"{radius:.3f}*pow(1-lum(X-mod(X\\,{cell})+{half:.3f}\\,Y-mod(Y\\,{cell})+{half:.3f})/255\\,{1.0 / contrast:.3f}))\\,"
            "0\\,255)"
        )
        return f"format=gray,geq=lum='{expr}':cb=128:cr=128,format=yuv420p"
    return None


def split_ffmpeg_filter_chain(filter_expr: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    quote: str | None = None
    for char in str(filter_expr or ""):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            current.append(char)
            quote = None if quote == char else (char if quote is None else quote)
            continue
        if char == "," and quote is None:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def ffmpeg_filter_name(filter_part: str) -> str:
    head = str(filter_part or "").strip().split("=", 1)[0].strip()
    return head.split("@", 1)[0].strip()


def add_timeline_enable_to_filter_chain(filter_expr: str, start: float, end: float) -> str | None:
    parts = split_ffmpeg_filter_chain(filter_expr)
    if not parts:
        return None
    # Only filters known to support FFmpeg timeline enable are used for scene-scoped chains.
    # Filters such as fps/scale/format/geq are intentionally excluded because adding enable
    # to them either fails or applies only part of a chain outside the requested scene.
    timeline_filters = {
        "drawtext",
        "drawbox",
        "eq",
        "hue",
        "vignette",
        "colorbalance",
        "noise",
        "gblur",
        "unsharp",
        "edgedetect",
        "negate",
    }
    enabled_parts: list[str] = []
    enable_expr = f"enable='between(t,{start:.3f},{end:.3f})'"
    for part in parts:
        name = ffmpeg_filter_name(part)
        if name not in timeline_filters:
            return None
        enabled_parts.append(f"{part}:{enable_expr}")
    return ",".join(enabled_parts)


def build_screen_effect_filter_chain(plan: dict, decoration: dict) -> tuple[str, list[str]]:
    stacks = {str(stack.get("id") or "").strip(): stack for stack in (decoration.get("screen_effect_stacks") or []) if str(stack.get("id") or "").strip()}
    targets = decoration.get("screen_effect_targets") or {"global_stack_ids": [], "scene_stack_ids": {}}
    segments = plan.get("segments") or []
    if not stacks or not segments:
        return "", []

    output_duration = max((float(seg.get("output_end_sec", 0.0) or 0.0) for seg in segments), default=0.0)
    if output_duration <= 0:
        return "", []

    applied: list[str] = []
    filter_parts: list[str] = []

    def stack_interval(stack: dict, target_start: float, target_end: float) -> tuple[float, float]:
        if str(stack.get("timing_mode") or "full").strip().lower() != "custom":
            return target_start, target_end
        raw_start = float(stack.get("effect_start_sec", 0.0) or 0.0)
        raw_end = float(stack.get("effect_end_sec", max(0.0, target_end - target_start)) or max(0.0, target_end - target_start))
        if str(stack.get("timing_basis") or "relative").strip().lower() == "absolute":
            start = raw_start
            end = raw_end
        else:
            start = target_start + raw_start
            end = target_start + raw_end
        return max(target_start, start), min(target_end, end)

    def add_stack_filters(stack_ids: list[str], start: float | None = None, end: float | None = None) -> None:
        base_scoped = start is not None and end is not None and end > start
        for stack_id in stack_ids:
            stack = stacks.get(str(stack_id or "").strip())
            if not stack:
                continue
            effect_start = float(start or 0.0)
            effect_end = float(end or output_duration)
            scoped = base_scoped
            if scoped:
                effect_start, effect_end = stack_interval(stack, effect_start, effect_end)
                if effect_end <= effect_start:
                    continue
            elif str(stack.get("timing_mode") or "full").strip().lower() == "custom":
                effect_start, effect_end = stack_interval(stack, 0.0, output_duration)
                if effect_end <= effect_start:
                    continue
                scoped = True
            for effect in stack.get("effects") or []:
                effect_id = str(effect.get("id") or "").strip()
                if effect_id == "video_zoom":
                    filter_expr = ffmpeg_video_zoom_filter(effect, effect_start, effect_end) if scoped else ffmpeg_video_zoom_filter(effect)
                    if filter_expr:
                        applied.append(effect_id)
                        filter_parts.append(filter_expr)
                    continue
                filter_expr = ffmpeg_screen_effect_filter(effect)
                if not filter_expr:
                    continue
                if scoped:
                    filter_expr = add_timeline_enable_to_filter_chain(filter_expr, effect_start, effect_end)
                    if not filter_expr:
                        continue
                applied.append(str(effect.get("id") or "unknown"))
                filter_parts.append(filter_expr)

    add_stack_filters([str(item) for item in targets.get("global_stack_ids", []) if str(item).strip()])
    for scene in plan.get("scenes") or []:
        scene_start = float(scene.get("start_sec", 0.0) or 0.0)
        scene_end = float(scene.get("end_sec", scene_start) or scene_start)
        if scene_end <= scene_start:
            continue
        scene_stack_ids = [str(item) for item in targets.get("scene_stack_ids", {}).get(str(scene.get("id") or "").strip(), []) if str(item).strip()]
        add_stack_filters(scene_stack_ids, scene_start, scene_end)

    return ",".join(filter_parts), applied


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


def sanitize_ass_comment_text(text: str) -> str:
    value = sanitize_ass_text(text)
    return value.replace(",", "，")


def default_ai_ass_prompt_lines() -> list[str]:
    return [
        "AI向け非表示プロンプト:",
        "このASS字幕ファイルのDialogue字幕本文と時刻を読み取り、YouTube投稿用の概要欄文面を日本語で作成してください。",
        "概要欄には、動画全体の短い説明、見どころの要約、時刻へ飛べるタイムラインインデックスを含めてください。",
        "タイムラインは 00:00 形式または 00:00:00 形式で、クリック可能なYouTubeチャプターとして使える形にしてください。",
        "字幕本文をそのまま長く転載せず、内容を要約してください。",
        "出力は「概要」「タイムライン」「補足メモ」の順にしてください。",
        "Comment行は表示用字幕ではなくAIへの指示です。Dialogue行を主な素材として扱ってください。",
    ]


def ass_comment_line(text: str, *, start: float = 0.0, end: float = 0.01, style: str = "DecorText") -> str:
    return f"Comment: 0,{ass_timecode(start)},{ass_timecode(end)},{style},,0,0,0,,{sanitize_ass_comment_text(text)}"


def ass_color(hex_color: str) -> str:
    value = str(hex_color or "#ffffff").strip().lstrip("#")
    if len(value) != 6:
        value = "ffffff"
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    return f"&H00{bb}{gg}{rr}&"


def ass_color_with_alpha(hex_color: str, opacity: float = 1.0) -> str:
    value = str(hex_color or "#ffffff").strip().lstrip("#")
    if len(value) != 6:
        value = "ffffff"
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    try:
        opacity_value = max(0.0, min(1.0, float(opacity)))
    except Exception:
        opacity_value = 1.0
    alpha = int(round((1.0 - opacity_value) * 255))
    return f"&H{alpha:02X}{bb}{gg}{rr}&"


@lru_cache(maxsize=256)
def find_font_file(family: str | None) -> Path | None:
    names = [re.sub(r"[_\-\s]+", " ", candidate).lower() for candidate in font_family_candidates(family)]
    if not names:
        return None
    candidates: list[Path] = []
    if os.name == "nt":
        font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        user_font_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Microsoft" / "Windows" / "Fonts"
        try:
            import winreg

            key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    value_name, font_file, _ = winreg.EnumValue(key, index)
                    cleaned = clean_font_family_name(str(value_name))
                    registry_names = [re.sub(r"[_\-\s]+", " ", item).lower() for item in font_family_candidates(cleaned)]
                    if any(
                        name == reg_name
                        or (
                            len(name) >= 6
                            and len(reg_name) >= 6
                            and (name in reg_name or reg_name in name)
                        )
                        for name in names
                        for reg_name in registry_names
                    ):
                        path = Path(str(font_file))
                        if not path.is_absolute():
                            path = font_dir / path
                        if path.exists():
                            return path
        except Exception:
            pass
        if font_dir.exists():
            candidates.extend([path for path in font_dir.rglob("*") if path.suffix.lower() in {".ttf", ".otf", ".ttc"}])
        if user_font_dir.exists():
            candidates.extend([path for path in user_font_dir.rglob("*") if path.suffix.lower() in {".ttf", ".otf", ".ttc"}])
    else:
        for font_dir in [Path("/usr/share/fonts"), Path.home() / ".fonts"]:
            if font_dir.exists():
                candidates.extend([path for path in font_dir.rglob("*") if path.suffix.lower() in {".ttf", ".otf", ".ttc"}])
    exact = [path for path in candidates if re.sub(r"[_\-\s]+", " ", path.stem).lower() in names]
    if exact:
        return sorted(exact, key=lambda item: len(item.name))[0]
    partial = [
        path
        for path in candidates
        if any(name in re.sub(r"[_\-\s]+", " ", path.stem).lower() for name in names)
    ]
    if partial:
        return sorted(partial, key=lambda item: len(item.name))[0]
    by_internal_exact: list[Path] = []
    by_internal_partial: list[Path] = []
    for path in candidates:
        internal_names = [
            re.sub(r"[_\-\s]+", " ", candidate).lower()
            for candidate in japanese_font_family_names_from_file(path)
        ]
        if any(name == internal for name in names for internal in internal_names):
            by_internal_exact.append(path)
        elif any(
            len(name) >= 6 and len(internal) >= 6 and (name in internal or internal in name)
            for name in names
            for internal in internal_names
        ):
            by_internal_partial.append(path)
    font_rank = lambda item: (0 if "regular" in item.stem.lower() else 1, len(item.name))
    if by_internal_exact:
        return sorted(by_internal_exact, key=font_rank)[0]
    if by_internal_partial:
        return sorted(by_internal_partial, key=font_rank)[0]
    return None


def rgba_from_hex(hex_color: str | None, opacity: float = 1.0) -> tuple[int, int, int, int]:
    value = str(hex_color or "#ffffff").strip().lstrip("#")
    if len(value) != 6:
        value = "ffffff"
    rr = int(value[0:2], 16)
    gg = int(value[2:4], 16)
    bb = int(value[4:6], 16)
    try:
        opacity_value = max(0.0, min(1.0, float(opacity)))
    except Exception:
        opacity_value = 1.0
    aa = int(round(opacity_value * 255))
    return rr, gg, bb, aa


def frame_kind(frame_preset: dict | None = None) -> str:
    preset = frame_preset or {}
    frame_id = str(preset.get("id", "")).strip().lower()
    effects = {str(effect).strip().lower() for effect in preset.get("effects", []) if str(effect).strip()}
    if frame_id == "frame_none":
        return "none"
    if "jagged" in effects or frame_id == "frame_bubble_jagged":
        return "jagged_bubble"
    if "hand_drawn" in effects or frame_id == "frame_hand_drawn":
        return "hand_drawn"
    if "shadow_box" in effects or frame_id == "frame_shadow_box":
        return "shadow_box"
    if "note_paper" in effects or frame_id == "frame_note_paper":
        return "note_paper"
    if "bubble_soft" in effects or frame_id == "frame_bubble_soft":
        return "bubble_soft"
    if "manga_thick" in effects or frame_id == "frame_manga_thick":
        return "manga_thick"
    if "manga_soft" in effects or frame_id == "frame_manga_soft":
        return "manga_soft"
    if "bubble_round" in effects or frame_id == "frame_bubble_round":
        return "bubble_round"
    return "bubble_round"


def effective_frame_preset_for_event(item: dict, preset: dict | None = None) -> dict:
    effective = dict(preset or {})
    if item.get("frame_preset_id"):
        effective["id"] = item.get("frame_preset_id")
    overrides = {
        "frame_border_enabled": "border_enabled",
        "frame_border_width": "border_width",
        "frame_border_color": "border_color",
        "frame_bg_color": "bg_color",
        "frame_bg_opacity": "bg_opacity",
        "frame_shadow_depth": "shadow_depth",
        "frame_clearance_px": "clearance_px",
        "frame_clearance_factor": "clearance_factor",
        "frame_wrap_ratio": "wrap_ratio",
        "frame_jagged_outer_px": "jagged_outer_px",
        "frame_jagged_inner_px": "jagged_inner_px",
        "frame_jagged_spacing_px": "jagged_spacing_px",
        "frame_jagged_spacing_min_jitter_px": "jagged_spacing_min_jitter_px",
        "frame_jagged_spacing_max_jitter_px": "jagged_spacing_max_jitter_px",
        "frame_jagged_pattern": "jagged_pattern",
        "frame_halftone_enabled": "halftone_enabled",
        "frame_halftone_scale": "halftone_scale",
        "frame_halftone_density": "halftone_scale",
        "frame_halftone_dot_size": "halftone_dot_size",
        "frame_halftone_opacity": "halftone_opacity",
        "frame_halftone_color": "halftone_color",
    }
    for source_key, target_key in overrides.items():
        value = item.get(source_key, None)
        if value is None or value == "":
            continue
        effective[target_key] = value
    return effective


DECORATION_STYLE_FIELDS = {
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
}


def decoration_events_with_global(decoration: dict, subtitles: list[dict]) -> list[dict]:
    global_event = dict(decoration.get("global_event") or {})
    if not global_event:
        return [dict(item) for item in subtitles]
    style_defaults = {key: global_event.get(key) for key in DECORATION_STYLE_FIELDS if key in global_event}
    merged: list[dict] = []
    for item in subtitles:
        event = dict(item)
        if event.get("style_override_enabled") is not True:
            for key in DECORATION_STYLE_FIELDS:
                event.pop(key, None)
            merged.append({**event, **style_defaults})
        else:
            merged.append({**style_defaults, **event})
    return merged


def timeline_start_sec(item: dict) -> float:
    return float(item.get("output_start_sec", item.get("start_sec", 0.0)) or 0.0)


def timeline_end_sec(item: dict, fallback_start: float | None = None) -> float:
    start = timeline_start_sec(item) if fallback_start is None else fallback_start
    return float(item.get("output_end_sec", item.get("end_sec", start)) or start)


def decoration_payload_for_plan(project_id: str, plan: dict, ass_source_srt: Path | None = None) -> dict:
    base = require_project(project_id)
    decoration_path = base / "decoration" / "decoration_project.json"
    decoration = json.loads(decoration_path.read_text(encoding="utf-8")) if decoration_path.exists() else {}
    decoration_payload = dict(decoration) if isinstance(decoration, dict) else {}
    if not decoration_payload:
        decoration_payload = load_decoration_presets()

    decoration_events = [dict(item) for item in decoration_payload.get("events", []) or []]
    by_key: dict[str, dict] = {}
    for event in decoration_events:
        for key in (event.get("subtitle_id"), event.get("id")):
            key_text = str(key or "").strip()
            if key_text:
                by_key[key_text] = event

    merged_events: list[dict] = []
    for index, sub in enumerate(plan.get("subtitles", []) or [], start=1):
        subtitle = dict(sub)
        lookup_keys = [
            str(subtitle.get("subtitle_id") or "").strip(),
            str(subtitle.get("id") or "").strip(),
            f"sub_{index:04d}",
        ]
        style_event = next((by_key[key] for key in lookup_keys if key and key in by_key), {})
        merged = {**style_event, **subtitle}
        output_start = subtitle.get("output_start_sec")
        output_end = subtitle.get("output_end_sec")
        if output_start is not None:
            merged["start_sec"] = output_start
        if output_end is not None:
            merged["end_sec"] = output_end
        if style_event.get("id") and not subtitle.get("id"):
            merged["id"] = style_event["id"]
        if subtitle.get("id"):
            merged["subtitle_id"] = subtitle.get("id")
        merged_events.append(merged)

    decoration_payload["events"] = merged_events
    existing_scenes = {
        str(scene.get("id") or "").strip(): dict(scene)
        for scene in (decoration_payload.get("scenes") or [])
        if str(scene.get("id") or "").strip()
    }
    output_scenes: list[dict] = []
    for index, event in enumerate(merged_events, start=1):
        scene_id = str(event.get("scene_id") or f"scene_{index:04d}")
        existing = existing_scenes.get(scene_id, {})
        start = timeline_start_sec(event)
        end = timeline_end_sec(event, start)
        output_scenes.append(
            {
                **existing,
                "id": scene_id,
                "label": existing.get("label") or f"#{index}",
                "start_sec": round(start, 3),
                "end_sec": round(max(start + 0.001, end), 3),
                "comment_ids": existing.get("comment_ids") or [str(event.get("subtitle_id") or event.get("id") or f"sub_{index:04d}")],
                "text": event.get("text", existing.get("text", "")),
            }
        )
    decoration_payload["scenes"] = output_scenes
    decoration_payload["source_srt"] = str(ass_source_srt or resolve_project_path(project_id, "subtitles", "edited.srt"))
    return decoration_payload


def subtitle_rotation_deg(item: dict) -> float:
    for key in ("text_rotation_deg", "font_rotation_deg", "subtitle_rotation_deg", "angle"):
        try:
            value = item.get(key, None)
            if value is None:
                continue
            return float(value)
        except Exception:
            continue
    return 0.0


def wrap_text_to_width(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    for paragraph in value.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            candidate = current + ch
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines or [""]


def effect_tags(effect_group: dict | None = None, emotion: str | None = None) -> str:
    effects = [str(effect).strip() for effect in (effect_group or {}).get("effects", []) if str(effect).strip()]
    tags: list[str] = []
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


def frame_tags(frame_preset: dict | None = None) -> str:
    preset = frame_preset or {}
    effects = [str(effect).strip() for effect in preset.get("effects", []) if str(effect).strip()]
    frame_id = str(preset.get("id", "")).strip()
    border_enabled = preset.get("border_enabled", True)
    border_width = max(0, int(float(preset.get("border_width", 4) or 4)))
    border_color = ass_color(preset.get("border_color", "#000000"))
    shadow_depth = max(0, int(float(preset.get("shadow_depth", 2) or 2)))
    bg_opacity = float(preset.get("bg_opacity", 0.9) or 0.0)
    blur = 0
    if frame_id in {"frame_bubble_soft"} or "bubble_soft" in effects:
        border_width = max(border_width, 3)
        shadow_depth = max(shadow_depth, 0)
        blur = max(blur, 1)
    elif frame_id in {"frame_bubble_jagged"} or "jagged" in effects:
        border_width = max(border_width, 4)
        shadow_depth = max(shadow_depth, 0)
        blur = max(blur, 0)
    elif frame_id in {"frame_bubble_round"} or "bubble_round" in effects:
        border_width = max(border_width, 4)
        shadow_depth = max(shadow_depth, 1)
        blur = max(blur, 0)
    elif frame_id in {"frame_manga_thick"} or "manga_thick" in effects:
        border_width = max(border_width, 6)
        shadow_depth = max(shadow_depth, 0)
    elif frame_id in {"frame_manga_soft"} or "manga_soft" in effects:
        border_width = max(border_width, 3)
        blur = max(blur, 1)
    elif frame_id in {"frame_hand_drawn"} or "hand_drawn" in effects:
        border_width = max(border_width, 4)
        blur = max(blur, 1)
    elif frame_id in {"frame_shadow_box"} or "shadow_box" in effects:
        shadow_depth = max(shadow_depth, 4)
        blur = max(blur, 0)
    elif frame_id in {"frame_note_paper"} or "note_paper" in effects:
        border_width = max(border_width, 2)
        shadow_depth = max(shadow_depth, 1)
        blur = max(blur, 0)
    if bg_opacity <= 0:
        border_enabled = False
        border_width = 0
        shadow_depth = 0
    if not border_enabled:
        border_width = 0
        shadow_depth = 0
    tags = [f"\\bord{border_width}", f"\\shad{shadow_depth}", f"\\3c{border_color}"]
    if blur:
        tags.append(f"\\blur{blur}")
    return "".join(tags)


def decoration_scale_for_canvas(canvas_size: tuple[int, int]) -> float:
    _, height = canvas_size
    return max(0.1, float(height or 720) / 720.0)


def scaled_decoration_font(font: dict, canvas_size: tuple[int, int]) -> dict:
    scale = decoration_scale_for_canvas(canvas_size)
    scaled = dict(font or {})
    scaled["size"] = int(round(float(scaled.get("size", 44) or 44) * scale))
    scaled["outline_width"] = int(round(float(scaled.get("outline_width", 4) or 4) * scale))
    scaled["shadow_depth"] = int(round(float(scaled.get("shadow_depth", 4) or 4) * scale))
    return scaled


def frame_canvas_geometry(item: dict, frame_preset: dict, layout: dict, font: dict, canvas_size: tuple[int, int] = (1280, 720)) -> dict:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    width, height = canvas_size
    scale = decoration_scale_for_canvas(canvas_size)
    effective = effective_frame_preset_for_event(item, frame_preset)
    font_family = clean_font_family_name(str(item.get("font_family") or font.get("family", "Yu Gothic")))
    font_path = find_font_file(font_family)
    font_size = max(12, int(round(float(item.get("font_size", font.get("size", 44)) or 44) * scale)))
    try:
        pil_font = ImageFont.truetype(str(font_path), font_size) if font_path else ImageFont.load_default()
    except Exception:
        pil_font = ImageFont.load_default()
    text = str(item.get("text") or "")
    speaker = str(item.get("speaker_label") or "").strip()
    if speaker:
        text = f"{speaker}: {text}"
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    clearance_factor_value = effective.get("clearance_factor", None)
    if clearance_factor_value is None or clearance_factor_value == "":
        clearance_px = max(0, int(float(effective.get("clearance_px", 0) or 0)))
    else:
        clearance_factor = max(0.0, float(clearance_factor_value))
        clearance_px = max(0, int(round(font_size * clearance_factor)))
    wrap_ratio = float(effective.get("wrap_ratio", 0.88) or 0.88)
    wrap_ratio = max(0.40, min(0.98, wrap_ratio))
    pad_x = max(int(round(24 * scale)), int(font_size * 0.9) + clearance_px)
    pad_y = max(int(round(16 * scale)), int(font_size * 0.6) + clearance_px)
    max_box_w = max(1, int(width * wrap_ratio))
    max_text_width = max(1, max_box_w - pad_x * 2)
    lines = wrap_text_to_width(draw, text, pil_font, max_text_width)
    line_boxes = [draw.textbbox((0, 0), line or " ", font=pil_font) for line in lines]
    line_heights = [(box[3] - box[1]) for box in line_boxes]
    line_widths = [(box[2] - box[0]) for box in line_boxes]
    text_w = max(line_widths) if line_widths else 0
    line_gap = max(1, int(round(8 * scale)))
    text_h = sum(line_heights) + max(0, len(lines) - 1) * line_gap
    box_w = min(max_box_w, max(1, text_w + pad_x * 2))
    margin = max(1, int(round(30 * scale)))
    edge_margin = max(1, int(round(8 * scale)))
    box_h = min(height - int(round(40 * scale)), text_h + pad_y * 2)
    layout_anchor = str(layout.get("anchor", "bottom_center"))
    positions = {
        "top_left": (margin, margin),
        "top_center": ((width - box_w) // 2, margin),
        "top_right": (width - box_w - margin, margin),
        "middle_left": (margin, (height - box_h) // 2),
        "middle_center": ((width - box_w) // 2, (height - box_h) // 2),
        "middle_right": (width - box_w - margin, (height - box_h) // 2),
        "bottom_left": (margin, height - box_h - margin),
        "bottom_center": ((width - box_w) // 2, height - box_h - margin),
        "bottom_right": (width - box_w - margin, height - box_h - margin),
    }
    x, y = positions.get(layout_anchor, positions["bottom_center"])
    layout_offset_x = float(item.get("layout_offset_x_px", layout.get("offset_x_px", 0)) or 0.0) * scale
    layout_offset_default = 18 if layout_anchor.startswith("bottom_") else 0
    layout_offset_y = float(item.get("layout_offset_y_px", layout.get("offset_y_px", layout_offset_default)) or 0.0) * scale
    x += int(round(layout_offset_x))
    y += int(round(layout_offset_y))
    x = max(edge_margin, min(width - box_w - edge_margin, int(x)))
    y = max(edge_margin, min(height - box_h - edge_margin, int(y)))
    return {
        "canvas": canvas,
        "draw": draw,
        "font": pil_font,
        "box": (x, y, x + box_w, y + box_h),
        "lines": lines,
        "line_heights": line_heights,
        "line_widths": line_widths,
        "line_gap": line_gap,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "clearance_px": clearance_px,
        "clearance_factor": clearance_factor_value,
        "wrap_ratio": wrap_ratio,
        "text": text,
        "text_center": (x + box_w / 2.0, y + box_h / 2.0),
        "text_width": text_w,
        "text_height": text_h,
    }


def render_frame_overlay_image(
    item: dict,
    frame_preset: dict,
    layout: dict,
    font: dict,
    *,
    canvas_size: tuple[int, int] = (1280, 720),
    output_path: Path | None = None,
) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    scale = decoration_scale_for_canvas(canvas_size)
    geometry = frame_canvas_geometry(item, frame_preset, layout, font, canvas_size=canvas_size)
    box = geometry["box"]
    width, height = canvas_size
    kind = frame_kind(frame_preset)
    if kind == "none":
        return None
    rotation = subtitle_rotation_deg(item)
    border_enabled = frame_preset.get("border_enabled", True) is not False
    border_width = max(0, int(round(float(frame_preset.get("border_width", 4) or 4) * scale)))
    border_color = rgba_from_hex(frame_preset.get("border_color", "#000000"), 1.0)
    bg_hex = frame_preset.get("bg_color", "#ffffff")
    bg_color = rgba_from_hex(bg_hex, frame_preset.get("bg_opacity", 0.9))
    shadow_depth = max(0, int(round(float(frame_preset.get("shadow_depth", 2) or 2) * scale)))
    halftone_enabled = bool(frame_preset.get("halftone_enabled", False))
    halftone_scale = max(4, int(round(float(frame_preset.get("halftone_scale", 16) or 16) * scale)))
    halftone_dot_size = max(1, int(round(float(frame_preset.get("halftone_dot_size", 2) or 2) * scale)))
    halftone_opacity = max(0.0, min(1.0, float(frame_preset.get("halftone_opacity", 0.24) or 0.0)))
    halftone_color = rgba_from_hex(bg_hex, halftone_opacity)

    if bg_color[3] <= 0 and not halftone_enabled:
        border_enabled = False
        border_width = 0
        shadow_depth = 0
    if not border_enabled:
        border_width = 0

    if bg_color[3] <= 0 and border_width <= 0 and shadow_depth <= 0 and not (halftone_enabled and halftone_color[3] > 0):
        return None

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_shadow = ImageDraw.Draw(shadow_layer)
    draw = ImageDraw.Draw(canvas)
    x1, y1, x2, y2 = [int(value) for value in box]
    radius = max(12, min(40, (y2 - y1) // 3))
    if kind == "bubble_soft":
        radius = max(radius, 24)
    elif kind == "jagged_bubble":
        radius = 0
    elif kind == "note_paper":
        radius = max(8, min(18, radius // 2))
    elif kind == "manga_thick":
        radius = 6
    elif kind == "hand_drawn":
        radius = max(10, radius - 6)

    def rounded_box(target_draw: ImageDraw.ImageDraw, fill: tuple[int, int, int, int] | None, outline: tuple[int, int, int, int] | None = None, width_value: int = 0, offset: tuple[int, int] = (0, 0), use_radius: int = radius) -> None:
        left = x1 + offset[0]
        top = y1 + offset[1]
        right = x2 + offset[0]
        bottom = y2 + offset[1]
        outline_width = max(1, width_value) if outline is not None and width_value > 0 else 1
        if use_radius > 0:
            if outline is not None and width_value > 0:
                target_draw.rounded_rectangle((left, top, right, bottom), radius=use_radius, fill=fill, outline=outline, width=outline_width)
            else:
                target_draw.rounded_rectangle((left, top, right, bottom), radius=use_radius, fill=fill)
        else:
            if outline is not None and width_value > 0:
                target_draw.rectangle((left, top, right, bottom), fill=fill, outline=outline, width=outline_width)
            else:
                target_draw.rectangle((left, top, right, bottom), fill=fill)

    def hand_drawn_points(jitter: int = 5) -> list[tuple[int, int]]:
        seed = int(float(item.get("seed", 0) or 0))
        points = []
        base_points = [
            (x1, y1),
            ((x1 + x2) // 2, y1),
            (x2, y1),
            (x2, (y1 + y2) // 2),
            (x2, y2),
            ((x1 + x2) // 2, y2),
            (x1, y2),
            (x1, (y1 + y2) // 2),
        ]
        for index, (px, py) in enumerate(base_points):
            wobble = ((seed + index * 13) % (jitter * 2 + 1)) - jitter
            wobble_y = ((seed // 3 + index * 17) % (jitter * 2 + 1)) - jitter
            points.append((px + wobble, py + wobble_y))
        return points

    def jagged_points(outer_pad: int | None = None, inner_pad: int | None = None) -> list[tuple[int, int]]:
        seed = int(float(item.get("seed", 0) or 0))
        left = x1
        top = y1
        right = x2
        bottom = y2
        width_span = max(1, right - left)
        height_span = max(1, bottom - top)
        outer_value = max(1, int(float(frame_preset.get("jagged_outer_px", outer_pad if outer_pad is not None else max(10, border_width + 8)) or 12)))
        inner_value = max(0, int(float(frame_preset.get("jagged_inner_px", inner_pad if inner_pad is not None else max(4, border_width + 2)) or 5)))
        spacing = max(6, int(float(frame_preset.get("jagged_spacing_px", 28) or 28)))
        min_jitter = max(0, int(float(frame_preset.get("jagged_spacing_min_jitter_px", 4) or 0)))
        max_jitter = max(0, int(float(frame_preset.get("jagged_spacing_max_jitter_px", 6) or 0)))
        pattern = str(frame_preset.get("jagged_pattern", "alternate") or "alternate").strip().lower()

        def edge_positions(length: int, edge_index: int) -> list[int]:
            positions = [0]
            current = 0
            step_index = 0
            while current < length:
                span = min_jitter + max_jitter + 1
                jitter_seed = seed + edge_index * 97 + step_index * 31
                jitter = (jitter_seed % span) - min_jitter if span > 0 else 0
                step = max(4, spacing + jitter)
                current += step
                if current < length:
                    positions.append(current)
                step_index += 1
            if positions[-1] != length:
                positions.append(length)
            return positions

        points: list[tuple[int, int]] = []
        point_index = 0

        def is_outer() -> bool:
            if pattern in {"random", "rand", "randomized"}:
                return ((seed + point_index * 53) % 2) == 0
            if pattern in {"short_long_short", "short-long-short", "sls"}:
                return point_index % 3 == 1
            return point_index % 2 == 0

        for pos in edge_positions(width_span, 0)[:-1]:
            points.append((left + pos, top - outer_value if is_outer() else top + inner_value))
            point_index += 1
        for pos in edge_positions(height_span, 1)[:-1]:
            points.append((right + outer_value if is_outer() else right - inner_value, top + pos))
            point_index += 1
        for pos in edge_positions(width_span, 2)[:-1]:
            points.append((right - pos, bottom + outer_value if is_outer() else bottom - inner_value))
            point_index += 1
        for pos in edge_positions(height_span, 3)[:-1]:
            points.append((left - outer_value if is_outer() else left + inner_value, bottom - pos))
            point_index += 1
        return points

    if shadow_depth > 0:
        shadow_alpha = min(170, 40 + shadow_depth * 22)
        shadow_fill = (0, 0, 0, shadow_alpha)
        shadow_outline = (0, 0, 0, min(190, shadow_alpha + 30))
        if kind == "hand_drawn":
            points = hand_drawn_points(jitter=max(3, shadow_depth + 1))
            draw_shadow.polygon([(px + shadow_depth, py + shadow_depth) for px, py in points], fill=shadow_fill, outline=shadow_outline)
        elif kind == "jagged_bubble":
            points = jagged_points(outer_pad=max(10, shadow_depth + 8), inner_pad=max(4, shadow_depth + 2))
            draw_shadow.polygon([(px + shadow_depth, py + shadow_depth) for px, py in points], fill=shadow_fill, outline=shadow_outline)
        else:
            rounded_box(draw_shadow, shadow_fill, shadow_outline, max(0, border_width + 1), offset=(shadow_depth, shadow_depth), use_radius=radius)
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=max(1, shadow_depth)))
        canvas = Image.alpha_composite(canvas, shadow_layer)
        draw = ImageDraw.Draw(canvas)

    def apply_halftone_fill(base_canvas: Image.Image) -> Image.Image:
        if not (halftone_enabled and halftone_color[3] > 0):
            return base_canvas
        tone_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        tone_draw = ImageDraw.Draw(tone_layer)
        shape_mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(shape_mask)
        if kind in {"bubble_round", "bubble_soft", "manga_soft", "note_paper"}:
            mask_draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=255)
            if kind == "note_paper":
                fold_size = max(12, min(28, (y2 - y1) // 5))
                mask_draw.polygon([(x2 - fold_size, y1), (x2, y1), (x2, y1 + fold_size)], fill=255)
        elif kind == "jagged_bubble":
            mask_draw.polygon(jagged_points(outer_pad=max(10, border_width + 8), inner_pad=max(4, border_width + 2)), fill=255)
        elif kind == "hand_drawn":
            mask_draw.polygon(hand_drawn_points(jitter=max(4, border_width + 1)), fill=255)
        else:
            mask_draw.rectangle((x1, y1, x2, y2), fill=255)
        dot_radius = max(1, min(halftone_dot_size, int(round(halftone_scale * 0.45))))
        for row, cy in enumerate(range(y1 + halftone_scale // 2, y2, halftone_scale)):
            row_shift = (halftone_scale // 2) if row % 2 else 0
            for col, cx in enumerate(range(x1 + halftone_scale // 2 + row_shift, x2, halftone_scale)):
                if ((row + col) % 2) != 0:
                    continue
                tone_draw.ellipse((cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius), fill=halftone_color)
        tone_layer = Image.composite(tone_layer, Image.new("RGBA", (width, height), (0, 0, 0, 0)), shape_mask)
        return Image.alpha_composite(base_canvas, tone_layer)

    if kind == "hand_drawn":
        points = hand_drawn_points(jitter=max(4, border_width + 1))
        if bg_color[3] > 0 and not halftone_enabled:
            draw.polygon(points, fill=bg_color)
        canvas = apply_halftone_fill(canvas)
        draw = ImageDraw.Draw(canvas)
        if border_width > 0:
            for stroke in range(max(1, min(border_width, 4))):
                offset = stroke - max(1, min(border_width, 4)) // 2
                shifted = [(px + offset, py + offset) for px, py in points]
                draw.line(shifted + [shifted[0]], fill=border_color, width=max(1, border_width - stroke))
    elif kind == "jagged_bubble":
        points = jagged_points(outer_pad=max(10, border_width + 8), inner_pad=max(4, border_width + 2))
        if bg_color[3] > 0 and not halftone_enabled:
            draw.polygon(points, fill=bg_color)
        canvas = apply_halftone_fill(canvas)
        draw = ImageDraw.Draw(canvas)
        if border_width > 0:
            draw.line(points + [points[0]], fill=border_color, width=max(1, border_width))
    else:
        if bg_color[3] > 0 and not halftone_enabled:
            if kind in {"bubble_round", "bubble_soft", "manga_soft", "note_paper"}:
                rounded_box(draw, bg_color, None, 0, use_radius=radius)
            else:
                draw.rectangle((x1, y1, x2, y2), fill=bg_color)
        canvas = apply_halftone_fill(canvas)
        draw = ImageDraw.Draw(canvas)
        if border_width > 0:
            outline = border_color
            if kind in {"bubble_round", "bubble_soft", "manga_soft", "note_paper"}:
                rounded_box(draw, None, outline, border_width, use_radius=radius)
            else:
                draw.rectangle((x1, y1, x2, y2), outline=outline, width=max(1, border_width))
        if kind == "note_paper":
            fold_size = max(12, min(28, (y2 - y1) // 5))
            fold_fill = (255, 244, 204, min(220, bg_color[3] + 20))
            fold_outline = border_color if border_width > 0 else (200, 180, 120, 200)
            draw.polygon([(x2 - fold_size, y1), (x2, y1), (x2, y1 + fold_size)], fill=fold_fill, outline=fold_outline)
            draw.line([(x2 - fold_size, y1), (x2 - fold_size, y1 + fold_size), (x2, y1 + fold_size)], fill=fold_outline, width=max(1, border_width or 1))

    if output_path is None:
        return None
    if abs(rotation) > 0.01:
        margin = max(border_width + shadow_depth + 12, 24)
        local_box = (
            max(0, x1 - margin),
            max(0, y1 - margin),
            min(width, x2 + margin),
            min(height, y2 + margin),
        )
        local = canvas.crop(local_box)
        rotated = local.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)
        base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        center_x = (local_box[0] + local_box[2]) / 2.0
        center_y = (local_box[1] + local_box[3]) / 2.0
        paste_x = int(round(center_x - rotated.width / 2.0))
        paste_y = int(round(center_y - rotated.height / 2.0))
        base.alpha_composite(rotated, (paste_x, paste_y))
        canvas = base
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def generate_decoration_overlays(project_id: str, decoration: dict, canvas_size: tuple[int, int] = (1280, 720)) -> list[dict]:
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
    subtitles = decoration.get("events")
    if subtitles is None:
        subtitles = json.loads(source_path.read_text(encoding="utf-8")) if source_path.suffix.lower() == ".json" else None
        if subtitles is None:
            from .srt import parse_srt

            subtitles = parse_srt(source_path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(subtitles, dict):
        subtitles = subtitles.get("subtitles", [])
    subtitles = [item for item in subtitles or [] if item.get("enabled", True)]
    subtitles = decoration_events_with_global(decoration, subtitles)
    defaults = load_decoration_presets()
    font_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("font_presets", []), decoration.get("font_presets"))}
    layout_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("layout_presets", []), decoration.get("layout_presets"))}
    frame_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("frame_presets", []), decoration.get("frame_presets"))}
    emotion_presets = load_emotion_presets()
    project_ui_state = project_info(project_id).get("ui_state") or {}
    project_ass_style = normalize_ass_subtitle_style(project_ui_state.get("ass_subtitle_defaults"))
    preset_default_font = next(iter(font_presets.values()), {"family": "Yu Gothic", "size": 44, "color": "#ffffff", "outline_color": "#000000", "outline_width": 4})
    default_font = {
        **preset_default_font,
        "family": project_ass_style["font_name"],
        "size": project_ass_style["font_size"],
        "color": project_ass_style["primary_color"],
        "outline_color": project_ass_style["outline_color"],
        "outline_width": project_ass_style["outline_width"],
        "shadow_depth": project_ass_style["shadow_depth"],
    }
    default_layout = next(iter(layout_presets.values()), {"anchor": "bottom_center"})
    overlay_dir = base / "temp" / "decoration_overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict] = []
    for index, item in enumerate(subtitles):
        emotion_preset = next(
            (
                preset
                for preset in emotion_presets
                if str(preset.get("id", "")).strip() == str(item.get("emotion_preset_id", "")).strip()
            ),
            resolve_emotion_preset(item.get("emotion"), emotion_presets),
        )
        font = font_presets.get(item.get("font_preset_id")) or font_presets.get(emotion_preset.get("font_preset_id")) or default_font
        frame_preset = effective_frame_preset_for_event(
            item,
            frame_presets.get(item.get("frame_preset_id")) or frame_presets.get("frame_none") or {},
        )
        layout = layout_presets.get(item.get("layout_preset_id")) or default_layout
        item_ass_override = normalize_ass_subtitle_style(item.get("ass_style"), include_enabled=True)
        item_ass_style = dict(project_ass_style)
        if item_ass_override.get("enabled"):
            item_ass_style.update({key: value for key, value in item_ass_override.items() if key != "enabled"})
        font_for_geometry = dict(font)
        font_for_geometry["family"] = str(item.get("font_family") or item_ass_style["font_name"] or font.get("family", "Yu Gothic"))
        font_for_geometry["size"] = int(float(item.get("font_size") or item_ass_style["font_size"] or font.get("size", 44)))
        start = timeline_start_sec(item)
        end = timeline_end_sec(item, start + 1.0)
        overlay_path = overlay_dir / f"frame_{index:04d}.png"
        created = render_frame_overlay_image(item, frame_preset, layout, font_for_geometry, canvas_size=canvas_size, output_path=overlay_path)
        if created is None:
            continue
        generated.append({
            "path": str(created),
            "start_sec": start,
            "end_sec": end,
        })
    return generated


def flatten_static_overlays_to_alpha_video(
    project_id: str,
    overlays: list[dict],
    duration_sec: float,
    canvas_size: tuple[int, int],
    *,
    name: str = "static_overlays",
) -> dict | None:
    static_overlays = [
        overlay
        for overlay in overlays
        if not overlay.get("animated") and not overlay.get("sequence") and Path(str(overlay.get("path") or "")).exists()
    ]
    if not static_overlays:
        return None
    try:
        from PIL import Image
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pillowを読み込めません: {exc}") from exc

    base = require_project(project_id)
    work_dir = base / "temp" / "flattened_overlays" / name
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    width, height = canvas_size
    duration = max(0.1, float(duration_sec or 0.1))

    points = {0.0, duration}
    normalized: list[dict] = []
    for overlay in static_overlays:
        start = max(0.0, min(duration, float(overlay.get("start_sec", 0.0) or 0.0)))
        end = max(start, min(duration, float(overlay.get("end_sec", start) or start)))
        if end - start < 0.001:
            continue
        item = {**overlay, "start_sec": start, "end_sec": end}
        normalized.append(item)
        points.add(start)
        points.add(end)
    if not normalized:
        return None

    blank_path = work_dir / "blank.png"
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank_path)
    sorted_points = sorted(points)
    state_cache: dict[tuple[str, ...], Path] = {(): blank_path}
    concat_entries: list[tuple[Path, float]] = []

    for index, (start, end) in enumerate(zip(sorted_points, sorted_points[1:]), start=1):
        span = end - start
        if span < 0.001:
            continue
        midpoint = start + span / 2.0
        active = [
            overlay
            for overlay in normalized
            if float(overlay["start_sec"]) <= midpoint < float(overlay["end_sec"])
        ]
        key = tuple(str(Path(str(overlay["path"])).resolve()) for overlay in active)
        frame_path = state_cache.get(key)
        if frame_path is None:
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            for overlay in active:
                image = Image.open(overlay["path"]).convert("RGBA")
                if image.size != (width, height):
                    image = image.resize((width, height), Image.Resampling.LANCZOS)
                canvas.alpha_composite(image)
            frame_path = work_dir / f"state_{len(state_cache):04d}.png"
            canvas.save(frame_path)
            state_cache[key] = frame_path
        if concat_entries and concat_entries[-1][0] == frame_path:
            concat_entries[-1] = (frame_path, concat_entries[-1][1] + span)
        else:
            concat_entries.append((frame_path, span))

    concat_path = work_dir / "concat.txt"

    def concat_path_text(path: Path) -> str:
        return path.resolve().as_posix().replace("'", r"'\''")

    lines: list[str] = []
    for frame_path, span in concat_entries:
        lines.append(f"file '{concat_path_text(frame_path)}'\n")
        lines.append(f"duration {max(0.001, span):.6f}\n")
    lines.append(f"file '{concat_path_text(concat_entries[-1][0])}'\n")
    atomic_write_text(concat_path, "".join(lines))

    output_path = work_dir / f"{name}.mov"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-vsync",
            "vfr",
            "-c:v",
            "qtrle",
            "-pix_fmt",
            "argb",
            str(output_path),
        ],
        base / "temp" / "logs" / f"{name}.log",
    )
    return {
        "path": str(output_path),
        "start_sec": 0.0,
        "end_sec": duration,
        "type": name,
        "animated": True,
        "flattened_count": len(normalized),
        "state_count": len(state_cache),
    }


def reaction_dialogues(item: dict, effect_group: dict | None, start: float, end: float, style_name: str) -> list[str]:
    effects = {str(effect).strip() for effect in (effect_group or {}).get("effects", []) if str(effect).strip()}
    text = str(item.get("text", "") or "")
    seed = int(float(item.get("seed", 0) or 0))
    reactions: list[tuple[str, str]] = []
    if ("☆" in text or "★" in text) and ("star_reaction" in effects or "sparkle" in effects):
        reactions.append(("☆", r"\1c&H66FFFF&\3c&H000000&"))
    if ("♡" in text or "♥" in text) and ("heart_reaction" in effects or "heart" in effects):
        reactions.append(("♡", r"\1c&HCC66FF&\3c&H000000&"))
    lines: list[str] = []
    duration_ms = max(400, int((end - start) * 1000))
    for reaction_index, (char, color_tags) in enumerate(reactions):
        for i in range(3):
            offset = (seed + reaction_index * 97 + i * 37) % 120
            x1 = 560 + ((offset * 17) % 170)
            y1 = 560 - ((offset * 11) % 80)
            x2 = x1 + (((offset % 5) - 2) * 20)
            y2 = max(120, y1 - 110 - i * 18)
            size = 34 + ((offset + i * 9) % 18)
            delay = min(duration_ms - 200, i * 130)
            tags = rf"\an5\fs{size}\bord2\shad1{color_tags}\move({x1},{y1},{x2},{y2},{delay},{duration_ms})\fad(60,260)"
            lines.append(
                f"Dialogue: 1,{ass_timecode(start)},{ass_timecode(end)},"
                f"{style_name},,0,0,0,,{{{tags}}}{char}"
            )
    return lines


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


def ass_alignment_position(alignment: int, margins: tuple[int, int, int], canvas_size: tuple[int, int]) -> tuple[float, float]:
    alignment = max(1, min(9, int(alignment or 2)))
    margin_l, margin_r, margin_v = margins
    width, height = canvas_size
    column = (alignment - 1) % 3
    row = (alignment - 1) // 3
    x = float(margin_l) if column == 0 else float(width) / 2.0 if column == 1 else float(width - margin_r)
    y = float(height - margin_v) if row == 0 else float(height) / 2.0 if row == 1 else float(margin_v)
    return x, y


def build_plain_ass(
    project_id: str,
    subtitles: list[dict],
    output_path: Path,
    *,
    canvas_size: tuple[int, int] = (1280, 720),
) -> Path:
    """Build an ASS subtitle file without decoration-page effects or frames."""
    require_project(project_id)
    project_ui_state = project_info(project_id).get("ui_state") or {}
    default_style = normalize_ass_subtitle_style(project_ui_state.get("ass_subtitle_defaults"))
    scale = decoration_scale_for_canvas(canvas_size)
    style_name = "Default"
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(canvas_size[0])}",
        f"PlayResY: {int(canvas_size[1])}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: "
        + ",".join(
            [
                style_name,
                clean_font_family_name(default_style["font_name"]),
                str(int(round(default_style["font_size"] * scale))),
                ass_color(default_style["primary_color"]),
                ass_color(default_style["primary_color"]),
                ass_color(default_style["outline_color"]),
                ass_color("#000000"),
                "-1" if default_style["bold"] else "0",
                "-1" if default_style["italic"] else "0",
                "0",
                "0",
                "100",
                "100",
                str(default_style["spacing"]),
                "0",
                "1",
                str(round(default_style["outline_width"] * scale, 2)),
                str(round(default_style["shadow_depth"] * scale, 2)),
                str(default_style["alignment"]),
                str(default_style["margin_l"]),
                str(default_style["margin_r"]),
                str(default_style["margin_v"]),
                "1",
            ]
        ),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    ass_lines.extend(ass_comment_line(line, style=style_name) for line in default_ai_ass_prompt_lines())
    for item in subtitles or []:
        if item.get("enabled", True) is False or not str(item.get("text") or "").strip():
            continue
        start = timeline_start_sec(item)
        end = max(start + 0.01, timeline_end_sec(item, start))
        override = normalize_ass_subtitle_style(item.get("ass_style"), include_enabled=True)
        style = dict(default_style)
        if override.get("enabled"):
            style.update({key: value for key, value in override.items() if key != "enabled"})
        alignment = int(style["alignment"])
        x, y = ass_alignment_position(
            alignment,
            (style["margin_l"], style["margin_r"], style["margin_v"]),
            canvas_size,
        )
        tags = [
            f"\\an{alignment}",
            f"\\pos({x:.1f},{y:.1f})",
            f"\\fn{sanitize_ass_text(style['font_name'])}",
            f"\\fs{int(round(style['font_size'] * scale))}",
            f"\\1c{ass_color(style['primary_color'])}",
            f"\\3c{ass_color(style['outline_color'])}",
            f"\\bord{round(style['outline_width'] * scale, 2)}",
            f"\\shad{round(style['shadow_depth'] * scale, 2)}",
            "\\b1" if style["bold"] else "\\b0",
            "\\i1" if style["italic"] else "\\i0",
            f"\\fsp{style['spacing']}",
        ]
        ass_lines.append(
            f"Dialogue: 0,{ass_timecode(start)},{ass_timecode(end)},{style_name},,"
            f"{style['margin_l']},{style['margin_r']},{style['margin_v']},,"
            f"{{{''.join(tags)}}}{sanitize_ass_text(item.get('text', ''))}"
        )
    atomic_write_text(output_path, "\n".join(ass_lines) + "\n", encoding="utf-8")
    return output_path


def build_decoration_ass(
    project_id: str,
    decoration: dict,
    output_path: Path | None = None,
    *,
    include_caption_text: bool = True,
    canvas_size: tuple[int, int] = (1280, 720),
) -> Path:
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
    subtitles = decoration.get("events") or None
    if subtitles is None:
        subtitles = json.loads(source_path.read_text(encoding="utf-8")) if source_path.suffix.lower() == ".json" else None
        if subtitles is None:
            from .srt import parse_srt

            subtitles = parse_srt(source_path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(subtitles, dict):
        subtitles = subtitles.get("subtitles", [])
    subtitles = [item for item in subtitles or [] if item.get("enabled", True)]
    subtitles = decoration_events_with_global(decoration, subtitles)
    defaults = load_decoration_presets()
    font_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("font_presets", []), decoration.get("font_presets"))}
    effect_groups = {item.get("id"): item for item in merge_preset_list(defaults.get("effect_groups", []), decoration.get("effect_groups"))}
    layout_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("layout_presets", []), decoration.get("layout_presets"))}
    frame_presets = {item.get("id"): item for item in merge_preset_list(defaults.get("frame_presets", []), decoration.get("frame_presets"))}
    emotion_presets = load_emotion_presets()
    project_ui_state = project_info(project_id).get("ui_state") or {}
    project_ass_style = normalize_ass_subtitle_style(project_ui_state.get("ass_subtitle_defaults"))
    preset_default_font = next(iter(font_presets.values()), {"family": "Yu Gothic", "size": 44, "color": "#ffffff", "outline_color": "#000000", "outline_width": 4})
    default_font = {
        **preset_default_font,
        "family": project_ass_style["font_name"],
        "size": project_ass_style["font_size"],
        "color": project_ass_style["primary_color"],
        "outline_color": project_ass_style["outline_color"],
        "outline_width": project_ass_style["outline_width"],
        "shadow_depth": project_ass_style["shadow_depth"],
    }
    play_res_x, play_res_y = canvas_size
    scale = decoration_scale_for_canvas(canvas_size)
    ass_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(play_res_x)}",
        f"PlayResY: {int(play_res_y)}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
    ]
    style_name = "DecorText"
    ass_lines.append(
        "Style: "
        + ",".join(
            [
                style_name,
                clean_font_family_name(str(default_font.get("family", "Yu Gothic"))),
                str(int(round(float(default_font.get("size", 44) or 44) * scale))),
                ass_color(default_font.get("color", "#ffffff")),
                ass_color(default_font.get("color", "#ffffff")),
                ass_color(default_font.get("outline_color", "#000000")),
                ass_color("#000000"),
                "-1" if project_ass_style["bold"] else "0",
                "-1" if project_ass_style["italic"] else "0",
                "0",
                "0",
                "100",
                "100",
                str(project_ass_style["spacing"]),
                "0",
                "1",
                str(max(0, int(round(float(default_font.get("outline_width", 4) or 4) * scale)))),
                str(max(0, int(round(float(default_font.get("shadow_depth", 4) or 4) * scale)))),
                str(project_ass_style["alignment"]),
                str(project_ass_style["margin_l"]),
                str(project_ass_style["margin_r"]),
                str(project_ass_style["margin_v"]),
                "1",
            ]
        )
    )
    ass_lines += [
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    ass_lines.extend(ass_comment_line(line, style=style_name) for line in default_ai_ass_prompt_lines())
    default_layout = next(iter(layout_presets.values()), {"anchor": "bottom_center"})
    for item in subtitles:
        start = timeline_start_sec(item)
        end = timeline_end_sec(item, start + 1.0)
        emotion_preset = next(
            (
                preset
                for preset in emotion_presets
                if str(preset.get("id", "")).strip() == str(item.get("emotion_preset_id", "")).strip()
            ),
            resolve_emotion_preset(item.get("emotion"), emotion_presets),
        )
        font = font_presets.get(item.get("font_preset_id")) or font_presets.get(emotion_preset.get("font_preset_id")) or default_font
        effect_group = (
            effect_groups.get(item.get("text_effect_group_id"))
            or effect_groups.get(item.get("effect_group_id"))
            or effect_groups.get(emotion_preset.get("effect_group_id"))
        )
        frame_preset = effective_frame_preset_for_event(
            item,
            frame_presets.get(item.get("frame_preset_id")) or frame_presets.get("frame_none") or {},
        )
        layout = layout_presets.get(item.get("layout_preset_id")) or default_layout
        if include_caption_text:
            item_ass_override = normalize_ass_subtitle_style(item.get("ass_style"), include_enabled=True)
            item_ass_style = dict(project_ass_style)
            if item_ass_override.get("enabled"):
                item_ass_style.update({key: value for key, value in item_ass_override.items() if key != "enabled"})
            font_family = clean_font_family_name(str(item.get("font_family") or item_ass_style["font_name"] or font.get("family", "Yu Gothic")))
            font_size = int(round(float(item.get("font_size") or item_ass_style["font_size"] or font.get("size", 44)) * scale))
            outline_enabled = item.get("font_outline_enabled", True)
            outline_source = item.get("font_outline_width") if item.get("font_outline_width") is not None else item_ass_style["outline_width"]
            outline = max(0, int(round(float(outline_source) * scale)))
            if outline_enabled is False:
                outline = 0
            shadow = max(0, int(round(float(item_ass_style["shadow_depth"]) * scale)))
            rotation = subtitle_rotation_deg(item)
            primary = ass_color(item.get("font_color") or item_ass_style["primary_color"] or font.get("color", "#ffffff"))
            outline_color = ass_color(item.get("font_outline_color") or item_ass_style["outline_color"] or font.get("outline_color", "#000000"))
            font_for_geometry = dict(font)
            font_for_geometry["family"] = font_family
            font_for_geometry["size"] = int(float(item.get("font_size") or item_ass_style["font_size"] or font.get("size", 44)))
            geometry = frame_canvas_geometry(item, frame_preset or {}, layout, font_for_geometry, canvas_size=canvas_size)
            has_decoration_layout = bool(item.get("layout_preset_id") or item.get("frame_preset_id"))
            if has_decoration_layout:
                text_center_x, text_center_y = geometry["text_center"]
                text_alignment = 5
            else:
                text_alignment = item_ass_style["alignment"]
                text_center_x, text_center_y = ass_alignment_position(
                    text_alignment,
                    (item_ass_style["margin_l"], item_ass_style["margin_r"], item_ass_style["margin_v"]),
                    canvas_size,
                )
            wrapped_text = r"\N".join(sanitize_ass_text(line) for line in geometry.get("lines", []) if line is not None) or sanitize_ass_text(item.get("text", ""))
            text_tags = [
                f"\\an{text_alignment}",
                f"\\pos({text_center_x:.1f},{text_center_y:.1f})",
                f"\\fn{sanitize_ass_text(font_family)}",
                f"\\fs{font_size}",
                f"\\1c{primary}",
                f"\\3c{outline_color}",
                f"\\bord{outline}",
                f"\\shad{shadow}",
                "\\b1" if item_ass_style["bold"] else "\\b0",
                "\\i1" if item_ass_style["italic"] else "\\i0",
                f"\\fsp{item_ass_style['spacing']}",
            ]
            if abs(rotation) > 0.01:
                text_tags.append(f"\\frz{rotation:.2f}")
            text_tags.append(effect_tags(effect_group, item.get("emotion")))
            ass_lines.append(
                f"Dialogue: 1,{ass_timecode(start)},{ass_timecode(end)},"
                f"{style_name},,{item_ass_style['margin_l']},{item_ass_style['margin_r']},{item_ass_style['margin_v']},,{{{''.join(text_tags)}}}{wrapped_text}"
            )
        ass_lines.extend(reaction_dialogues(item, effect_group, start, end, style_name))
    ass_text = "\n".join(ass_lines) + "\n"
    ass_path = output_path or (base / "decoration" / "decorated.ass")
    atomic_write_text(ass_path, ass_text, encoding="utf-8")
    return ass_path


def shifted_decoration_for_preview(decoration: dict, start_sec: float, duration_sec: float) -> dict:
    start = max(0.0, float(start_sec or 0.0))
    end = start + max(0.1, float(duration_sec or 0.1))
    shifted = copy.deepcopy(decoration or {})

    def shift_item_times(item: dict) -> dict | None:
        raw_start = timeline_start_sec(item)
        raw_end = timeline_end_sec(item, raw_start)
        if raw_end < start or raw_start > end:
            return None
        item["start_sec"] = round(max(0.0, raw_start - start), 3)
        item["end_sec"] = round(max(item["start_sec"] + 0.001, min(raw_end, end) - start), 3)
        for prefix in ("output", "range_relative", "source", "original"):
            start_key = f"{prefix}_start_sec"
            end_key = f"{prefix}_end_sec"
            if start_key in item:
                item[start_key] = round(max(0.0, float(item.get(start_key) or 0.0) - start), 3)
            if end_key in item:
                item[end_key] = round(max(0.0, float(item.get(end_key) or 0.0) - start), 3)
        return item

    shifted["events"] = [item for item in (shift_item_times(event) for event in shifted.get("events", []) or []) if item]
    shifted["scenes"] = [item for item in (shift_item_times(scene) for scene in shifted.get("scenes", []) or []) if item]

    return shifted


def render_decoration_video(
    project_id: str,
    decoration: dict,
    preview: bool = True,
    max_height: int | None = 480,
    fps: int | None = None,
    start_sec: float | None = None,
    duration_sec: float | None = None,
) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    source_video = project_source_video(project_id)
    source_info = probe_video(str(source_video))
    source_canvas_size = (int(source_info.get("width") or 1280), int(source_info.get("height") or 720))
    preview_height = int(max_height or 0) if preview else 0
    if preview_height > 0:
        preview_height = max(144, min(1080, preview_height))
    preview_fps = max(1, min(60, int(fps or 10))) if preview else 0
    preview_duration = 0.0
    if preview and duration_sec:
        preview_duration = max(5.0, min(300.0, float(duration_sec)))
    preview_start = max(0.0, float(start_sec or 0.0)) if preview else 0.0
    render_decoration = shifted_decoration_for_preview(decoration, preview_start, preview_duration) if preview_start > 0 and preview_duration > 0 else decoration
    if preview and preview_height > 0 and source_canvas_size[1] > 0:
        exact_width = source_canvas_size[0] * preview_height / source_canvas_size[1]
        preview_width = max(2, int(round(exact_width / 2.0) * 2))
        canvas_size = (preview_width, preview_height)
    else:
        canvas_size = source_canvas_size
    ass_path = build_decoration_ass(project_id, render_decoration, base / "decoration" / "decorated.ass", include_caption_text=True, canvas_size=canvas_size)
    frame_overlays = generate_decoration_overlays(project_id, render_decoration, canvas_size=canvas_size)
    out_dir = base / ("preview" if preview else "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / ("decorated_preview.mp4" if preview else "decorated_final.mp4")
    log_path = base / "temp" / "logs" / ("decoration_preview.log" if preview else "decoration_final.log")
    ass_filter_path = ass_path.name.replace("'", r"\'")
    filter_parts: list[str] = []
    last_label = "[0:v]"
    if preview and preview_height > 0:
        filter_parts.append(f"{last_label}scale={canvas_size[0]}:{canvas_size[1]},setsar=1[vpreviewbase]")
        last_label = "[vpreviewbase]"
    decoration_duration = max((timeline_end_sec(item, timeline_start_sec(item)) for item in render_decoration.get("events", []) or []), default=0.0)
    pseudo_plan = {
        "segments": [{"output_start_sec": 0.0, "output_end_sec": max(0.1, decoration_duration)}],
        "scenes": render_decoration.get("scenes") or [],
    }
    screen_filter_expr, applied_effects = build_screen_effect_filter_chain(pseudo_plan, render_decoration)
    sequence_fps = 24
    if preview:
        sequence_fps = 6 if preview_height <= 240 or preview_fps <= 3 else 12
    screen_overlays = generate_screen_effect_overlays(
        project_id,
        pseudo_plan,
        render_decoration,
        canvas_size=canvas_size,
        sequence_fps=sequence_fps,
        speed_lines_as_video=preview,
    )
    flattened_frame_overlay = flatten_static_overlays_to_alpha_video(
        project_id,
        frame_overlays,
        preview_duration if preview_duration > 0 else max(0.1, decoration_duration),
        canvas_size,
        name="preview_frame_overlays" if preview else "decoration_frame_overlays",
    )
    overlays = [*screen_overlays]
    if flattened_frame_overlay:
        overlays.append(flattened_frame_overlay)
    else:
        overlays.extend(frame_overlays)
    if screen_filter_expr:
        filter_parts.append(f"{last_label}{screen_filter_expr}[vfx]")
        last_label = "[vfx]"
    for index, overlay in enumerate(overlays, start=1):
        overlay_path = Path(overlay["path"])
        start_sec = float(overlay.get("start_sec", 0.0) or 0.0)
        end_sec = float(overlay.get("end_sec", start_sec + 1.0) or (start_sec + 1.0))
        filter_parts.append(
            f"{last_label}[{index}:v]overlay=0:0:eof_action=pass:enable='between(t,{start_sec:.3f},{end_sec:.3f})'"
            f"[v{index}]"
        )
        last_label = f"[v{index}]"
        overlays[index - 1]["path"] = str(overlay_path)
    if preview_height > 0:
        final_filter = f"subtitles=filename='{ass_filter_path}',fps={preview_fps}"
    else:
        final_filter = f"subtitles=filename='{ass_filter_path}'"
    if preview_duration > 0:
        final_filter = f"{final_filter},trim=end={preview_duration:.3f},setpts=PTS-STARTPTS"
    filter_parts.append(f"{last_label}{final_filter}[vout]")
    preview_crf = "36" if preview and preview_height and preview_height <= 240 and preview_fps <= 3 else "30"
    filter_complex = ";".join(filter_parts)
    render_cwd = ass_path.parent

    def render_arg_path(path: Path | str) -> str:
        try:
            return os.path.relpath(Path(path), render_cwd)
        except Exception:
            return str(path)

    filter_script_path = base / "temp" / "logs" / ("decoration_preview_filter.txt" if preview else "decoration_render_filter.txt")
    atomic_write_text(filter_script_path, filter_complex)
    inputs = [*(["-ss", f"{preview_start:.3f}"] if preview_start > 0 else []), "-i", render_arg_path(source_video)]
    for overlay in overlays:
        if overlay.get("sequence"):
            inputs.extend([
                "-framerate",
                str(int(overlay.get("framerate") or 24)),
                "-itsoffset",
                f"{float(overlay.get('start_sec', 0.0) or 0.0):.3f}",
                "-i",
                render_arg_path(overlay["path"]),
            ])
        elif overlay.get("animated"):
            inputs.extend(["-itsoffset", f"{float(overlay.get('start_sec', 0.0) or 0.0):.3f}", "-i", render_arg_path(overlay["path"])])
        else:
            inputs.extend(["-loop", "1", "-i", render_arg_path(overlay["path"])])
    run_command(
        [
            "ffmpeg",
            "-y",
            *ffmpeg_cfr_args(),
            *inputs,
            "-filter_complex_script",
            render_arg_path(filter_script_path),
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast" if preview else "veryfast",
            "-crf",
            preview_crf if preview else "18",
            *([] if not preview else ["-r", str(preview_fps)]),
            *([] if preview_duration <= 0 else ["-t", f"{preview_duration:.3f}"]),
            "-c:a",
            "copy",
            "-pix_fmt",
            "yuv420p",
            render_arg_path(output_path),
        ],
        log_path,
        cwd=render_cwd,
    )
    audit_project_event(
        project_id,
        "decoration.render",
        context={
            "preview": preview,
            "max_height": preview_height or None,
            "fps": preview_fps or None,
            "start_sec": preview_start or None,
            "duration_sec": preview_duration or None,
            "crf": preview_crf if preview else "18",
            "screen_effects": applied_effects,
            "screen_effect_scope": "source_video_only",
            "source_canvas_size": source_canvas_size,
            "render_canvas_size": canvas_size,
            "overlay_sequence_fps": sequence_fps,
            "ass_path": str(ass_path),
            "output_path": str(output_path),
        },
    )
    return {
        "ass_path": str(ass_path),
        "video_path": str(output_path),
        "video_url": f"/api/projects/{project_id}/media/{'preview' if preview else 'output'}/{output_path.name}",
        "max_height": preview_height or None,
        "fps": preview_fps or None,
        "start_sec": preview_start or None,
        "duration_sec": preview_duration or None,
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
    try:
        info = read_json_repairing_extra_data(info_path)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"project.jsonを読み込めません: {exc}") from exc
    if not isinstance(info, dict):
        raise HTTPException(status_code=500, detail="project.jsonの形式が不正です")
    return info


def update_project_info(project_id: str, updates: dict) -> dict:
    base = require_project(project_id)
    info_path = base / "project.json"
    if not info_path.exists():
        raise HTTPException(status_code=404, detail="project.jsonが見つかりません")
    try:
        current = read_json_repairing_extra_data(info_path)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"project.jsonを読み込めません: {exc}") from exc
    if not isinstance(current, dict):
        raise HTTPException(status_code=500, detail="project.jsonの形式が不正です")
    current.update(updates or {})
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(info_path, current, backup=True)
    return current


def list_projects() -> list[dict]:
    if not PROJECTS_DIR.exists():
        return []
    items: list[dict] = []
    for project_dir_path in PROJECTS_DIR.iterdir():
        if not project_dir_path.is_dir():
            continue
        info_path = project_dir_path / "project.json"
        if not info_path.exists():
            continue
        try:
            info = read_json_repairing_extra_data(info_path)
        except Exception:
            continue
        if not isinstance(info, dict):
            continue
        source_video = str(info.get("source_video", ""))
        source_name = Path(source_video).name if source_video else ""
        items.append(
            {
                "project_id": project_dir_path.name,
                "project_name": info.get("project_name") or project_dir_path.name,
                "source_video": source_video,
                "source_video_name": source_name,
                "created_at": info.get("created_at"),
                "updated_at": info.get("updated_at") or datetime.fromtimestamp(info_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "has_edit_plan": (project_dir_path / "edit_plan.json").exists(),
                "has_transcript": (project_dir_path / "transcript" / "transcript.json").exists(),
                "has_decoration": (project_dir_path / "decoration" / "decoration_project.json").exists(),
                "has_output": any((project_dir_path / "output").glob("final.*")),
                "workflow": info.get("workflow") if isinstance(info.get("workflow"), dict) else None,
            }
        )
    items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return items


def delete_project(project_id: str) -> None:
    base = require_project(project_id).resolve()
    try:
        base.relative_to(PROJECTS_DIR.resolve())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="プロジェクトの削除先が不正です") from exc
    shutil.rmtree(base, ignore_errors=False)


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


def find_mpv_executable() -> str | None:
    candidates = [
        shutil.which("mpv"),
        shutil.which("mpv.exe"),
        str(ROOT / "tools" / "mpv" / "mpv.exe"),
        str(ROOT / "tools" / "mpv-x86_64" / "mpv.exe"),
        r"C:\Program Files\mpv\mpv.exe",
        r"C:\Program Files (x86)\mpv\mpv.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def default_mpv_target(project_id: str, target: str = "decoration_preview") -> Path:
    normalized = str(target or "decoration_preview").strip().lower()
    candidates: list[tuple[str, str]]
    if normalized in {"source", "source_video"}:
        return project_source_video(project_id)
    if normalized in {"final", "output"}:
        candidates = [("output", "final.mp4"), ("output", "final.mkv"), ("output", "decorated_final.mp4")]
    elif normalized in {"preview", "cut_preview"}:
        candidates = [("preview", "preview_low.mp4"), ("preview", "decorated_preview.mp4")]
    else:
        candidates = [("preview", "decorated_preview.mp4"), ("preview", "preview_low.mp4")]
    for folder, filename in candidates:
        path = resolve_project_path(project_id, folder, filename)
        if path.exists():
            return path
    raise HTTPException(status_code=404, detail="MPVで開けるプレビュー動画が見つかりません。先にプレビューを作成してください。")


def launch_mpv(project_id: str, target: str = "decoration_preview", path: str | None = None, pause: bool = False) -> dict:
    mpv = find_mpv_executable()
    if not mpv:
        raise HTTPException(status_code=500, detail="MPVが見つかりません。mpv.exeをPATHに追加するか、tools/mpv/mpv.exe に配置してください。")
    normalized_target = str(target or "decoration_ass").strip().lower()
    extra_args: list[str] = []
    if normalized_target in {"decoration_ass", "ass", "no_encode", "source_ass"}:
        media_path = project_source_video(project_id)
        decoration = load_project_decoration(project_id) or load_decoration_presets()
        source_info = probe_video(str(media_path))
        canvas_size = (int(source_info.get("width") or 1280), int(source_info.get("height") or 720))
        ass_path = build_decoration_ass(project_id, decoration, require_project(project_id) / "decoration" / "mpv_no_encode_preview.ass", include_caption_text=True, canvas_size=canvas_size)
        extra_args.extend([
            "--sub-auto=no",
            "--sid=no",
            f"--sub-file={ass_path}",
        ])
    else:
        media_path = resolve_project_path(project_id, path) if path else default_mpv_target(project_id, target)
    if not media_path.exists():
        raise HTTPException(status_code=404, detail="MPVで開く動画ファイルが見つかりません")
    args = [
        mpv,
        "--force-window=yes",
        "--keep-open=yes",
        "--no-terminal",
        f"--title=切り抜き動画工房 preview - {media_path.name}",
        *extra_args,
    ]
    if pause:
        args.append("--pause")
    args.append(str(media_path))
    subprocess.Popen(args, cwd=str(ROOT), close_fds=True)
    audit_event("mpv.launch", project_id=project_id, context={"target": target, "path": str(media_path), "mpv": mpv, "no_encode": bool(extra_args)})
    return {"started": True, "player": mpv, "path": str(media_path), "mode": normalized_target, "no_encode": bool(extra_args)}


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


def ensure_project_edit_plan(project_id: str) -> dict:
    path = resolve_project_path(project_id, "edit_plan.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    base = require_project(project_id)
    info = project_info(project_id)
    source_video_value = str(info.get("source_video") or "").strip()
    if not source_video_value:
        raise HTTPException(status_code=404, detail="元動画情報が見つかりません")

    transcript_path = base / "transcript" / "transcript.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.exists() else {}
    if not transcript:
        raise HTTPException(status_code=404, detail="transcript.jsonが見つかりません")

    if not transcript.get("subtitles") and transcript.get("aligned_subtitles"):
        transcript = dict(transcript)
        transcript["subtitles"] = transcript.get("aligned_subtitles") or []

    duration_sec = float((transcript.get("waveform") or {}).get("duration_sec", 0.0) or 0.0)
    if duration_sec <= 0:
        duration_sec = float(probe_video(str(project_source_video(project_id))).get("duration_sec", 0.0) or 0.0)
    if duration_sec <= 0:
        raise HTTPException(status_code=500, detail="最終出力用の動画長を取得できません")

    correction = dict(transcript.get("subtitle_correction") or {})
    settings = {
        "detection_mode": transcript.get("detection_mode") or correction.get("detection_mode") or "vad",
        "voice_isolation_enabled": bool((transcript.get("voice_isolation") or {}).get("enabled", False)),
        "use_isolated_voice_for_vad": bool((transcript.get("voice_isolation") or {}).get("enabled", False)),
        "use_isolated_voice_for_whisper": bool((transcript.get("voice_isolation") or {}).get("enabled", False)),
        "pre_margin_sec": correction.get("pre_margin_sec", 0.3),
        "post_margin_sec": correction.get("post_margin_sec", 0.5),
        "min_speech_duration_sec": correction.get("min_speech_duration_sec", 0.2),
        "merge_silence_gap_sec": correction.get("merge_silence_gap_sec", 0.5),
        "silence_threshold_db": correction.get("silence_threshold_db", -35.0),
        "manual_cut_segments": [],
        "protected_segments": [],
    }

    plan = build_edit_plan(
        source_video_value,
        {"start_sec": 0.0, "end_sec": round(duration_sec, 3)},
        transcript.get("silences") or [],
        transcript,
        settings,
    )
    plan = normalize_edit_plan_source_video(project_id, plan)
    atomic_write_json(path, plan, backup=True)
    audit_project_event(
        project_id,
        "edit_plan.auto_created",
        context={"source_video": source_video_value, "duration_sec": round(duration_sec, 3), "subtitles": len(plan.get("subtitles", [])), "segments": len(plan.get("segments", []))},
    )
    return plan


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
            "screen_effect_stack_ids": [],
            "subtitle_style_preset_id": "subtitle_emotion_surprise",
            "comment_ids": ["sub_0007", "sub_0008"],
        }
    ]
    data = _load_json_file(SCENES_SAMPLE, fallback)
    return data if isinstance(data, list) else fallback


def load_decoration_presets() -> dict:
    fallback = {
        "effect_library": [
            {"id": "sparkle", "name": "きらめき"},
            {"id": "pop_in", "name": "ポップイン"},
            {"id": "shake", "name": "揺れ"},
            {"id": "float_in", "name": "浮遊"},
            {"id": "heart", "name": "ハート"},
            {"id": "star_reaction", "name": "☆反応"},
            {"id": "heart_reaction", "name": "♡反応"},
        ],
        "screen_effect_library": [
            {"id": "shutter_24fps", "name": "24fpsシャッター"},
            {"id": "sepia", "name": "セピア"},
            {"id": "disco", "name": "ディスコ"},
            {"id": "vignette", "name": "ビネット"},
            {"id": "cinema", "name": "シネマ"},
            {"id": "monochrome", "name": "モノクロ"},
            {"id": "old_tv", "name": "古いテレビ"},
            {"id": "vhs", "name": "VHS"},
            {"id": "crt", "name": "CRT"},
            {"id": "retro_game", "name": "レトロゲーム"},
            {"id": "neon", "name": "ネオン"},
            {"id": "cyberpunk", "name": "サイバーパンク"},
            {"id": "horror", "name": "ホラー"},
            {"id": "dream", "name": "ドリーム"},
            {"id": "rainy", "name": "雨の日"},
            {"id": "sunset", "name": "夕焼け"},
            {"id": "docu_low_sat", "name": "ドキュメンタリー低彩度"},
            {"id": "pop_high_sat", "name": "ポップ高彩度"},
            {"id": "noise", "name": "ノイズ"},
            {"id": "film_grain", "name": "フィルム粒子"},
            {"id": "scanlines", "name": "走査線"},
            {"id": "chromatic_aberration", "name": "色ずれ"},
            {"id": "edge_blur", "name": "周辺ぼかし"},
            {"id": "background_blur", "name": "背景ぼかし"},
            {"id": "highlight_subject", "name": "中央強調"},
            {"id": "shadow_boost", "name": "暗部持ち上げ"},
            {"id": "highlight_suppress", "name": "白飛び抑制"},
            {"id": "sharpen", "name": "シャープ"},
            {"id": "cinematic_border", "name": "シネマ帯"},
            {"id": "glitch", "name": "グリッチ"},
            {"id": "rgb_shift", "name": "RGBシフト"},
            {"id": "flash", "name": "フラッシュ"},
            {"id": "strobe", "name": "ストロボ"},
            {"id": "fade", "name": "フェード"},
            {"id": "shake", "name": "シェイク"},
            {"id": "hand_tremor", "name": "手ぶれ"},
            {"id": "miniature", "name": "ミニチュア"},
            {"id": "fisheye", "name": "魚眼"},
            {"id": "speed_lines", "name": "集中線"},
            {"id": "speed_lines_sparse", "name": "集中線 荒め"},
            {"id": "speed_lines_white", "name": "集中線 白抜き"},
            {"id": "speed_lines_slash", "name": "斜めスピード線"},
            {"id": "speed_lines_frame", "name": "外周集中線"},
            {"id": "speed_lines_burst", "name": "爆発集中線"},
            {"id": "speed_lines_outward", "name": "外向き放射線"},
            {"id": "anime_edge", "name": "アニメ輪郭"},
            {"id": "halftone", "name": "単色ハーフトーン"},
            {"id": "video_zoom", "name": "拡大・縮小"},
            {"id": "zoom_blur", "name": "ズームブラー"},
            {"id": "radial_blur", "name": "放射ブラー"},
            {"id": "impact_flash", "name": "衝撃フラッシュ"},
            {"id": "action_shake", "name": "アクション揺れ"},
            {"id": "mirror", "name": "ミラー"},
            {"id": "split_mirror", "name": "分割ミラー"},
            {"id": "kaleidoscope", "name": "万華鏡"},
            {"id": "pixelate", "name": "ドット化"},
            {"id": "posterize", "name": "階調削減"},
            {"id": "oil_paint", "name": "油絵"},
            {"id": "watercolor", "name": "水彩"},
            {"id": "pencil_sketch", "name": "鉛筆スケッチ"},
            {"id": "pseudo_hdr", "name": "擬似HDR"},
            {"id": "skin_tone", "name": "肌色補正"},
            {"id": "auto_brightness", "name": "自動明るさ"},
            {"id": "game_sharp", "name": "ゲーム鮮明化"},
            {"id": "text_readability", "name": "文字視認性"},
            {"id": "dark_game", "name": "暗いゲーム補正"},
            {"id": "white_balance", "name": "ホワイトバランス"},
            {"id": "spotlight", "name": "スポットライト"},
            {"id": "iris_out", "name": "丸絞り暗転"},
            {"id": "drifting_stars", "name": "流れ星"},
            {"id": "drifting_hearts", "name": "ハート漂い"},
            {"id": "heart_wipe", "name": "ハートワイプ"},
            {"id": "heart_burst", "name": "広がって消えるハート"},
            {"id": "heart_rain", "name": "ハート雨"},
            {"id": "heart_float_up", "name": "ハート浮上"},
            {"id": "heart_confetti", "name": "ハート紙吹雪"},
            {"id": "heart_sparkle", "name": "ハートきらめき"},
            {"id": "heart_tunnel", "name": "ハートトンネル"},
            {"id": "heart_orbit_burst", "name": "回転ハートバースト"},
            {"id": "hearts", "name": "ハート"},
            {"id": "balloons", "name": "風船"},
            {"id": "stars", "name": "流星"},
            {"id": "snow", "name": "雪"},
        ],
        "screen_effect_stacks": [
            {
                "id": "screen_stack_cinema_soft",
                "name": "シネマ柔らか",
                "description": "落ち着いた色と軽い粒状感の組み合わせ",
                "effects": [
                    {"id": "cinema", "intensity": 0.55, "speed": 1, "color": "#ffffff"},
                    {"id": "vignette", "intensity": 0.4, "speed": 1, "color": "#000000"},
                    {"id": "film_grain", "intensity": 0.25, "speed": 1, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_vhs",
                "name": "VHS風",
                "description": "色ずれと走査線を重ねた昔の録画風",
                "effects": [
                    {"id": "vhs", "intensity": 0.8, "speed": 1, "color": "#ffffff"},
                    {"id": "scanlines", "intensity": 0.7, "speed": 1, "color": "#ffffff"},
                    {"id": "glitch", "intensity": 0.35, "speed": 1.2, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_neon",
                "name": "ネオン夜景",
                "description": "発色を強めて夜の街っぽく見せる",
                "effects": [
                    {"id": "neon", "intensity": 0.75, "speed": 1, "color": "#ff66cc"},
                    {"id": "chromatic_aberration", "intensity": 0.4, "speed": 1, "color": "#66ccff"},
                    {"id": "disco", "intensity": 0.25, "speed": 0.6, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_horror",
                "name": "ホラー",
                "description": "暗く冷たい雰囲気を作る",
                "effects": [
                    {"id": "horror", "intensity": 0.8, "speed": 1, "color": "#ffffff"},
                    {"id": "monochrome", "intensity": 0.35, "speed": 1, "color": "#ffffff"},
                    {"id": "noise", "intensity": 0.25, "speed": 1, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_dream",
                "name": "ドリーム",
                "description": "軽いボケとやわらかな彩度で夢っぽくする",
                "effects": [
                    {"id": "dream", "intensity": 0.6, "speed": 1, "color": "#ffffff"},
                    {"id": "fade", "intensity": 0.2, "speed": 0.8, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_manga_impact",
                "name": "漫画インパクト",
                "description": "集中線と衝撃フラッシュで強調する",
                "effects": [
                    {"id": "speed_lines", "intensity": 0.85, "speed": 1.0, "color": "#000000"},
                    {"id": "impact_flash", "intensity": 0.55, "speed": 1.2, "color": "#ffffff"},
                    {"id": "action_shake", "intensity": 0.35, "speed": 1.4, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_anime_line",
                "name": "アニメ輪郭",
                "description": "輪郭と漫画トーンを重ねる",
                "effects": [
                    {"id": "anime_edge", "intensity": 0.65, "speed": 1.0, "color": "#000000"},
                    {"id": "halftone", "intensity": 0.35, "speed": 1.0, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_halftone_coarse",
                "name": "網点粗め",
                "description": "粗い印刷っぽい単色ハーフトーン",
                "effects": [
                    {"id": "halftone", "intensity": 0.9, "speed": 1.0, "color": "#101010", "background_color": "#f7f1e3", "dot_density": 14, "dot_scale": 1.4, "contrast": 1.0, "rotation": 0.0},
                ],
            },
            {
                "id": "screen_stack_halftone_manga",
                "name": "マンガトーン",
                "description": "漫画のスクリーントーン風の単色網点",
                "effects": [
                    {"id": "halftone", "intensity": 0.95, "speed": 1.0, "color": "#111111", "background_color": "#ffffff", "dot_density": 28, "dot_scale": 0.95, "contrast": 1.18, "rotation": 0.785398},
                    {"id": "anime_edge", "intensity": 0.35, "speed": 1.0, "color": "#000000"},
                ],
            },
            {
                "id": "screen_stack_halftone_cdlabel",
                "name": "CDレーベル",
                "description": "昔のCD印刷っぽい細かい網点",
                "effects": [
                    {"id": "halftone", "intensity": 0.85, "speed": 1.0, "color": "#202020", "background_color": "#fefefe", "dot_density": 42, "dot_scale": 0.68, "contrast": 0.95, "rotation": 0.261799},
                    {"id": "vignette", "intensity": 0.18, "speed": 1.0, "color": "#000000"},
                ],
            },
            {
                "id": "screen_stack_fisheye_motion",
                "name": "魚眼モーション",
                "description": "魚眼と手ブレで動きを出す",
                "effects": [
                    {"id": "fisheye", "intensity": 0.45, "speed": 1.0, "color": "#ffffff"},
                    {"id": "hand_tremor", "intensity": 0.35, "speed": 1.2, "color": "#ffffff"},
                ],
            },
            {
                "id": "screen_stack_zoom_action",
                "name": "ズームアクション",
                "description": "ズームブラーと集中線のアクション表現",
                "effects": [
                    {"id": "zoom_blur", "intensity": 0.55, "speed": 1.0, "color": "#ffffff"},
                    {"id": "speed_lines", "intensity": 0.55, "speed": 1.0, "color": "#000000"},
                ],
            },
            {
                "id": "screen_stack_heart_burst",
                "name": "広がって消えるハート",
                "description": "ハートの輪郭が広がりながらフェードアウトする",
                "effects": [
                    {"id": "heart_burst", "intensity": 0.9, "speed": 1.0, "color": "#ff5ca8", "position_x": 0.5, "position_y": 0.5, "radius": 0.18, "expansion_speed": 1.0},
                ],
            },
            {
                "id": "screen_stack_heart_rain",
                "name": "ハート雨",
                "description": "画面上から小さなハートが降る",
                "effects": [
                    {"id": "heart_rain", "intensity": 0.78, "speed": 0.85, "color": "#ff5ca8", "symbol_count": 28, "radius": 0.055},
                ],
            },
            {
                "id": "screen_stack_heart_float",
                "name": "ハート浮上",
                "description": "下からハートがふわっと浮かぶ",
                "effects": [
                    {"id": "heart_float_up", "intensity": 0.72, "speed": 0.7, "color": "#ff83bd", "symbol_count": 22, "radius": 0.06},
                ],
            },
            {
                "id": "screen_stack_heart_confetti",
                "name": "ハート紙吹雪",
                "description": "中心からハートが弾ける",
                "effects": [
                    {"id": "heart_confetti", "intensity": 0.85, "speed": 1.25, "color": "#ff5ca8", "position_x": 0.5, "position_y": 0.5, "symbol_count": 34, "radius": 0.045},
                ],
            },
            {
                "id": "screen_stack_heart_sparkle",
                "name": "ハートきらめき",
                "description": "画面内で小さなハートが点滅する",
                "effects": [
                    {"id": "heart_sparkle", "intensity": 0.72, "speed": 1.0, "color": "#ff7ec8", "symbol_count": 26, "radius": 0.04},
                ],
            },
            {
                "id": "screen_stack_heart_tunnel",
                "name": "ハートトンネル",
                "description": "ハートの輪郭が奥から迫るように広がる",
                "effects": [
                    {"id": "heart_tunnel", "intensity": 0.8, "speed": 1.0, "color": "#ff5ca8", "position_x": 0.5, "position_y": 0.5},
                ],
            },
        ],
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
                "effects": ["sparkle", "pop_in", "shake", "star_reaction"],
                "description": "文字のポップ演出をまとめた基本セット",
            },
            {
                "id": "effect_group_yume_kawaii",
                "name": "ゆめかわ",
                "effects": ["heart", "float_in", "heart_reaction"],
                "description": "淡い色と軽い浮遊感のセット",
            },
        ],
        "frame_presets": [
            {"id": "frame_manga_round", "name": "漫画吹き出し", "effects": ["bubble_round"], "border_enabled": True, "border_width": 5, "border_color": "#111111", "bg_color": "#ffffff", "bg_opacity": 0.95, "shadow_depth": 2, "default_layout_id": "layout_bottom_center", "clearance_px": 18, "clearance_factor": 0.5, "wrap_ratio": 0.88, "halftone_enabled": False, "halftone_scale": 16, "halftone_dot_size": 2, "halftone_opacity": 0.24, "halftone_color": "#ffffff", "description": "普通の漫画の吹き出し"},
            {"id": "frame_manga_jagged", "name": "ギザギザ吹き出し", "effects": ["bubble_round", "jagged"], "border_enabled": True, "border_width": 5, "border_color": "#111111", "bg_color": "#ffffff", "bg_opacity": 0.95, "shadow_depth": 2, "default_layout_id": "layout_bottom_center", "clearance_px": 18, "clearance_factor": 0.5, "wrap_ratio": 0.88, "jagged_outer_px": 14, "jagged_inner_px": 5, "jagged_spacing_px": 28, "jagged_spacing_min_jitter_px": 4, "jagged_spacing_max_jitter_px": 6, "jagged_pattern": "alternate", "halftone_enabled": False, "halftone_scale": 16, "halftone_dot_size": 2, "halftone_opacity": 0.24, "halftone_color": "#ffffff", "description": "漫画吹き出しの外側をギザギザにした枠"},
            {"id": "frame_cloud_soft", "name": "ふわふわ吹き出し", "effects": ["bubble_soft"], "border_enabled": True, "border_width": 4, "border_color": "#222222", "bg_color": "#fffdf7", "bg_opacity": 0.9, "shadow_depth": 1, "default_layout_id": "layout_bottom_center", "clearance_px": 22, "clearance_factor": 0.5, "wrap_ratio": 0.86, "halftone_enabled": False, "halftone_scale": 16, "halftone_dot_size": 2, "halftone_opacity": 0.24, "halftone_color": "#fffdf7", "description": "雲のようなやわらかい吹き出し"},
            {"id": "frame_narration_top", "name": "ナレーション上", "effects": [], "border_enabled": False, "border_width": 0, "border_color": "#000000", "bg_color": "#ffffff", "bg_opacity": 0.0, "shadow_depth": 0, "default_layout_id": "layout_top_center", "clearance_px": 10, "clearance_factor": 0.5, "wrap_ratio": 0.92, "halftone_enabled": False, "halftone_scale": 16, "halftone_dot_size": 2, "halftone_opacity": 0.24, "halftone_color": "#ffffff", "description": "上配置の縁無しナレーション"},
            {"id": "frame_narration_bottom", "name": "ナレーション下", "effects": [], "border_enabled": False, "border_width": 0, "border_color": "#000000", "bg_color": "#ffffff", "bg_opacity": 0.0, "shadow_depth": 0, "default_layout_id": "layout_bottom_center", "clearance_px": 10, "clearance_factor": 0.5, "wrap_ratio": 0.92, "halftone_enabled": False, "halftone_scale": 16, "halftone_dot_size": 2, "halftone_opacity": 0.24, "halftone_color": "#ffffff", "description": "下配置の縁無しナレーション"},
        ],
        "layout_presets": [
            {"id": "layout_top_left", "name": "上左", "anchor": "top_left"},
            {"id": "layout_top_center", "name": "上中央", "anchor": "top_center"},
            {"id": "layout_top_right", "name": "上右", "anchor": "top_right"},
            {"id": "layout_top_left_inner", "name": "上左 内寄せ", "anchor": "top_left", "offset_x_px": 120, "offset_y_px": 70},
            {"id": "layout_top_center_lower", "name": "上中央 やや下", "anchor": "top_center", "offset_y_px": 70},
            {"id": "layout_top_right_inner", "name": "上右 内寄せ", "anchor": "top_right", "offset_x_px": -120, "offset_y_px": 70},
            {"id": "layout_middle_left", "name": "中央左", "anchor": "middle_left"},
            {"id": "layout_middle_center", "name": "中央", "anchor": "middle_center"},
            {"id": "layout_middle_right", "name": "中央右", "anchor": "middle_right"},
            {"id": "layout_middle_left_inner", "name": "中央左 内寄せ", "anchor": "middle_left", "offset_x_px": 120},
            {"id": "layout_middle_center_upper", "name": "中央 やや上", "anchor": "middle_center", "offset_y_px": -90},
            {"id": "layout_middle_right_inner", "name": "中央右 内寄せ", "anchor": "middle_right", "offset_x_px": -120},
            {"id": "layout_bottom_left", "name": "下左", "anchor": "bottom_left", "offset_y_px": 18},
            {"id": "layout_bottom_center", "name": "下中央", "anchor": "bottom_center", "offset_y_px": 18},
            {"id": "layout_bottom_right", "name": "下右", "anchor": "bottom_right", "offset_y_px": 18},
            {"id": "layout_bottom_left_inner", "name": "下左 内寄せ", "anchor": "bottom_left", "offset_x_px": 120, "offset_y_px": 18},
            {"id": "layout_bottom_center_low", "name": "下中央 さらに下", "anchor": "bottom_center", "offset_y_px": 42},
            {"id": "layout_bottom_right_inner", "name": "下右 内寄せ", "anchor": "bottom_right", "offset_x_px": -120, "offset_y_px": 18},
        ],
        "screen_effect_targets": {
            "global_stack_ids": [],
            "scene_stack_ids": {},
        },
    }
    data = _load_json_file(DECORATION_PRESETS_SAMPLE, fallback)
    shared = load_shared_decoration_presets()
    if not isinstance(data, dict):
        return fallback
    merged = dict(fallback)
    merged.update(data)
    for key in ["effect_library", "screen_effect_library", "screen_effect_stacks", "font_presets", "effect_groups", "frame_presets", "layout_presets"]:
        merged[key] = merge_preset_list(fallback.get(key, []), data.get(key, []))
    if isinstance(shared, dict):
        for key in ["effect_library", "screen_effect_library", "screen_effect_stacks", "font_presets", "effect_groups", "frame_presets", "layout_presets", "screen_effect_targets"]:
            if shared.get(key):
                if key == "screen_effect_targets":
                    merged[key] = shared.get(key)
                else:
                    merged[key] = merge_preset_list(merged.get(key, []), shared.get(key, []))
    for key in ["effect_library", "screen_effect_library", "screen_effect_stacks", "font_presets", "effect_groups", "frame_presets", "layout_presets"]:
        if not merged.get(key):
            merged[key] = fallback.get(key, [])
    if not merged.get("screen_effect_targets"):
        merged["screen_effect_targets"] = fallback["screen_effect_targets"]
    return merged


def load_shared_decoration_presets() -> dict:
    shared = _load_json_file(DECORATION_PRESETS_SHARED, {})
    if not shared and DECORATION_PRESETS_SHARED_LEGACY.exists():
        shared = _load_json_file(DECORATION_PRESETS_SHARED_LEGACY, {})
    if not isinstance(shared, dict):
        return {}
    return shared


def save_shared_decoration_presets(decoration: dict) -> dict:
    shared = load_shared_decoration_presets()
    current = {
        "effect_library": decoration.get("effect_library") or shared.get("effect_library") or [],
        "screen_effect_library": decoration.get("screen_effect_library") or shared.get("screen_effect_library") or [],
        "screen_effect_stacks": decoration.get("screen_effect_stacks") or shared.get("screen_effect_stacks") or [],
        "font_presets": decoration.get("font_presets") or shared.get("font_presets") or [],
        "effect_groups": decoration.get("effect_groups") or shared.get("effect_groups") or [],
        "frame_presets": decoration.get("frame_presets") or shared.get("frame_presets") or [],
        "layout_presets": decoration.get("layout_presets") or shared.get("layout_presets") or [],
        "screen_effect_targets": decoration.get("screen_effect_targets") or shared.get("screen_effect_targets") or {"global_stack_ids": [], "scene_stack_ids": {}},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(DECORATION_PRESETS_SHARED, current, backup=True)
    return current


def merge_preset_list(base: list[dict] | None, override: list[dict] | None) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in base or []:
        item_id = str(item.get("id", "")).strip()
        if item_id:
            merged[item_id] = dict(item)
    for item in override or []:
        item_id = str(item.get("id", "")).strip() or f"preset_{len(merged) + 1}"
        merged[item_id] = {**merged.get(item_id, {}), **dict(item), "id": item_id}
    return list(merged.values())


def preset_catalog() -> dict:
    return {
        "emotion_presets": load_emotion_presets(),
        "subtitle_style_presets": load_subtitle_style_presets(),
        "scenes": load_scene_catalog(),
        "decoration_presets": load_decoration_presets(),
        "emotion_labels": ["neutral", "joy", "anger", "sadness", "surprise", "fear", "embarrassment", "teasing"],
    }


def build_scene_catalog_from_subtitles(subtitles: list[dict], existing_scenes: list[dict] | None = None) -> list[dict]:
    existing_by_id: dict[str, dict] = {}
    for scene in existing_scenes or []:
        scene_id = str(scene.get("id", "")).strip()
        if not scene_id:
            continue
        existing_by_id[scene_id] = dict(scene)
    scenes: list[dict] = []
    enabled_subtitles = [sub for sub in (subtitles or []) if sub.get("enabled", True) is not False]
    for index, sub in enumerate(enabled_subtitles, start=1):
        scene_id = f"scene_{index:04d}"
        existing = existing_by_id.get(scene_id, {})
        start = float(sub.get("output_start_sec", sub.get("edited_start_sec", sub.get("start_sec", 0.0))) or 0.0)
        end = float(sub.get("output_end_sec", sub.get("edited_end_sec", sub.get("end_sec", start))) or start)
        comment_id = str(sub.get("id") or sub.get("subtitle_id") or f"sub_{index:04d}")
        sub["scene_id"] = scene_id
        scenes.append(
            {
                "id": scene_id,
                "label": f"#{index}",
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "emotion": str(sub.get("emotion") or existing.get("emotion") or "neutral"),
                "effect_group_id": str(sub.get("effect_group_id") or existing.get("effect_group_id") or ""),
                "screen_effect_stack_ids": list(sub.get("screen_effect_stack_ids") or existing.get("screen_effect_stack_ids") or []),
                "subtitle_style_preset_id": str(sub.get("subtitle_style_preset_id") or existing.get("subtitle_style_preset_id") or ""),
                "comment_ids": [comment_id] if comment_id else [],
                "text": str(sub.get("text") or ""),
            }
        )
    return sorted(
        scenes,
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


def resolve_export_profile(project_id: str, output_profile: str | None = None) -> dict:
    profile = str(output_profile or "").strip().lower()
    if not profile:
        info = project_info(project_id)
        ui_state = info.get("ui_state") or {}
        profile = str(ui_state.get("output_profile") or "mp4_compat").strip().lower()
    if profile in {"mp4", "mp4_compat", "compat", "compat_mp4"}:
        return {
            "profile": "mp4_compat",
            "container": "mp4",
            "extension": "mp4",
            "video_codec": "libx264",
            "audio_codec": "aac",
            "preview_video_codec": "libx264",
            "preview_audio_codec": "aac",
        }
    if profile in {"mp4_lossless", "mp4_ffv1_flac", "lossless_mp4"}:
        return {
            "profile": "mkv_lossless",
            "container": "mkv",
            "extension": "mkv",
            "video_codec": "ffv1",
            "audio_codec": "flac",
            "preview_video_codec": "libx264",
            "preview_audio_codec": "aac",
        }
    if profile in {"mkv", "mkv_lossless", "mkv_ffv1_flac", "lossless_mkv"}:
        return {
            "profile": "mkv_lossless",
            "container": "mkv",
            "extension": "mkv",
            "video_codec": "ffv1",
            "audio_codec": "flac",
            "preview_video_codec": "libx264",
            "preview_audio_codec": "aac",
        }
    raise HTTPException(status_code=400, detail="不正な出力プリセットです")


def normalize_subtitle_export_options(
    subtitle_mode: str | None = None,
    subtitle_format: str | None = None,
    burn_subtitles: bool = False,
) -> tuple[str, str]:
    mode = str(subtitle_mode or "external").strip().lower()
    subtitle_type = str(subtitle_format or "srt").strip().lower()
    if burn_subtitles and mode == "external":
        mode = "burn"
    if mode not in {"external", "burn", "embed"}:
        raise HTTPException(status_code=400, detail="字幕出力方式が不正です")
    if subtitle_type not in {"srt", "plain_ass", "ass"}:
        raise HTTPException(status_code=400, detail="字幕形式が不正です")
    return mode, subtitle_type


def embedded_subtitle_output_spec(video_path: Path, subtitle_format: str) -> tuple[Path, str]:
    if subtitle_format == "ass":
        return video_path.with_suffix(".mkv"), "ass"
    if video_path.suffix.lower() == ".mp4":
        return video_path, "mov_text"
    return video_path, "srt"


def mux_subtitle_track(
    project_id: str,
    video_path: Path,
    subtitle_path: Path,
    subtitle_format: str,
) -> tuple[Path, str]:
    base = require_project(project_id)
    output_path, subtitle_codec = embedded_subtitle_output_spec(video_path, subtitle_format)
    temp_output = output_path.with_name(f"{output_path.stem}_subtitle_mux{output_path.suffix}")
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(subtitle_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            subtitle_codec,
            "-metadata:s:s:0",
            "language=jpn",
            "-metadata:s:s:0",
            "title=Japanese",
            "-disposition:s:0",
            "default",
            str(temp_output),
        ],
        base / "temp" / "logs" / "final_subtitle_mux.log",
    )
    if output_path.exists() and output_path != video_path:
        output_path.unlink()
    temp_output.replace(output_path)
    if output_path != video_path and video_path.exists():
        video_path.unlink()
    return output_path, subtitle_codec


def sanitize_export_name(value: str | None, fallback: str = "output") -> str:
    name = str(value or "").strip()
    if Path(name).suffix.lower() in {".mp4", ".mkv", ".srt", ".ass"}:
        name = Path(name).stem
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")
    if not name:
        name = fallback
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if name.upper() in reserved:
        name = f"_{name}"
    return name[:160]


def _available_export_stem(directory: Path, stem: str, suffixes: list[str]) -> str:
    candidate = stem
    index = 2
    while any((directory / f"{candidate}{suffix}").exists() for suffix in suffixes):
        candidate = f"{stem}_{index}"
        index += 1
    return candidate


def _copy_export_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temp_path)
        last_error: PermissionError | None = None
        for attempt in range(5):
            try:
                os.replace(temp_path, destination)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise HTTPException(status_code=500, detail=f"出力先ファイルが使用中です: {destination}") from last_error
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def publish_export_result(
    project_id: str,
    result: dict,
    output_directory: str,
    output_filename: str | None = None,
    create_project_subdirectory: bool = False,
) -> dict:
    directory_text = str(output_directory or "").strip()
    if not directory_text:
        return result
    destination_root = Path(directory_text).expanduser()
    if not destination_root.is_absolute():
        raise HTTPException(status_code=400, detail="出力先は絶対パスで指定してください")
    try:
        destination_root = destination_root.resolve()
        destination_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"出力先を作成できません: {destination_root}") from exc

    info = project_info(project_id)
    project_name = sanitize_export_name(info.get("project_name"), project_id)
    destination = destination_root / project_name if create_project_subdirectory else destination_root
    destination.mkdir(parents=True, exist_ok=True)
    requested_stem = sanitize_export_name(output_filename, project_name)

    video_source = Path(str(result.get("video_path") or ""))
    if not video_source.exists():
        raise HTTPException(status_code=500, detail="出力済み動画が見つかりません")
    subtitle_source: Path | None = None
    if result.get("subtitle_mode") == "external":
        candidate = Path(str(result.get("subtitle_path") or ""))
        if candidate.exists():
            subtitle_source = candidate
    suffixes = [video_source.suffix]
    if subtitle_source is not None:
        suffixes.append(subtitle_source.suffix)
    output_stem = _available_export_stem(destination, requested_stem, suffixes)

    video_destination = destination / f"{output_stem}{video_source.suffix}"
    _copy_export_artifact(video_source, video_destination)
    subtitle_destination: Path | None = None
    if subtitle_source is not None:
        subtitle_destination = destination / f"{output_stem}{subtitle_source.suffix}"
        _copy_export_artifact(subtitle_source, subtitle_destination)

    published = dict(result)
    published["workspace_video_path"] = str(video_source)
    published["workspace_subtitle_path"] = str(subtitle_source) if subtitle_source is not None else None
    published["video_path"] = str(video_destination)
    published["subtitle_path"] = str(subtitle_destination) if subtitle_destination is not None else None
    published["published_directory"] = str(destination)
    published["published_filename"] = output_stem
    audit_project_event(
        project_id,
        "export.publish",
        context={
            "destination": str(destination),
            "video_path": str(video_destination),
            "subtitle_path": str(subtitle_destination) if subtitle_destination is not None else None,
            "create_project_subdirectory": create_project_subdirectory,
        },
    )
    return published


def choose_output_directory(initial_directory: str | None = None) -> str | None:
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        initial_path = Path(initial_directory).expanduser() if initial_directory else Path.home()
        if not initial_path.exists():
            initial_path = next((parent for parent in initial_path.parents if parent.exists()), Path.home())
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            title="出力先フォルダを選択",
            initialdir=str(initial_path),
            mustexist=False,
        )
        return str(Path(selected).resolve()) if selected else None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"フォルダ選択画面を開けません: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()


def configured_export_directory(project_id: str, app_settings: dict | None = None) -> Path:
    base = require_project(project_id)
    settings = app_settings or {}
    configured_root = str(settings.get("default_output_directory") or "").strip()
    if not configured_root:
        return base / "output"
    root = Path(configured_root).expanduser()
    if not root.is_absolute():
        raise HTTPException(status_code=400, detail="既定の出力先は絶対パスで指定してください")
    if settings.get("output_create_project_subdirectory", True) is not False:
        info = project_info(project_id)
        root = root / sanitize_export_name(info.get("project_name"), project_id)
    return root.resolve()


def open_directory_in_file_manager(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", str(path)], close_fds=True)
        return
    raise HTTPException(status_code=501, detail="このOSのフォルダ表示には未対応です")


def create_project_dirs(base: Path) -> None:
    for name in ["source", "audio", "transcript", "subtitles", "analysis", "preview", "output", "decoration", "temp/segments", "temp/logs"]:
        (base / name).mkdir(parents=True, exist_ok=True)


def create_project_from_local_file(source_file: Path, project_name: str | None = None) -> dict:
    ext = source_file.suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise HTTPException(status_code=400, detail="対応形式は mp4, mkv, mov, webm です")
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="動画ファイルが存在しません")
    default_name = f"{source_file.stem}_{datetime.now().strftime('%Y%m%d')}"
    resolved_name = project_name or default_name
    project_id = re.sub(r"[^A-Za-z0-9_-]+", "_", resolved_name).strip("_")
    project_id = project_id[:48] or "project"
    project_id = f"{project_id}_{uuid.uuid4().hex[:8]}"
    base = PROJECTS_DIR / project_id
    create_project_dirs(base)
    source_path = base / "source" / f"input{ext}"
    shutil.copy2(source_file, source_path)
    info = {
        "project_id": project_id,
        "project_name": resolved_name,
        "source_video": str(source_path.relative_to(base)),
        "source_video_name": source_file.name,
        "source_video_url": f"/api/projects/{project_id}/media/source/{source_path.name}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scenes": [],
        "decoration": {},
        "ui_state": {
            "default_emotion_preset_id": "emotion_neutral",
            "default_subtitle_style_preset_id": "subtitle_standard",
            "output_profile": "mp4_compat",
            "audio_stream_index": None,
            "subtitle_click_playback_mode": "jump",
            "ass_subtitle_defaults": dict(DEFAULT_ASS_SUBTITLE_STYLE),
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
        "global_event": {},
        "events": [],
        "effect_groups": presets.get("effect_groups", []),
        "screen_effect_stacks": presets.get("screen_effect_stacks", []),
        "font_presets": presets.get("font_presets", []),
        "layout_presets": merge_preset_list(presets.get("layout_presets", []), []),
        "frame_presets": merge_preset_list(presets.get("frame_presets", []), []),
        "screen_effect_targets": presets.get("screen_effect_targets", {"global_stack_ids": [], "scene_stack_ids": {}}),
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
        "global_event": decoration.get("global_event") or {},
        "events": decoration.get("events") or [],
        "effect_groups": decoration.get("effect_groups") or presets.get("effect_groups", []),
        "screen_effect_stacks": decoration.get("screen_effect_stacks") or presets.get("screen_effect_stacks", []),
        "font_presets": decoration.get("font_presets") or presets.get("font_presets", []),
        "layout_presets": decoration.get("layout_presets") or presets.get("layout_presets", []),
        "frame_presets": decoration.get("frame_presets") or presets.get("frame_presets", []),
        "screen_effect_targets": decoration.get("screen_effect_targets") or presets.get("screen_effect_targets", {"global_stack_ids": [], "scene_stack_ids": {}}),
        "scenes": decoration.get("scenes") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(path, current, backup=True)
    update_project_info(project_id, {"decoration": current, "scenes": current.get("scenes") or []})
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
    audio_streams = [s for s in raw.get("streams", []) if s.get("codec_type") == "audio"]
    default_audio_stream = next(
        (stream for stream in audio_streams if int((stream.get("disposition") or {}).get("default", 0) or 0) == 1),
        audio_streams[0] if audio_streams else None,
    )
    format_start_time = float(raw.get("format", {}).get("start_time", 0.0) or 0.0)
    audio_tracks = []
    for audio_position, stream in enumerate(audio_streams):
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        audio_tracks.append(
            {
                "stream_index": int(stream.get("index", audio_position)),
                "audio_position": audio_position,
                "codec_name": str(stream.get("codec_name") or "unknown"),
                "codec_long_name": str(stream.get("codec_long_name") or ""),
                "sample_rate": int(stream.get("sample_rate", 0) or 0) or None,
                "channels": int(stream.get("channels", 0) or 0) or None,
                "channel_layout": str(stream.get("channel_layout") or ""),
                "bit_rate": int(stream.get("bit_rate", 0) or 0) or None,
                "start_time_sec": float(stream.get("start_time", format_start_time) or format_start_time),
                "timeline_offset_sec": round(float(stream.get("start_time", format_start_time) or format_start_time) - format_start_time, 6),
                "language": str(tags.get("language") or "und"),
                "title": str(tags.get("title") or ""),
                "is_default": int(disposition.get("default", 0) or 0) == 1,
                "is_forced": int(disposition.get("forced", 0) or 0) == 1,
                "is_commentary": int(disposition.get("comment", 0) or 0) == 1,
            }
        )
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
        "has_audio": default_audio_stream is not None,
        "audio_sample_rate": int(default_audio_stream.get("sample_rate", 0)) if default_audio_stream else None,
        "audio_tracks": audio_tracks,
        "default_audio_stream_index": int(default_audio_stream.get("index")) if default_audio_stream else None,
        "file_size": int(raw.get("format", {}).get("size", path.stat().st_size)),
    }


def extract_audio(
    project_id: str,
    video_path: str,
    start_sec: float,
    end_sec: float,
    compute_profile: str = "auto",
    audio_stream_index: int | None = None,
) -> dict:
    ensure_tool("ffmpeg")
    if start_sec < 0 or end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="指定区間が不正です")
    normalized_profile = normalize_compute_profile(compute_profile)
    base = require_project(project_id)
    media_info = probe_video(video_path)
    audio_tracks = media_info.get("audio_tracks") or []
    if not audio_tracks:
        raise HTTPException(status_code=400, detail="動画に音声トラックがありません")
    selected_stream_index = audio_stream_index
    if selected_stream_index is None:
        selected_stream_index = media_info.get("default_audio_stream_index")
    if selected_stream_index is None or not any(int(track["stream_index"]) == int(selected_stream_index) for track in audio_tracks):
        raise HTTPException(status_code=400, detail="指定した音声トラックが動画内にありません")
    selected_stream_index = int(selected_stream_index)
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
            "-map",
            f"0:{selected_stream_index}",
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
    isolated_cache = base / "analysis" / "voice_isolation" / "voice_isolated.wav"
    if isolated_cache.exists():
        isolated_cache.unlink()
    audit_project_event(
        project_id,
        "extract_audio",
        context={
            "start_sec": start_sec,
            "end_sec": end_sec,
            "compute_profile": normalized_profile,
            "audio_stream_index": selected_stream_index,
        },
    )
    return {
        "audio_path": str(output),
        "compute_profile": normalized_profile,
        "audio_stream_index": selected_stream_index,
    }


def prepare_audio_track_preview(project_id: str, audio_stream_index: int) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    source = project_source_video(project_id)
    media_info = probe_video(str(source))
    selected_track = next(
        (track for track in media_info.get("audio_tracks") or [] if int(track.get("stream_index", -1)) == int(audio_stream_index)),
        None,
    )
    if selected_track is None:
        raise HTTPException(status_code=400, detail="指定した音声トラックが動画内にありません")
    output = base / "preview" / f"audio_track_{int(audio_stream_index)}.m4a"
    output.parent.mkdir(parents=True, exist_ok=True)
    cache_hit = output.exists() and output.stat().st_mtime >= source.stat().st_mtime
    if not cache_hit:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:{int(audio_stream_index)}",
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(output),
            ],
            base / "temp" / "logs" / f"audio_track_preview_{int(audio_stream_index)}.log",
        )
    audit_project_event(
        project_id,
        "audio_track_preview.prepared",
        context={"audio_stream_index": int(audio_stream_index), "output_path": str(output)},
    )
    return {
        "audio_path": str(output),
        "audio_url": f"/api/projects/{project_id}/media/preview/{output.name}",
        "audio_stream_index": int(audio_stream_index),
        "timeline_offset_sec": float(selected_track.get("timeline_offset_sec", 0.0) or 0.0),
        "cached": cache_hit,
    }


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
    vad_threshold: float = 0.5,
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
    use_whisperx_alignment: bool = False,
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

    begin_transcription_progress(
        project_id,
        audio,
        engine,
        model,
        normalized_profile,
        voice_isolation_enabled,
        use_whisperx_alignment,
    )
    if voice_isolation_enabled:
        update_transcription_progress(project_id, "声とBGMを分離", "voice_isolation", 3, 25, 0.22)
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

    preparation_start = 25 if voice_isolation_enabled else 3
    preparation_end = 30 if voice_isolation_enabled else 10
    update_transcription_progress(project_id, "解析用音声を準備", "audio_preparation", preparation_start, preparation_end, 0.07)
    whisper_audio_path = prepared_audio(whisper_source_audio, "whisper")
    vad_audio_path = prepared_audio(vad_source_audio, "vad")
    update_transcription_progress(project_id, "Whisper文字起こし", "whisper_transcription", preparation_end, 78, 0.58)
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
        update_transcription_progress(project_id, "VAD発話区間を検出", "vad_detection", 78, 86, 0.08)
        vad_intervals = detect_vad_speech_intervals(
            project_id,
            vad_audio_path,
            vad_threshold=vad_threshold,
            min_speech_duration_sec=min_speech_duration_sec,
            min_silence_duration_sec=vad_min_silence_duration_ms / 1000.0,
            speech_pad_sec=vad_speech_pad_ms / 1000.0,
            merge_silence_gap_sec=merge_silence_gap_sec,
        )
    unfiltered_subtitles = [dict(item) for item in raw_subtitles]
    discarded_hallucinations: list[dict] = []
    if vad_intervals.get("speech_intervals"):
        raw_subtitles, discarded_hallucinations = filter_repetitive_hallucinations(
            raw_subtitles,
            vad_intervals.get("speech_intervals", []),
        )
        if discarded_hallucinations:
            audit_project_detail_event(
                project_id,
                "transcribe.hallucination_filter",
                stream="processing",
                context={
                    "discarded_count": len(discarded_hallucinations),
                    "kept_count": len(raw_subtitles),
                    "items": discarded_hallucinations,
                },
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
    update_transcription_progress(project_id, "波形と字幕を解析", "waveform_analysis", 86, 93, 0.07)
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
    result["unfiltered_subtitles"] = unfiltered_subtitles
    result["raw_subtitles"] = raw_subtitles
    result["discarded_hallucination_subtitles"] = discarded_hallucinations
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
        "algorithm": "vad_boundary_limited_v2",
        "pre_margin_sec": pre_margin_sec,
        "post_margin_sec": post_margin_sec,
        "min_speech_duration_sec": min_speech_duration_sec,
        "merge_silence_gap_sec": merge_silence_gap_sec,
        "silence_threshold_db": silence_threshold_db,
        "max_match_gap_sec": 0.5,
        "min_overlap_ratio": 0.1,
        "max_start_adjustment_sec": 0.75,
        "max_end_adjustment_sec": 0.75,
        "preserve_subtitle_units": True,
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
        "hallucination_filter": {
            "enabled": bool(vad_intervals.get("speech_intervals")),
            "discarded_count": len(discarded_hallucinations),
            "policy": "repetition_with_weak_vad_support",
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
        update_transcription_progress(project_id, "字幕タイミングを補正", "subtitle_alignment", 93, 98, 0.12 if use_whisperx_alignment else 0.04)
        try:
            if use_whisperx_alignment:
                aligned_result = align_subtitles_with_whisperx(project_id, whisper_audio_path, result, waveform_profile=waveform_profile)
                aligned_subtitles = aligned_result.get("aligned_subtitles", []) or aligned_result.get("subtitles", [])
                result.update(
                    {
                        "alignment_engine": aligned_result.get("alignment_engine"),
                        "alignment_language": aligned_result.get("alignment_language"),
                        "aligned_transcription": aligned_result.get("aligned_transcription", []),
                        "aligned_segments": aligned_result.get("aligned_segments", []),
                        "waveform_refined_subtitles": aligned_result.get("waveform_refined_subtitles", []),
                        "whisperx_aligned_srt_path": aligned_result.get("whisperx_aligned_srt_path"),
                    }
                )
            else:
                aligned_subtitles = apply_vad_subtitle_corrections(
                    raw_subtitles,
                    result.get("vad_intervals", []),
                    subtitle_start_strategy="hybrid",
                    pre_margin_sec=pre_margin_sec,
                    post_margin_sec=post_margin_sec,
                )
            if aligned_subtitles:
                result["subtitles"] = aligned_subtitles
                result["aligned_subtitles"] = aligned_subtitles
                if use_whisperx_alignment and result.get("whisperx_aligned_srt_path"):
                    aligned_srt_path = Path(result["whisperx_aligned_srt_path"])
                else:
                    aligned_srt_path = base / "subtitles" / "aligned_vad.srt"
                    write_srt(aligned_subtitles, aligned_srt_path)
                result["aligned_srt_path"] = str(aligned_srt_path)
                result["alignment_engine"] = result.get("alignment_engine") or ("whisperx" if use_whisperx_alignment else "vad")
                result["alignment_status"] = "ok"
        except Exception as exc:
            alignment_error = str(exc)
            result["alignment_error"] = alignment_error
            result["alignment_status"] = "fallback_vad"

    result["processing_summary"]["alignment"] = {
        "enabled": align_timestamps,
        "engine": result.get("alignment_engine", "none"),
        "device": "cpu" if align_timestamps else "none",
        "status": result.get("alignment_status", "skipped" if not align_timestamps else "unknown"),
        "heavy": bool(use_whisperx_alignment),
    }

    update_transcription_progress(project_id, "字幕ファイルを保存", "subtitle_save", 98, 99.5, 0.02)
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
                "use_whisperx_alignment": use_whisperx_alignment,
                "alignment_engine": result.get("alignment_engine"),
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


def _subtitle_source_relative_bounds(item: dict, source_range_start: float) -> tuple[float, float]:
    if item.get("range_relative_start_sec") is not None:
        start = float(item.get("range_relative_start_sec") or 0.0)
        end = float(item.get("range_relative_end_sec", start) or start)
        return start, max(start, end)
    for start_key, end_key in (
        ("original_start_sec", "original_end_sec"),
        ("source_start_sec", "source_end_sec"),
    ):
        if item.get(start_key) is not None:
            start = float(item.get(start_key) or 0.0) - source_range_start
            end = float(item.get(end_key, start + source_range_start) or (start + source_range_start)) - source_range_start
            return start, max(start, end)
    start = float(item.get("start_sec", item.get("output_start_sec", 0.0)) or 0.0)
    end = float(item.get("end_sec", item.get("output_end_sec", start)) or start)
    return start, max(start, end)


def merge_range_transcription_subtitles(
    existing_subtitles: list[dict],
    replacement_subtitles: list[dict],
    range_start_sec: float,
    range_end_sec: float,
    source_range_start: float,
    replacement_mode: str = "text_and_timing",
) -> dict:
    mode = replacement_mode if replacement_mode in {"text_only", "text_and_timing"} else "text_and_timing"
    existing = [copy.deepcopy(item) for item in existing_subtitles]
    replacements = [copy.deepcopy(item) for item in replacement_subtitles]

    def overlap_with_range(item: dict) -> float:
        start, end = _subtitle_source_relative_bounds(item, source_range_start)
        return max(0.0, min(end, range_end_sec) - max(start, range_start_sec))

    affected = [item for item in existing if overlap_with_range(item) > 0.0]
    unaffected = [item for item in existing if overlap_with_range(item) <= 0.0]
    affected_ids = [str(item.get("id") or "") for item in affected]

    if mode == "text_only":
        merged = existing
        for item in affected:
            old_start, old_end = _subtitle_source_relative_bounds(item, source_range_start)
            matches: list[tuple[float, float, dict]] = []
            for replacement in replacements:
                new_start, new_end = _subtitle_source_relative_bounds(replacement, source_range_start)
                overlap = max(0.0, min(old_end, new_end) - max(old_start, new_start))
                if overlap > 0.0:
                    matches.append((new_start, overlap, replacement))
            if matches:
                matches.sort(key=lambda value: value[0])
                texts = [str(value[2].get("text") or "").strip() for value in matches]
                item["text"] = "\n".join(text for text in texts if text)
    else:
        used_existing_ids: set[str] = set()
        timing_keys = {
            "id", "text", "start_sec", "end_sec", "range_relative_start_sec", "range_relative_end_sec",
            "source_start_sec", "source_end_sec", "original_start_sec", "original_end_sec", "original_start",
            "original_end", "whisper_start_sec", "whisper_end_sec", "corrected_start_sec", "corrected_end_sec",
            "vad_start_sec", "vad_end_sec", "auto_start_sec", "auto_end_sec", "manual_start_sec", "manual_end_sec",
            "selected_start_sec", "selected_end_sec", "start_timing_source", "end_timing_source",
            "edited_start_sec", "edited_end_sec", "edited_start", "edited_end", "output_start_sec", "output_end_sec",
            "segment_id", "split_piece_index", "split_piece_total", "split_original_id", "split_pieces",
        }
        for replacement in replacements:
            new_start, new_end = _subtitle_source_relative_bounds(replacement, source_range_start)
            best: dict | None = None
            best_overlap = 0.0
            for item in affected:
                old_start, old_end = _subtitle_source_relative_bounds(item, source_range_start)
                overlap = max(0.0, min(old_end, new_end) - max(old_start, new_start))
                if overlap > best_overlap:
                    best = item
                    best_overlap = overlap
            if best:
                for key, value in best.items():
                    if key not in timing_keys and key not in replacement:
                        replacement[key] = copy.deepcopy(value)
                best_id = str(best.get("id") or "")
                if best_id and best_id not in used_existing_ids:
                    replacement["id"] = best_id
                    used_existing_ids.add(best_id)
        merged = unaffected + replacements

    merged.sort(
        key=lambda item: (
            float(item.get("output_start_sec", item.get("range_relative_start_sec", 0.0)) or 0.0),
            float(item.get("output_end_sec", item.get("range_relative_end_sec", 0.0)) or 0.0),
        )
    )
    return {
        "replacement_mode": mode,
        "affected_subtitle_ids": affected_ids,
        "affected_subtitles": affected,
        "replacement_subtitles": replacements,
        "merged_subtitles": merged,
    }


def offset_subtitle_timing_candidates(item: dict, offset_sec: float, selected_start_sec: float, selected_end_sec: float) -> dict:
    shifted = dict(item)
    for timing_key in (
        "whisper_start_sec", "whisper_end_sec", "vad_start_sec", "vad_end_sec",
        "normalized_start_sec", "normalized_end_sec", "corrected_start_sec", "corrected_end_sec",
        "auto_start_sec", "auto_end_sec", "manual_start_sec", "manual_end_sec",
        "selected_start_sec", "selected_end_sec",
    ):
        if shifted.get(timing_key) is not None:
            shifted[timing_key] = round(float(offset_sec) + float(shifted[timing_key]), 3)
    shifted["auto_start_sec"] = round(selected_start_sec, 3)
    shifted["auto_end_sec"] = round(selected_end_sec, 3)
    shifted["selected_start_sec"] = round(selected_start_sec, 3)
    shifted["selected_end_sec"] = round(selected_end_sec, 3)
    return shifted


def transcribe_audio_range(
    project_id: str,
    start_sec: float,
    end_sec: float,
    existing_subtitles: list[dict],
    language: str = "ja",
    model: str = "small",
    compute_profile: str = "auto",
    engine: str = "whisper.cpp-vad",
    replacement_mode: str = "text_and_timing",
    analysis_padding_sec: float = 1.5,
    detection_mode: str = "vad",
    voice_isolation_enabled: bool = False,
    use_isolated_voice_for_vad: bool = False,
    use_isolated_voice_for_whisper: bool = False,
    vad_threshold: float = 0.5,
    vad_min_speech_duration_ms: int = 100,
    vad_min_silence_duration_ms: int = 80,
    vad_speech_pad_ms: int = 50,
    pre_margin_sec: float = 0.3,
    post_margin_sec: float = 0.5,
    min_speech_duration_sec: float = 0.2,
    merge_silence_gap_sec: float = 0.5,
    align_timestamps: bool = False,
) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    source_audio = resolve_project_path(project_id, "audio", "source_range.wav")
    if not source_audio.exists():
        raise HTTPException(status_code=404, detail="先に指定範囲の音声を抽出してください")
    if start_sec < 0 or end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="再文字起こし区間が不正です")
    with wave.open(str(source_audio), "rb") as wav_file:
        source_duration = wav_file.getnframes() / max(1, wav_file.getframerate())
    if start_sec >= source_duration:
        raise HTTPException(status_code=400, detail="再文字起こし開始位置が音声範囲外です")

    core_start = max(0.0, float(start_sec))
    core_end = min(source_duration, float(end_sec))
    padding = min(10.0, max(0.0, float(analysis_padding_sec)))
    analysis_start = max(0.0, core_start - padding)
    analysis_end = min(source_duration, core_end + padding)
    warnings: list[str] = []

    isolated_source: Path | None = None
    transcript_path = resolve_project_path(project_id, "transcript", "transcript.json")
    if voice_isolation_enabled and transcript_path.exists():
        try:
            transcript = read_json_repairing_extra_data(transcript_path)
            candidate = Path(str(transcript.get("voice_isolated_audio_path") or ""))
            if candidate.exists() and candidate.resolve().is_relative_to(base.resolve()):
                isolated_source = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            isolated_source = None
    if voice_isolation_enabled and not isolated_source:
        warnings.append("保存済みの声抽出音声がないため、この区間は元音声で解析しました")

    clip_id = uuid.uuid4().hex[:10]
    clip_cache: dict[str, Path] = {}

    def extract_clip(source: Path, purpose: str) -> Path:
        cache_key = str(source.resolve())
        if cache_key in clip_cache:
            return clip_cache[cache_key]
        output = base / "temp" / f"range_retranscribe_{clip_id}_{purpose}.wav"
        run_command(
            [
                "ffmpeg", "-y", "-ss", f"{analysis_start:.3f}", "-to", f"{analysis_end:.3f}",
                "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
            ],
            base / "temp" / "logs" / f"range_retranscribe_{clip_id}_{purpose}.log",
        )
        clip_cache[cache_key] = output
        return output

    whisper_full_source = isolated_source if use_isolated_voice_for_whisper and isolated_source else source_audio
    vad_full_source = isolated_source if use_isolated_voice_for_vad and isolated_source else source_audio
    whisper_clip = extract_clip(whisper_full_source, "whisper")
    vad_clip = extract_clip(vad_full_source, "vad")
    normalized_profile = normalize_compute_profile(compute_profile)

    if engine == "whisper.cpp":
        result = transcribe_with_whisper_cpp(project_id, str(whisper_clip), language, model, normalized_profile)
    elif engine == "whisper.cpp-vad":
        result = transcribe_with_whisper_cpp_vad(
            project_id, str(whisper_clip), language, model, normalized_profile,
            vad_threshold=vad_threshold,
            vad_min_speech_duration_ms=vad_min_speech_duration_ms,
            vad_min_silence_duration_ms=vad_min_silence_duration_ms,
            vad_speech_pad_ms=vad_speech_pad_ms,
        )
    elif engine in {"faster-whisper", "faster-whisper-vad"}:
        result = transcribe_with_faster_whisper(
            project_id, str(whisper_clip), language, model,
            vad_filter=engine == "faster-whisper-vad", word_timestamps=engine == "faster-whisper-vad",
        )
    else:
        try:
            import whisper
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"openai-whisperを読み込めません: {exc}") from exc
        whisper_model = whisper.load_model(model)
        result = whisper_model.transcribe(str(whisper_clip), language=language, verbose=False)

    raw_subtitles = normalize_subtitle_durations(subtitles_from_whisper(result))
    vad_intervals: list[dict] = []
    vad_required = detection_mode in {"vad", "hybrid"} or align_timestamps
    if vad_required:
        vad_result = detect_vad_speech_intervals(
            project_id,
            str(vad_clip),
            compute_profile=normalized_profile,
            vad_threshold=vad_threshold,
            min_speech_duration_sec=min_speech_duration_sec,
            min_silence_duration_sec=vad_min_silence_duration_ms / 1000.0,
            speech_pad_sec=vad_speech_pad_ms / 1000.0,
            merge_silence_gap_sec=merge_silence_gap_sec,
        )
        vad_intervals = vad_result.get("speech_intervals", [])
        if vad_intervals:
            raw_subtitles, _ = filter_repetitive_hallucinations(raw_subtitles, vad_intervals)
        vad_supported_subtitles: list[dict] = []
        for subtitle in raw_subtitles:
            subtitle_start = float(subtitle.get("output_start_sec", subtitle.get("start_sec", 0.0)) or 0.0)
            subtitle_end = float(subtitle.get("output_end_sec", subtitle.get("end_sec", subtitle_start)) or subtitle_start)
            subtitle_duration = max(0.001, subtitle_end - subtitle_start)
            speech_overlap = sum(
                max(
                    0.0,
                    min(subtitle_end, float(interval.get("end_sec", interval.get("speech_end_sec", 0.0)) or 0.0))
                    - max(subtitle_start, float(interval.get("start_sec", interval.get("speech_start_sec", 0.0)) or 0.0)),
                )
                for interval in vad_intervals
            )
            if speech_overlap >= min(0.10, subtitle_duration * 0.10):
                vad_supported_subtitles.append(subtitle)
        removed_without_vad = len(raw_subtitles) - len(vad_supported_subtitles)
        raw_subtitles = vad_supported_subtitles
        if removed_without_vad:
            warnings.append(f"VADの発話裏付けがない候補を{removed_without_vad}件除外しました")
    if align_timestamps and vad_intervals:
        raw_subtitles = apply_vad_subtitle_corrections(
            raw_subtitles,
            vad_intervals,
            subtitle_start_strategy="hybrid",
            pre_margin_sec=pre_margin_sec,
            post_margin_sec=post_margin_sec,
        )

    plan_path = resolve_project_path(project_id, "edit_plan.json")
    plan = load_project_edit_plan(project_id) if plan_path.exists() else {}
    source_range = plan.get("source_range") or {"start_sec": 0.0, "end_sec": source_duration}
    source_range_start = float(source_range.get("start_sec", 0.0) or 0.0)
    segments = plan.get("segments") or [
        {
            "id": "seg_full",
            "enabled": True,
            "range_relative_start_sec": 0.0,
            "range_relative_end_sec": source_duration,
            "output_start_sec": 0.0,
            "output_end_sec": source_duration,
        }
    ]
    replacements: list[dict] = []
    for index, subtitle in enumerate(raw_subtitles, start=1):
        local_start = float(subtitle.get("output_start_sec", subtitle.get("start_sec", 0.0)) or 0.0)
        local_end = float(subtitle.get("output_end_sec", subtitle.get("end_sec", local_start)) or local_start)
        relative_start = analysis_start + local_start
        relative_end = analysis_start + local_end
        if min(relative_end, core_end) <= max(relative_start, core_start):
            continue
        relative_start = max(core_start, relative_start)
        relative_end = min(core_end, relative_end)
        if relative_end <= relative_start:
            continue
        shifted_subtitle = offset_subtitle_timing_candidates(subtitle, analysis_start, relative_start, relative_end)
        replacements.append(
            {
                **shifted_subtitle,
                "id": f"sub_range_{clip_id}_{index:03d}",
                "range_relative_start_sec": round(relative_start, 3),
                "range_relative_end_sec": round(relative_end, 3),
                "start_sec": round(relative_start, 3),
                "end_sec": round(relative_end, 3),
            }
        )
    replacements = map_subtitles_to_output(
        replacements,
        segments,
        source_range_start,
        float(source_range.get("end_sec", source_range_start + source_duration) or (source_range_start + source_duration)),
    )
    merge_result = merge_range_transcription_subtitles(
        existing_subtitles,
        replacements,
        core_start,
        core_end,
        source_range_start,
        replacement_mode,
    )
    audit_project_event(
        project_id,
        "transcribe_audio_range",
        context={
            "range_start_sec": core_start,
            "range_end_sec": core_end,
            "analysis_start_sec": analysis_start,
            "analysis_end_sec": analysis_end,
            "engine": engine,
            "model": model,
            "replacement_mode": merge_result["replacement_mode"],
            "affected_count": len(merge_result["affected_subtitle_ids"]),
            "replacement_count": len(replacements),
            "warnings": warnings,
        },
    )
    audit_project_detail_event(
        project_id,
        "transcribe_audio_range.proposal",
        stream="processing",
        context={
            "clip_id": clip_id,
            "range_start_sec": core_start,
            "range_end_sec": core_end,
            "affected_subtitle_ids": merge_result["affected_subtitle_ids"],
            "replacement_subtitles": [
                {
                    "id": item.get("id"),
                    "range_relative_start_sec": item.get("range_relative_start_sec"),
                    "range_relative_end_sec": item.get("range_relative_end_sec"),
                    "output_start_sec": item.get("output_start_sec"),
                    "output_end_sec": item.get("output_end_sec"),
                    "text": item.get("text", ""),
                }
                for item in replacements
            ],
            "warnings": warnings,
        },
    )
    finish_transcription_progress(project_id, success=True)
    return {
        **merge_result,
        "range_start_sec": round(core_start, 3),
        "range_end_sec": round(core_end, 3),
        "analysis_start_sec": round(analysis_start, 3),
        "analysis_end_sec": round(analysis_end, 3),
        "engine": result.get("engine", engine),
        "model": result.get("model", model),
        "device": result.get("device", "auto"),
        "warnings": warnings,
        "vad_intervals": [
            {"start_sec": round(analysis_start + float(item.get("start_sec", item.get("start", 0.0)) or 0.0), 3),
             "end_sec": round(analysis_start + float(item.get("end_sec", item.get("end", 0.0)) or 0.0), 3)}
            for item in vad_intervals
        ],
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
    vad_threshold: float = 0.5,
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
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad

        return load_silero_vad(), (get_speech_timestamps,)
    except ImportError:
        pass
    try:
        model, utils = torch.hub.load(
            "snakers4/silero-vad:v6.2.1",
            "silero_vad",
            trust_repo=True,
        )
        return model, utils
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Silero VAD 6.2.1を読み込めません: {exc}") from exc


def detect_silero_speech_intervals(
    audio_path: str,
    *,
    vad_threshold: float = 0.5,
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

    segments = copy.deepcopy(transcript.get("segments") or [])
    if not segments:
        raise HTTPException(status_code=400, detail="align対象の字幕がありません")

    language = str(transcript.get("language") or "ja")
    device = "cpu"
    model_a, metadata = load_whisperx_align_model(language, device)
    audio = whisperx.load_audio(str(audio_file))
    audio_duration_sec = float(len(audio)) / 16000.0
    input_end_sec = max((float(item.get("end", 0.0) or 0.0) for item in segments), default=0.0)
    if input_end_sec > audio_duration_sec + 1.0:
        raise HTTPException(
            status_code=500,
            detail=(
                "Whisper字幕時刻が解析音声長を超えています: "
                f"subtitle_end={input_end_sec:.3f}, audio_duration={audio_duration_sec:.3f}"
            ),
        )
    aligned = whisperx.align(segments, model_a, metadata, audio, device, return_char_alignments=False)
    aligned_segments = aligned.get("segments") or []
    for source_segment, aligned_segment in zip(segments, aligned_segments):
        source_start = float(source_segment.get("start", 0.0) or 0.0)
        source_end = float(source_segment.get("end", source_start) or source_start)
        aligned_start = float(aligned_segment.get("start", source_start) or source_start)
        aligned_end = float(aligned_segment.get("end", source_end) or source_end)
        if (
            not math.isfinite(aligned_start)
            or not math.isfinite(aligned_end)
            or aligned_start < source_start - 0.5
            or aligned_end > source_end + 0.5
            or aligned_end > audio_duration_sec + 0.5
        ):
            raise HTTPException(
                status_code=500,
                detail=(
                    "WhisperXの補正時刻が元区間または音声長を超えたため採用しません: "
                    f"source={source_start:.3f}-{source_end:.3f}, "
                    f"aligned={aligned_start:.3f}-{aligned_end:.3f}, "
                    f"audio_duration={audio_duration_sec:.3f}"
                ),
            )
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


@lru_cache(maxsize=1)
def whisper_cpp_runtime_version() -> str:
    if not WHISPER_CPP_EXE.exists():
        return "missing"
    try:
        proc = subprocess.run(
            [str(WHISPER_CPP_EXE), "--version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        match = re.search(r"whisper\.cpp version:\s*([^\s]+)", f"{proc.stdout}\n{proc.stderr}")
        return match.group(1) if match else "unknown"
    except Exception:
        return "unknown"


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
            "-mc",
            "0",
            "-nfa",
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
        "runtime_version": whisper_cpp_runtime_version(),
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
    vad_threshold: float = 0.5,
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
            "-mc",
            "0",
            "-nfa",
            "--vad",
            "-vm",
            path_for_cli(vad_model_path),
            "-vt",
            f"{float(vad_threshold):.2f}",
            "-vspd",
            str(int(vad_min_speech_duration_ms)),
            "-vsd",
            str(int(vad_min_silence_duration_ms)),
            "-vmsd",
            "30",
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
    transcription = normalize_whisper_cpp_vad_transcription(raw.get("transcription", []))
    segments: list[dict] = []
    for item in transcription:
        offsets = item.get("offsets", {})
        tokens = item.get("tokens") or []
        token_starts = [float(token.get("offsets", {}).get("from", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        token_ends = [float(token.get("offsets", {}).get("to", 0)) / 1000.0 for token in tokens if not str(token.get("text", "")).startswith("[_")]
        start = min(token_starts) if token_starts else float(offsets.get("from", 0)) / 1000.0
        end = max(token_ends) if token_ends else float(offsets.get("to", 0)) / 1000.0
        segments.append({"start": start, "end": end, "text": str(item.get("text", "")).strip()})
    timeline_max_end_sec = max((float(item.get("end", 0.0)) for item in segments), default=0.0)
    audit_project_detail_event(
        project_id,
        "transcribe.whisper_cpp_vad_timeline",
        stream="processing",
        context={
            "mapping": "source_segment_anchored_v2",
            "segment_count": len(segments),
            "timeline_max_end_sec": round(timeline_max_end_sec, 3),
        },
    )
    return {
        "language": raw.get("result", {}).get("language", language),
        "engine": "whisper.cpp-vad",
        "runtime_version": whisper_cpp_runtime_version(),
        "model": str(model_path),
        "vad_model": str(vad_model_path),
        "device": device,
        "gpu_used": device == "vulkan",
        "vad_threshold": float(vad_threshold),
        "vad_min_speech_duration_ms": int(vad_min_speech_duration_ms),
        "vad_min_silence_duration_ms": int(vad_min_silence_duration_ms),
        "vad_speech_pad_ms": int(vad_speech_pad_ms),
        "vad_token_timebase": "source_segment_anchored_v2",
        "timeline_max_end_sec": round(timeline_max_end_sec, 3),
        "transcription": transcription,
        "segments": segments,
        "raw": raw,
    }


def normalize_whisper_cpp_vad_transcription(raw_transcription: list[dict]) -> list[dict]:
    """Map VAD-compressed token offsets back into each source-audio segment.

    whisper.cpp reports each segment's offsets on the original audio timeline,
    while token offsets are on the concatenated VAD speech timeline.  Adding
    both values accumulates removed silence and creates progressive drift.
    """
    transcription: list[dict] = []
    for item in raw_transcription or []:
        adjusted = dict(item)
        item_offsets = dict(adjusted.get("offsets", {}))
        item_start_ms = int(float(item_offsets.get("from", 0) or 0))
        item_end_ms = max(item_start_ms, int(float(item_offsets.get("to", item_start_ms) or item_start_ms)))
        raw_tokens = adjusted.get("tokens") or []
        content_tokens = [token for token in raw_tokens if not str(token.get("text", "")).startswith("[_")]
        anchor_candidates = [
            int(float(token.get("offsets", {}).get("from", 0) or 0))
            for token in content_tokens
            if token.get("offsets", {}).get("from") is not None
        ]
        compressed_anchor_ms = min(anchor_candidates) if anchor_candidates else 0
        tokens = []
        for token in raw_tokens:
            token_offsets = dict(token.get("offsets", {}))
            if "from" in token_offsets:
                relative_from = int(float(token_offsets.get("from", 0) or 0)) - compressed_anchor_ms
                token_offsets["from"] = max(item_start_ms, min(item_end_ms, item_start_ms + relative_from))
            if "to" in token_offsets:
                relative_to = int(float(token_offsets.get("to", 0) or 0)) - compressed_anchor_ms
                token_offsets["to"] = max(
                    int(token_offsets.get("from", item_start_ms)),
                    min(item_end_ms, item_start_ms + relative_to),
                )
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
    return transcription


def _render_plan_media(
    project_id: str,
    plan: dict,
    preview: bool = False,
    burn_subtitles: bool = False,
    persist_final_plan: bool = False,
    output_profile: str | None = None,
    subtitle_mode: str = "external",
    subtitle_format: str = "srt",
) -> dict:
    ensure_tool("ffmpeg")
    base = require_project(project_id)
    settings = plan.get("settings", {})
    export_profile = resolve_export_profile(project_id, output_profile)
    subtitle_mode, subtitle_format = normalize_subtitle_export_options(
        subtitle_mode,
        subtitle_format,
        burn_subtitles=burn_subtitles,
    )
    if preview:
        subtitle_mode, subtitle_format = "external", "srt"
    transcript_path = base / "transcript" / "transcript.json"
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.exists() else {}
    segments = [s for s in plan.get("segments", []) if s.get("enabled", True)]
    if not segments:
        raise HTTPException(status_code=400, detail="出力対象の区間がありません")
    segment_dir = base / "temp" / "segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_files: list[Path] = []
    source = project_source_video(project_id)
    project_ui_state = project_info(project_id).get("ui_state") or {}
    selected_audio_stream_index = project_ui_state.get("audio_stream_index")
    if selected_audio_stream_index is not None:
        try:
            selected_audio_stream_index = int(selected_audio_stream_index)
        except (TypeError, ValueError):
            selected_audio_stream_index = None
    output_audio_mode = str(plan.get("settings", {}).get("output_audio_mode", transcript.get("output_audio_mode", "original"))).strip().lower()
    isolated_audio_source = None
    if output_audio_mode == "isolated_voice":
        candidate = transcript.get("voice_isolated_audio_path") or transcript.get("vad_audio_path") or transcript.get("whisper_audio_path")
        if candidate and Path(candidate).exists():
            isolated_audio_source = Path(candidate)
        else:
            output_audio_mode = "original"

    if preview:
        video_codec = "libx264"
        audio_codec = "aac"
        video_quality_args = ["-preset", "ultrafast", "-crf", "30"]
    else:
        video_codec = export_profile["video_codec"]
        audio_codec = export_profile["audio_codec"]
        video_quality_args = ["-preset", "veryfast", "-crf", "20"] if video_codec == "libx264" else []

    segment_ext = "mp4" if preview or export_profile["container"] == "mp4" else export_profile["extension"]
    container_args = ["-movflags", "+faststart"] if segment_ext == "mp4" else []

    for idx, segment in enumerate(segments, start=1):
        out = segment_dir / f"segment_{idx:04}.{segment_ext}"
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
                args += ["-vf", "scale='min(1280,iw)':-2", *video_quality_args]
            else:
                args += ["-c:v", video_codec, *video_quality_args]
            if selected_audio_stream_index is not None:
                args += ["-map", "0:v:0", "-map", f"0:{selected_audio_stream_index}"]
            args += ["-c:a", audio_codec, *container_args, str(out)]
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
                args += ["-vf", "scale='min(1280,iw)':-2", *video_quality_args]
            else:
                args += ["-c:v", video_codec, *video_quality_args]
            args += ["-c:a", audio_codec, *container_args, str(out)]
        run_command(args, base / "temp" / "logs" / f"segment_{idx:04}.log")
        segment_files.append(out)

    concat_list = base / "temp" / "segments" / "concat.txt"
    atomic_write_text(concat_list, "".join(f"file '{p.as_posix()}'\n" for p in segment_files))
    output_dir = base / ("preview" if preview else "output")
    final_ext = export_profile["extension"] if not preview else "mp4"
    video_out = output_dir / ("preview_low.mp4" if preview else f"final.{final_ext}")
    run_command(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(video_out)],
        base / "temp" / "logs" / ("preview_concat.log" if preview else "final_concat.log"),
    )
    srt_out = output_dir / ("preview.srt" if preview else "final.srt")
    write_srt(plan.get("subtitles", []), srt_out)
    ass_out: Path | None = None
    decoration_payload: dict | None = None
    output_info: dict | None = None
    canvas_size: tuple[int, int] | None = None
    if not preview and subtitle_format in {"plain_ass", "ass"}:
        output_info = probe_video(str(video_out))
        canvas_size = (int(output_info.get("width") or 1280), int(output_info.get("height") or 720))
        if subtitle_format == "ass":
            decoration_payload = decoration_payload_for_plan(project_id, plan, ass_source_srt=srt_out)
            ass_out = build_decoration_ass(
                project_id,
                decoration_payload,
                output_dir / "final.ass",
                include_caption_text=True,
                canvas_size=canvas_size,
            )
        else:
            ass_out = build_plain_ass(
                project_id,
                plan.get("subtitles", []),
                output_dir / "final.ass",
                canvas_size=canvas_size,
            )
    if not preview:
        should_burn_decoration = subtitle_mode == "burn" and subtitle_format == "ass"
        if should_burn_decoration:
            if decoration_payload is None or output_info is None or canvas_size is None or ass_out is None:
                raise HTTPException(status_code=500, detail="装飾ASSの生成に失敗しました")
            ass_path = ass_out
            screen_filter_expr, applied_effects = build_screen_effect_filter_chain(plan, decoration_payload)
            screen_overlays = generate_screen_effect_overlays(project_id, plan, decoration_payload, canvas_size=canvas_size)
            frame_overlays = generate_decoration_overlays(project_id, decoration_payload, canvas_size=canvas_size)
            output_duration = float(output_info.get("duration_sec") or max((float(seg.get("output_end_sec", 0.0) or 0.0) for seg in plan.get("segments") or []), default=0.0) or 0.1)
            flattened_frame_overlay = flatten_static_overlays_to_alpha_video(
                project_id,
                frame_overlays,
                output_duration,
                canvas_size,
                name="final_frame_overlays",
            )
            overlays = [*screen_overlays]
            if flattened_frame_overlay:
                overlays.append(flattened_frame_overlay)
            else:
                overlays.extend(frame_overlays)
            burn_cwd = ass_path.parent

            def burn_arg_path(path: Path | str) -> str:
                try:
                    return os.path.relpath(Path(path), burn_cwd)
                except Exception:
                    return str(path)

            subtitles_filter = f"subtitles=filename='{ass_path.name}'"
            burn_output = video_out.with_name(f"{video_out.stem}_decorated{video_out.suffix}")
            burn_args = [
                "ffmpeg",
                "-y",
                "-i",
                burn_arg_path(video_out),
            ]
            if overlays:
                for overlay in overlays:
                    if overlay.get("sequence"):
                        burn_args += [
                            "-framerate",
                            str(int(overlay.get("framerate") or 24)),
                            "-itsoffset",
                            f"{float(overlay.get('start_sec', 0.0) or 0.0):.3f}",
                            "-i",
                            burn_arg_path(overlay["path"]),
                        ]
                    elif overlay.get("animated"):
                        burn_args += ["-itsoffset", f"{float(overlay.get('start_sec', 0.0) or 0.0):.3f}", "-i", burn_arg_path(overlay["path"])]
                    else:
                        burn_args += ["-loop", "1", "-i", burn_arg_path(overlay["path"])]
                filter_parts: list[str] = []
                last_label = "[0:v]"
                if screen_filter_expr:
                    filter_parts.append(f"{last_label}{screen_filter_expr}[vfx]")
                    last_label = "[vfx]"
                for index, overlay in enumerate(overlays, start=1):
                    start_sec = float(overlay.get("start_sec", 0.0) or 0.0)
                    end_sec = float(overlay.get("end_sec", start_sec + 1.0) or (start_sec + 1.0))
                    filter_parts.append(
                        f"{last_label}[{index}:v]overlay=0:0:eof_action=pass:enable='between(t,{start_sec:.3f},{end_sec:.3f})'[vfx{index}]"
                    )
                    last_label = f"[vfx{index}]"
                filter_parts.append(f"{last_label}{subtitles_filter}[vout]")
                filter_script_path = base / "temp" / "logs" / "final_burn_filter.txt"
                atomic_write_text(filter_script_path, ";".join(filter_parts))
                burn_args += ["-filter_complex_script", burn_arg_path(filter_script_path), "-map", "[vout]", "-map", "0:a?"]
            else:
                filter_expr = ",".join([part for part in [screen_filter_expr, subtitles_filter] if part])
                if filter_expr:
                    burn_args += ["-vf", filter_expr]
            burn_args += [
                "-c:v",
                video_codec,
                *video_quality_args,
                "-c:a",
                audio_codec,
                *(["-movflags", "+faststart"] if export_profile["container"] == "mp4" else []),
                burn_arg_path(burn_output),
            ]
            run_command(
                burn_args,
                base / "temp" / "logs" / "final_burn.log",
                cwd=burn_cwd,
            )
            burn_output.replace(video_out)
            if applied_effects:
                audit_project_event(project_id, "render_from_plan.screen_effects_burned", context={"effects": applied_effects, "output_path": str(video_out)})
        elif subtitle_mode == "burn":
            burn_output = video_out.with_name(f"{video_out.stem}_subtitled{video_out.suffix}")
            burn_subtitle_path = ass_out if subtitle_format == "plain_ass" and ass_out is not None else srt_out
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video_out),
                    "-vf",
                    ffmpeg_subtitles_filter(burn_subtitle_path),
                    "-c:v",
                    video_codec,
                    *video_quality_args,
                    "-c:a",
                    "copy",
                    *( ["-movflags", "+faststart"] if export_profile["container"] == "mp4" else [] ),
                    str(burn_output),
                ],
                base / "temp" / "logs" / "final_srt_burn.log",
            )
            burn_output.replace(video_out)
        subtitle_track_codec = None
        if subtitle_mode == "embed":
            subtitle_source = ass_out if subtitle_format in {"plain_ass", "ass"} else srt_out
            if subtitle_source is None or not subtitle_source.exists():
                raise HTTPException(status_code=500, detail="埋め込み対象の字幕ファイルが見つかりません")
            video_out, subtitle_track_codec = mux_subtitle_track(
                project_id,
                video_out,
                subtitle_source,
                "ass" if subtitle_format in {"plain_ass", "ass"} else "srt",
            )
    if not preview:
        normalized_plan = normalize_edit_plan_source_video(project_id, plan)
        if persist_final_plan:
            atomic_write_json(output_dir / "edit_plan_final.json", normalized_plan)
    result_key = "preview_video_path" if preview else "video_path"
    audit_project_event(project_id, "render_from_plan", context={"preview": preview, "burn_subtitles": subtitle_mode == "burn", "subtitle_mode": subtitle_mode, "subtitle_format": subtitle_format, "subtitle_track_codec": subtitle_track_codec if not preview else None, "segment_count": len(segments), "output_audio_mode": output_audio_mode, "audio_mode_resolved": "isolated_voice" if isolated_audio_source else "original", "audio_stream_index": selected_audio_stream_index, "video_codec": video_codec, "audio_codec": audio_codec, "output_profile": export_profile["profile"], "container": video_out.suffix.lower().lstrip(".")})
    subtitle_path = ass_out if subtitle_format in {"plain_ass", "ass"} and ass_out is not None else srt_out
    return {
        result_key: str(video_out),
        "srt_path": str(srt_out),
        "ass_path": str(ass_out) if ass_out is not None else None,
        "subtitle_path": str(subtitle_path),
        "subtitle_mode": subtitle_mode,
        "subtitle_format": subtitle_format,
        "subtitle_track_codec": subtitle_track_codec if not preview else None,
        "video_url": f"/api/projects/{project_id}/media/{'preview' if preview else 'output'}/{video_out.name}",
    }


def render_from_plan(
    project_id: str,
    preview: bool = False,
    burn_subtitles: bool = False,
    output_profile: str | None = None,
    subtitle_mode: str = "external",
    subtitle_format: str = "srt",
) -> dict:
    base = require_project(project_id)
    plan = ensure_project_edit_plan(project_id)
    return _render_plan_media(
        project_id,
        plan,
        preview=preview,
        burn_subtitles=burn_subtitles,
        persist_final_plan=not preview,
        output_profile=output_profile,
        subtitle_mode=subtitle_mode,
        subtitle_format=subtitle_format,
    )


def export_cut_video_with_decoration_ass(project_id: str, output_profile: str | None = None) -> dict:
    base = require_project(project_id)
    plan = ensure_project_edit_plan(project_id)
    render_result = _render_plan_media(
        project_id,
        plan,
        preview=False,
        burn_subtitles=False,
        persist_final_plan=True,
        output_profile=output_profile,
    )
    video_path = Path(str(render_result.get("video_path") or ""))
    if not video_path.exists():
        raise HTTPException(status_code=500, detail="カット済み動画の出力に失敗しました")
    srt_path = Path(str(render_result.get("srt_path") or (base / "output" / "final.srt")))
    output_info = probe_video(str(video_path))
    canvas_size = (int(output_info.get("width") or 1280), int(output_info.get("height") or 720))
    decoration_payload = decoration_payload_for_plan(project_id, plan, ass_source_srt=srt_path)
    ass_path = build_decoration_ass(
        project_id,
        decoration_payload,
        base / "output" / "final.ass",
        include_caption_text=True,
        canvas_size=canvas_size,
    )
    audit_project_event(
        project_id,
        "decoration.export_ass_package",
        context={
            "video_path": str(video_path),
            "ass_path": str(ass_path),
            "srt_path": str(srt_path),
            "output_profile": output_profile,
            "canvas_size": canvas_size,
        },
    )
    return {
        "video_path": str(video_path),
        "ass_path": str(ass_path),
        "srt_path": str(srt_path),
        "video_url": render_result.get("video_url"),
    }


def render_from_plan_data(project_id: str, plan: dict, preview: bool = True, burn_subtitles: bool = False, output_profile: str | None = None) -> dict:
    base = require_project(project_id)
    (base / "temp" / "segments").mkdir(parents=True, exist_ok=True)
    return _render_plan_media(project_id, plan, preview=preview, burn_subtitles=burn_subtitles, persist_final_plan=False, output_profile=output_profile)

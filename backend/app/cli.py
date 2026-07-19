from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import audit_event, audit_project_event
from .edit_plan import build_edit_plan, build_speaker_roster
from .services import (
    create_project_from_local_file,
    atomic_write_json,
    cleanup_project_artifacts,
    detect_silence,
    extract_audio,
    load_project_edit_plan,
    normalize_edit_plan_source_video,
    normalize_compute_profile,
    probe_video,
    project_info,
    update_project_info,
    render_from_plan,
    resolve_project_path,
    transcribe_audio,
)
from .srt import write_srt
from .gemini_service import translate_project_subtitles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cutsubtitle")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe")
    p.add_argument("--video", required=True)

    p = sub.add_parser("new-project")
    p.add_argument("--video", required=True)
    p.add_argument("--name")

    p = sub.add_parser("extract-audio")
    p.add_argument("--project-id", required=True)
    p.add_argument("--video-path", required=True)
    p.add_argument("--start", type=float, required=True)
    p.add_argument("--end", type=float, required=True)
    p.add_argument("--compute-profile", default="auto", choices=["auto", "cpu", "gpu"])
    p.add_argument("--audio-stream-index", type=int)

    p = sub.add_parser("transcribe")
    p.add_argument("--project-id", required=True)
    p.add_argument("--audio-path", required=True)
    p.add_argument("--language", default="ja")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--compute-profile", default="auto", choices=["auto", "cpu", "gpu"])
    p.add_argument("--engine", default="whisper.cpp")
    p.add_argument("--silence-threshold-db", type=float, default=-35.0)
    p.add_argument("--detection-mode", default="silencedetect")
    p.add_argument("--voice-isolation-enabled", action="store_true")
    p.add_argument("--use-isolated-voice-for-vad", action="store_true")
    p.add_argument("--use-isolated-voice-for-whisper", action="store_true")

    p = sub.add_parser("detect-silence")
    p.add_argument("--project-id", required=True)
    p.add_argument("--audio-path", required=True)
    p.add_argument("--threshold-db", type=float, default=-35.0)
    p.add_argument("--min-silence-duration", type=float, default=0.7)
    p.add_argument("--compute-profile", default="auto", choices=["auto", "cpu", "gpu"])

    p = sub.add_parser("create-edit-plan")
    p.add_argument("--project-id", required=True)
    p.add_argument("--source-start", type=float, required=True)
    p.add_argument("--source-end", type=float, required=True)
    p.add_argument("--settings-json")

    p = sub.add_parser("save-subtitles")
    p.add_argument("--project-id", required=True)
    p.add_argument("--subtitles-json", required=True)

    p = sub.add_parser("translate-subtitles")
    p.add_argument("--project-id", required=True)
    p.add_argument("--model")
    p.add_argument("--source-language", default="en")
    p.add_argument("--target-language", default="ja")
    p.add_argument(
        "--display-mode",
        choices=["source_above", "translation_above", "source_only", "translation_only"],
        default="source_above",
    )

    p = sub.add_parser("preview")
    p.add_argument("--project-id", required=True)

    p = sub.add_parser("export")
    p.add_argument("--project-id", required=True)
    p.add_argument("--burn-subtitles", action="store_true")
    p.add_argument("--subtitle-mode", choices=["external", "burn", "embed"], default="external")
    p.add_argument("--subtitle-format", choices=["srt", "plain_ass", "ass"], default="srt")
    p.add_argument("--output-profile")

    p = sub.add_parser("cleanup")
    p.add_argument("--project-id", required=True)
    p.add_argument("--keep-audio", action="store_true")
    p.add_argument("--keep-preview", action="store_true")
    p.add_argument("--keep-analysis", action="store_true")
    p.add_argument("--keep-raw-subtitles", action="store_true")

    p = sub.add_parser("run-pipeline")
    p.add_argument("--config")
    p.add_argument("--video")
    p.add_argument("--name")
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("--language", default="ja")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--compute-profile", default="auto", choices=["auto", "cpu", "gpu"])
    p.add_argument("--audio-stream-index", type=int)
    p.add_argument("--engine", default="whisper.cpp")
    p.add_argument("--silence-threshold-db", type=float, default=-35.0)
    p.add_argument("--detection-mode", default="silencedetect")
    p.add_argument("--voice-isolation-enabled", action="store_true")
    p.add_argument("--use-isolated-voice-for-vad", action="store_true")
    p.add_argument("--use-isolated-voice-for-whisper", action="store_true")
    p.add_argument("--threshold-db", type=float, default=-35.0)
    p.add_argument("--min-silence-duration", type=float, default=0.7)
    p.add_argument("--auto-cut", dest="auto_cut", action="store_true")
    p.add_argument("--no-auto-cut", dest="auto_cut", action="store_false")
    p.add_argument("--settings-json")
    p.add_argument("--burn-subtitles", action="store_true")
    p.add_argument("--subtitle-mode", choices=["external", "burn", "embed"], default="external")
    p.add_argument("--subtitle-format", choices=["srt", "plain_ass", "ass"], default="srt")
    p.add_argument("--output-profile")
    p.add_argument("--auto-cleanup", action="store_true")
    p.add_argument("--report")

    return parser


def cmd_probe(args: argparse.Namespace) -> None:
    print(json.dumps(probe_video(args.video), ensure_ascii=False, indent=2))


def cmd_new_project(args: argparse.Namespace) -> None:
    info = create_project_from_local_file(Path(args.video), args.name)
    audit_event("cli.new_project", detail="project created", context={"project_id": info["project_id"]})
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_extract_audio(args: argparse.Namespace) -> None:
    result = extract_audio(args.project_id, args.video_path, args.start, args.end, args.compute_profile, args.audio_stream_index)
    audit_project_event(args.project_id, "cli.extract_audio")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_transcribe(args: argparse.Namespace) -> None:
    result = transcribe_audio(
        args.project_id,
        args.audio_path,
        args.language,
        args.model,
        args.compute_profile,
        args.engine,
        args.silence_threshold_db,
        detection_mode=args.detection_mode,
        voice_isolation_enabled=args.voice_isolation_enabled,
        use_isolated_voice_for_vad=args.use_isolated_voice_for_vad,
        use_isolated_voice_for_whisper=args.use_isolated_voice_for_whisper,
    )
    audit_project_event(
        args.project_id,
        "cli.transcribe",
        context={
            "engine": args.engine,
            "model": args.model,
            "silence_threshold_db": args.silence_threshold_db,
            "detection_mode": args.detection_mode,
            "voice_isolation_enabled": args.voice_isolation_enabled,
            "use_isolated_voice_for_vad": args.use_isolated_voice_for_vad,
            "use_isolated_voice_for_whisper": args.use_isolated_voice_for_whisper,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_detect_silence(args: argparse.Namespace) -> None:
    result = detect_silence(args.project_id, args.audio_path, args.threshold_db, args.min_silence_duration, args.compute_profile)
    audit_project_event(args.project_id, "cli.detect_silence")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_create_edit_plan(args: argparse.Namespace) -> None:
    base = resolve_project_path(args.project_id, "edit_plan.json").parent
    source_video = project_info(args.project_id).get("source_video")
    if not source_video:
        raise SystemExit("project.json に source_video がありません")
    transcript_path = resolve_project_path(args.project_id, "transcript", "transcript.json")
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path.exists() else {}
    silences = []
    silence_path = resolve_project_path(args.project_id, "temp", "silences.json")
    if silence_path.exists():
        silences = json.loads(silence_path.read_text(encoding="utf-8"))
    settings = json.loads(args.settings_json) if args.settings_json else {}
    plan = build_edit_plan(source_video, {"start_sec": args.source_start, "end_sec": args.source_end}, silences, transcript, settings)
    plan = normalize_edit_plan_source_video(args.project_id, plan)
    path = base / "edit_plan.json"
    atomic_write_json(path, plan, backup=True)
    write_srt(plan.get("subtitles", []), base / "subtitles" / "edited.srt")
    audit_project_event(args.project_id, "cli.create_edit_plan")
    print(json.dumps({"edit_plan_path": str(path), "edit_plan": plan}, ensure_ascii=False, indent=2))


def cmd_save_subtitles(args: argparse.Namespace) -> None:
    subtitles = json.loads(Path(args.subtitles_json).read_text(encoding="utf-8"))
    path = resolve_project_path(args.project_id, "edit_plan.json")
    plan = load_project_edit_plan(args.project_id)
    plan["subtitles"] = subtitles
    plan["speaker_roster"] = build_speaker_roster(subtitles)
    atomic_write_json(path, plan, backup=True)
    write_srt(subtitles, resolve_project_path(args.project_id, "subtitles", "edited.srt"))
    audit_project_event(args.project_id, "cli.save_subtitles")
    print(json.dumps({"edit_plan": plan}, ensure_ascii=False, indent=2))


def cmd_translate_subtitles(args: argparse.Namespace) -> None:
    result = translate_project_subtitles(
        args.project_id,
        args.model,
        args.source_language,
        args.target_language,
        args.display_mode,
    )
    audit_project_event(
        args.project_id,
        "cli.translate_subtitles",
        context={
            "model": result.get("model"),
            "source_language": args.source_language,
            "target_language": args.target_language,
            "display_mode": args.display_mode,
            "translated_count": result.get("translated_count", 0),
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_preview(args: argparse.Namespace) -> None:
    result = render_from_plan(args.project_id, preview=True)
    audit_project_event(args.project_id, "cli.preview")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_export(args: argparse.Namespace) -> None:
    subtitle_mode = "burn" if args.burn_subtitles else args.subtitle_mode
    result = render_from_plan(
        args.project_id,
        preview=False,
        burn_subtitles=args.burn_subtitles,
        subtitle_mode=subtitle_mode,
        subtitle_format=args.subtitle_format,
        output_profile=args.output_profile,
    )
    audit_project_event(
        args.project_id,
        "cli.export",
        context={
            "burn_subtitles": args.burn_subtitles,
            "subtitle_mode": subtitle_mode,
            "subtitle_format": args.subtitle_format,
            "output_profile": args.output_profile,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_cleanup(args: argparse.Namespace) -> None:
    result = cleanup_project_artifacts(
        args.project_id,
        keep_audio=args.keep_audio,
        keep_preview=args.keep_preview,
        keep_analysis=args.keep_analysis,
        keep_raw_subtitles=args.keep_raw_subtitles,
    )
    audit_project_event(
        args.project_id,
        "cli.cleanup",
        context={
            "keep_audio": args.keep_audio,
            "keep_preview": args.keep_preview,
            "keep_analysis": args.keep_analysis,
            "keep_raw_subtitles": args.keep_raw_subtitles,
            "removed_count": len(result.get("removed", [])),
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def load_json_config(path_text: str | None) -> dict:
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.exists():
        raise SystemExit(f"config file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def cmd_run_pipeline(args: argparse.Namespace) -> None:
    config = load_json_config(args.config)
    project_id: str | None = None
    cleanup = None
    video = config.get("video") or args.video
    if not video:
        raise SystemExit("video is required")
    name = config.get("name") or args.name
    start = float(config.get("start", args.start) or 0.0)
    end = float(config.get("end", args.end) or 0.0)
    if end <= start:
        raise SystemExit("end must be greater than start")
    language = config.get("language") or args.language
    model = config.get("model") or args.model
    compute_profile = config.get("compute_profile") or args.compute_profile
    audio_stream_index = config.get("audio_stream_index", args.audio_stream_index)
    if audio_stream_index is not None:
        audio_stream_index = int(audio_stream_index)
    engine = config.get("engine") or args.engine
    threshold_db = float(config.get("threshold_db", args.threshold_db))
    silence_threshold_db = float(config.get("silence_threshold_db", args.silence_threshold_db))
    detection_mode = config.get("detection_mode") or args.detection_mode
    voice_isolation_enabled = bool(config.get("voice_isolation_enabled", args.voice_isolation_enabled))
    use_isolated_voice_for_vad = bool(config.get("use_isolated_voice_for_vad", args.use_isolated_voice_for_vad))
    use_isolated_voice_for_whisper = bool(config.get("use_isolated_voice_for_whisper", args.use_isolated_voice_for_whisper))
    min_silence_duration = float(config.get("min_silence_duration", args.min_silence_duration))
    auto_cut = bool(config.get("auto_cut", args.auto_cut))
    auto_cleanup = bool(config.get("auto_cleanup", args.auto_cleanup))
    settings_json = config.get("settings_json") or args.settings_json
    burn_subtitles = bool(config.get("burn_subtitles", args.burn_subtitles))
    subtitle_mode = str(config.get("subtitle_mode") or args.subtitle_mode)
    subtitle_format = str(config.get("subtitle_format") or args.subtitle_format)
    if burn_subtitles:
        subtitle_mode = "burn"
    output_profile = config.get("output_profile") or args.output_profile
    subtitles_override = config.get("subtitles")

    try:
        project = create_project_from_local_file(Path(video), name)
        project_id = project["project_id"]
        if output_profile or audio_stream_index is not None:
            current_ui = dict(project.get("ui_state") or {})
            if output_profile:
                current_ui["output_profile"] = output_profile
            if audio_stream_index is not None:
                current_ui["audio_stream_index"] = audio_stream_index
            update_project_info(project_id, {"ui_state": current_ui})
        audit_project_event(project_id, "cli.run_pipeline.start")
        audio = extract_audio(project_id, project["source_video"], start, end, compute_profile, audio_stream_index)
        if subtitles_override is not None:
            transcript = {"engine": "manual", "subtitles": subtitles_override}
        else:
            transcript = transcribe_audio(
                project_id,
                audio["audio_path"],
                language,
                model,
                compute_profile,
                engine,
                silence_threshold_db,
                detection_mode=detection_mode,
                voice_isolation_enabled=voice_isolation_enabled,
                use_isolated_voice_for_vad=use_isolated_voice_for_vad,
                use_isolated_voice_for_whisper=use_isolated_voice_for_whisper,
            )
        silence_audio_path = transcript.get("vad_audio_path") or audio["audio_path"]
        if auto_cut:
            silences = detect_silence(project_id, silence_audio_path, threshold_db, min_silence_duration, compute_profile)
            atomic_write_json(Path(resolve_project_path(project_id, "temp", "silences.json")), silences["silences"])
        else:
            silences = {"silences": [], "compute_profile": normalize_compute_profile(compute_profile), "auto_cut": False}
            atomic_write_json(Path(resolve_project_path(project_id, "temp", "silences.json")), [])
        settings = json.loads(settings_json) if settings_json else {}
        settings.update(
            {
                "auto_cut": auto_cut,
                "silence_threshold_db": config.get("silence_threshold_db", settings.get("silence_threshold_db")),
                "detection_mode": detection_mode,
                "voice_isolation_enabled": voice_isolation_enabled,
                "use_isolated_voice_for_vad": use_isolated_voice_for_vad,
                "use_isolated_voice_for_whisper": use_isolated_voice_for_whisper,
                "output_profile": output_profile,
            }
        )
        plan = build_edit_plan(project["source_video"], {"start_sec": start, "end_sec": end}, silences["silences"], {"subtitles": transcript["subtitles"]}, settings)
        plan = normalize_edit_plan_source_video(project_id, plan)
        plan_path = resolve_project_path(project_id, "edit_plan.json")
        atomic_write_json(plan_path, plan, backup=True)
        write_srt(plan.get("subtitles", []), resolve_project_path(project_id, "subtitles", "edited.srt"))
        preview = render_from_plan(project_id, preview=True, output_profile=output_profile)
        final = render_from_plan(
            project_id,
            preview=False,
            burn_subtitles=burn_subtitles,
            subtitle_mode=subtitle_mode,
            subtitle_format=subtitle_format,
            output_profile=output_profile,
        )
        if auto_cleanup:
            cleanup = cleanup_project_artifacts(
                project_id,
                keep_audio=False,
                keep_preview=False,
                keep_analysis=False,
                keep_raw_subtitles=False,
            )
        audit_project_event(project_id, "cli.run_pipeline.complete")
        report = {
            "project": project,
            "audio": audio,
            "transcript": transcript,
            "silences": silences,
            "edit_plan_path": str(plan_path),
            "preview": preview,
            "final": final,
            "cleanup": cleanup,
            "config": config,
        }
        if args.report:
            atomic_write_json(Path(args.report), report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        if project_id and auto_cleanup:
            audit_project_event(project_id, "cli.run_pipeline.cleanup_skipped", context={"reason": "pipeline_failed"})
        raise


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "probe":
        cmd_probe(args)
    elif args.command == "new-project":
        cmd_new_project(args)
    elif args.command == "extract-audio":
        cmd_extract_audio(args)
    elif args.command == "transcribe":
        cmd_transcribe(args)
    elif args.command == "detect-silence":
        cmd_detect_silence(args)
    elif args.command == "create-edit-plan":
        cmd_create_edit_plan(args)
    elif args.command == "save-subtitles":
        cmd_save_subtitles(args)
    elif args.command == "translate-subtitles":
        cmd_translate_subtitles(args)
    elif args.command == "preview":
        cmd_preview(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    elif args.command == "run-pipeline":
        cmd_run_pipeline(args)


if __name__ == "__main__":
    main()

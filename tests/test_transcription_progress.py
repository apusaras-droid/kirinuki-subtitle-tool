import json
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import (
    begin_transcription_progress,
    estimate_transcription_duration,
    finish_transcription_progress,
    project_processing_progress,
    update_transcription_progress,
)


def _write_silent_wav(path: Path, duration_sec: float = 10.0) -> None:
    sample_rate = 16000
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(sample_rate * duration_sec))


def test_profile_estimate_scales_with_audio_duration():
    with TemporaryDirectory() as temp_dir, patch(
        "backend.app.services.TRANSCRIPTION_RUNTIME_HISTORY", Path(temp_dir) / "missing.json"
    ):
        short, source, _ = estimate_transcription_duration(60, "whisper.cpp-vad", "small", "gpu", False, False)
        long, _, _ = estimate_transcription_duration(600, "whisper.cpp-vad", "small", "gpu", False, False)
    assert source == "profile"
    assert long > short


def test_transcription_progress_reports_stage_and_remaining_time():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        audio = base / "audio" / "source_range.wav"
        history = base / "shared" / "history.json"
        _write_silent_wav(audio)
        (base / "temp" / "logs").mkdir(parents=True)
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.TRANSCRIPTION_RUNTIME_HISTORY", history),
            patch("backend.app.services.time.time", return_value=1000.0),
        ):
            begin_transcription_progress("sample", audio, "whisper.cpp-vad", "small", "gpu", False, False)
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.time.time", return_value=1005.0),
        ):
            update_transcription_progress("sample", "Whisper文字起こし", "whisper_transcription", 10, 78, 0.58)
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.time.time", return_value=1010.0),
        ):
            progress = project_processing_progress("sample")

        assert progress["active"] is True
        assert progress["stage_id"] == "whisper_transcription"
        assert 10 < progress["percent"] < 78
        assert progress["remaining_sec"] > 0
        assert progress["estimate"] is True

        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.TRANSCRIPTION_RUNTIME_HISTORY", history),
            patch("backend.app.services.time.time", return_value=1020.0),
        ):
            finish_transcription_progress("sample", success=True)
        saved = json.loads((base / "temp" / "transcription_progress.json").read_text(encoding="utf-8"))
        assert saved["status"] == "completed"
        assert history.exists()

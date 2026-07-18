from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.services import embedded_subtitle_output_spec, normalize_subtitle_export_options


@pytest.mark.parametrize(
    ("mode", "subtitle_format", "legacy_burn", "expected"),
    [
        ("external", "srt", False, ("external", "srt")),
        ("embed", "ass", False, ("embed", "ass")),
        ("external", "plain_ass", False, ("external", "plain_ass")),
        ("external", "srt", True, ("burn", "srt")),
        ("burn", "ass", False, ("burn", "ass")),
    ],
)
def test_normalize_subtitle_export_options(mode, subtitle_format, legacy_burn, expected):
    assert normalize_subtitle_export_options(mode, subtitle_format, legacy_burn) == expected


@pytest.mark.parametrize("mode", ["copy", "none", "invalid"])
def test_normalize_subtitle_export_options_rejects_invalid_mode(mode):
    with pytest.raises(HTTPException):
        normalize_subtitle_export_options(mode, "srt")


def test_mp4_srt_embedding_uses_mov_text():
    output, codec = embedded_subtitle_output_spec(Path("final.mp4"), "srt")
    assert output == Path("final.mp4")
    assert codec == "mov_text"


def test_ass_embedding_switches_to_mkv_to_preserve_styles():
    output, codec = embedded_subtitle_output_spec(Path("final.mp4"), "ass")
    assert output == Path("final.mkv")
    assert codec == "ass"


def test_mkv_srt_embedding_keeps_subrip_track():
    output, codec = embedded_subtitle_output_spec(Path("final.mkv"), "srt")
    assert output == Path("final.mkv")
    assert codec == "srt"

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services import build_decoration_ass, build_plain_ass


def test_build_decoration_ass_uses_project_default_and_subtitle_override():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        source_srt = base / "edited.srt"
        source_srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nテスト\n", encoding="utf-8")
        event = {
            "id": "sub_0001",
            "start_sec": 1,
            "end_sec": 3,
            "text": "テスト",
            "ass_style": {
                "enabled": True,
                "font_name": "Noto Serif JP",
                "font_size": 52,
                "primary_color": "#FFF7DE",
                "outline_color": "#112233",
                "outline_width": 4,
                "shadow_depth": 2,
                "bold": False,
                "italic": True,
                "alignment": 8,
                "margin_l": 70,
                "margin_r": 80,
                "margin_v": 40,
                "spacing": 1.5,
            },
        }
        project = {
            "ui_state": {
                "ass_subtitle_defaults": {
                    "font_name": "Noto Sans JP",
                    "font_size": 44,
                    "primary_color": "#FFFFFF",
                    "outline_color": "#000000",
                    "outline_width": 3,
                    "shadow_depth": 1,
                    "bold": True,
                    "italic": False,
                    "alignment": 2,
                    "margin_l": 60,
                    "margin_r": 60,
                    "margin_v": 48,
                    "spacing": 0,
                }
            }
        }
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value=project),
        ):
            output = build_decoration_ass(
                "sample",
                {"source_srt": str(source_srt), "events": [event]},
                base / "output.ass",
            )

        ass_text = output.read_text(encoding="utf-8")
        style = next(line for line in ass_text.splitlines() if line.startswith("Style:"))
        dialogue = next(line for line in ass_text.splitlines() if line.startswith("Dialogue:"))
        assert "Noto Sans JP,44" in style
        assert r"\an8\pos(640.0,40.0)" in dialogue
        assert r"\fnNoto Serif JP\fs52" in dialogue
        assert r"\3c&H00332211&\bord4\shad2\b0\i1\fsp1.5" in dialogue


def test_build_plain_ass_uses_ass_style_without_decoration_fields():
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        project = {
            "ui_state": {
                "ass_subtitle_defaults": {
                    "font_name": "Noto Sans JP",
                    "font_size": 44,
                    "primary_color": "#FFFFFF",
                    "outline_color": "#000000",
                    "outline_width": 3,
                    "shadow_depth": 1,
                    "bold": True,
                    "italic": False,
                    "alignment": 2,
                    "margin_l": 60,
                    "margin_r": 60,
                    "margin_v": 48,
                    "spacing": 0,
                }
            }
        }
        subtitle = {
            "output_start_sec": 1.0,
            "output_end_sec": 2.5,
            "text": "通常字幕★",
            "frame_preset_id": "frame_bubble_jagged",
            "effect_group_id": "effect_heart",
            "font_color": "#FF0000",
            "ass_style": {
                "enabled": True,
                "font_name": "Noto Serif JP",
                "font_size": 52,
                "primary_color": "#FFF7DE",
                "outline_color": "#112233",
                "outline_width": 4,
                "shadow_depth": 2,
                "alignment": 8,
                "margin_l": 70,
                "margin_r": 80,
                "margin_v": 40,
            },
        }
        with (
            patch("backend.app.services.require_project", return_value=base),
            patch("backend.app.services.project_info", return_value=project),
        ):
            output = build_plain_ass("sample", [subtitle], base / "plain.ass")

        text = output.read_text(encoding="utf-8")
        dialogue = next(line for line in text.splitlines() if line.startswith("Dialogue:"))
        assert r"\fnNoto Serif JP\fs52" in dialogue
        assert r"\1c&H00DEF7FF&\3c&H00332211&\bord4" in dialogue
        assert "frame_bubble_jagged" not in text
        assert "effect_heart" not in text
